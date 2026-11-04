"""
test_tag_field_engine.py — the one field table, exercised on real containers.

Two things are locked here that no mock can: the table's container keys are the
ones the suite wrote before this module existed (``TXXX:ALBUMGENRE``,
``CONTENTGROUP``, ``----:TXXX:ALBUMGENRE`` …), and a write through the engine
lands in a real file where mutagen reads it back.  A read-back through the
engine's own reader would prove nothing — it would agree with itself — so every
value assertion below reloads the file with mutagen directly.

The dry run is checked by outcome (bytes and ``st_mtime_ns``), not by a mock's
call log, because the gate lives in the write path: a mock that is never called
because the code took a different branch would pass a call-count assertion.

Changed in 2.4.2: new — plan WP-6 (C-M2), the one tag layer.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import mutagen
import pytest
from mutagen.id3 import TCON
from pydub import AudioSegment

from audio_suite_shared.audio_formats import FORMAT_MATRIX
from audio_suite_shared.batch_undo import active_batch, list_recent_batches
from audio_suite_shared.exceptions import AudioFormatError, AudioTagError
from audio_suite_shared.tag_field_engine import (
    APEV2,
    CONVENTIONS,
    FIELD_RULES,
    ID3,
    MP4,
    TRANSFORM_SLASH_GENRE,
    TRANSFORM_VERBATIM,
    VORBIS,
    TagFieldEngine,
    apply_transform,
    needs_slash_genre_split,
    rule_for,
    split_slash_genre,
)
from audio_suite_shared.tag_helper_base import EDITABLE_FIELDS

#: One exporter per container the suite can tag and this suite can encode.
#: ``.mp4`` shares the MP4 handler with ``.m4a``; the container is the same.
_EXPORTERS: dict[str, str] = {
    ".mp3": "mp3",
    ".flac": "flac",
    ".m4a": "ipod",
    ".wav": "wav",
    ".ogg": "ogg",
}

#: The containers the real-file tests run on, in table order.
REAL_CONTAINERS = [".mp3", ".flac", ".m4a", ".wav", ".ogg"]


def _digest(path: Path) -> str:
    """Return the file's SHA-256, the byte-level "did anything move" check."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _export(tmp_path: Path, extension: str) -> Path:
    """Build a real, encodable audio file of *extension*.

    Args:
        tmp_path: Directory to write into.
        extension: Container extension, dotted.

    Returns:
        The new file's path.

    Raises:
        pytest.skip.Exception: When this host has no encoder for the container,
            with the reason rather than a bare skip.
    """
    path = tmp_path / f"sample{extension}"
    try:
        AudioSegment.silent(duration=200).export(
            str(path), format=_EXPORTERS[extension]
        )
    except Exception as exc:  # pragma: no cover - host without the encoder
        pytest.skip(
            f"this host cannot encode {extension} ({type(exc).__name__}); "
            "the table and refusal tests still cover the convention"
        )
    return path


def _seed_genre(path: Path, value: str) -> None:
    """Store *value* as the container's genre tag, the way an outside tool would.

    Args:
        path: The audio file.
        value: Genre text, e.g. ``"Rock/Pop"``.
    """
    extension = path.suffix.lower()
    audio = mutagen.File(str(path))
    if extension in (".mp3", ".wav"):
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TCON(encoding=3, text=value))
    elif extension in (".flac", ".ogg"):
        audio["genre"] = value
    else:
        audio.tags["\xa9gen"] = value
    audio.save()


def _raw_genre(path: Path) -> str | None:
    """Read the genre back with mutagen, per container, not through the engine.

    Args:
        path: The audio file.

    Returns:
        The stored genre text, or None when the container has none.
    """
    extension = path.suffix.lower()
    audio = mutagen.File(str(path))
    if extension in (".mp3", ".wav"):
        frame = audio.tags.get("TCON") if audio.tags is not None else None
        return str(frame.text[0]) if frame is not None and frame.text else None
    if extension in (".flac", ".ogg"):
        values = audio.get("genre")
        return str(values[0]) if values else None
    values = audio.tags.get("\xa9gen")
    return str(values[0]) if values else None


class TestFieldTable:
    """The table itself: coverage, key spellings and the transform."""

    def test_every_editable_field_has_a_rule(self) -> None:
        """A field the Tag Editor can write is a field the engine can place."""
        names = {rule.name for rule in FIELD_RULES}
        missing = sorted(set(EDITABLE_FIELDS) - names)
        assert not missing, f"no rule for editable field(s): {missing}"

    def test_the_table_is_non_empty_and_unique(self) -> None:
        """A scan of an empty table must fail instead of passing vacuously."""
        names = [rule.name for rule in FIELD_RULES]
        assert names, "FIELD_RULES is empty"
        assert len(names) == len(set(names)), f"duplicate rule names: {names}"

    @pytest.mark.parametrize("rule", [r for r in FIELD_RULES if r.kind == "key"])
    def test_every_key_rule_covers_every_convention(self, rule: object) -> None:
        """A key rule must place its field in all four conventions.

        A newly added convention would otherwise read back as "absent" for every
        field it does not list — an absence that looks like an empty tag.
        """
        conventions = [convention for convention, _ in rule.keys]  # type: ignore[attr-defined]
        assert sorted(conventions) == sorted(CONVENTIONS), (
            f"{rule.name} covers {conventions}, expected {list(CONVENTIONS)}"  # type: ignore[attr-defined]
        )

    @pytest.mark.parametrize(
        ("field", "convention", "key"),
        [
            ("album_artist_genre", ID3, "TXXX:ALBUMARTISTGENRE"),
            ("album_genre", ID3, "TXXX:ALBUMGENRE"),
            ("artist_genre", ID3, "TXXX:ARTISTGENRE"),
            ("content_group", ID3, "TIT1"),
            ("genre", ID3, "TCON"),
            ("album_artist_genre", VORBIS, "ALBUMARTISTGENRE"),
            ("album_genre", VORBIS, "ALBUMGENRE"),
            ("artist_genre", VORBIS, "ARTISTGENRE"),
            ("content_group", VORBIS, "CONTENTGROUP"),
            ("genre", VORBIS, "GENRE"),
            ("album_artist_genre", MP4, "----:TXXX:ALBUMARTISTGENRE"),
            ("album_genre", MP4, "----:TXXX:ALBUMGENRE"),
            ("artist_genre", MP4, "----:TXXX:ARTISTGENRE"),
            ("content_group", MP4, "©grp"),
            ("genre", MP4, "©gen"),
            ("album_artist_genre", APEV2, "ALBUMARTISTGENRE"),
            ("album_genre", APEV2, "ALBUMGENRE"),
            ("artist_genre", APEV2, "ARTISTGENRE"),
            ("content_group", APEV2, "ContentGroup"),
            ("genre", APEV2, "Genre"),
        ],
    )
    def test_the_container_keys_are_the_ones_the_tools_wrote(
        self, field: str, convention: str, key: str
    ) -> None:
        """The table's keys are frozen: a rename here changes what lands on disk.

        These are exactly the keys ``tag_field_updater``'s per-format rules
        wrote, character for character, including the ``TXXX`` mean on MP4.
        """
        assert rule_for(field).key_for(convention) == key

    def test_rule_for_rejects_an_unknown_field(self) -> None:
        """An unknown name fails here, not somewhere odd at write time."""
        with pytest.raises(AudioTagError, match="Unknown tag field"):
            rule_for("no_such_field")

    def test_key_for_rejects_a_convention_the_field_does_not_cover(self) -> None:
        """A field with no key for a convention says so."""
        rule = rule_for("album_genre")
        with pytest.raises(AudioTagError, match="has no .* key"):
            rule.key_for("id4")

    def test_apply_transform_rejects_an_unknown_token(self) -> None:
        """A typo in the table cannot silently store the raw text."""
        with pytest.raises(AudioTagError, match="Unknown field transform"):
            apply_transform("slash_genres", "Rock/Pop")

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("Rock/Pop", "Rock; Pop"),
            ("A/B/C", "A; B; C"),
            ("Rock / Pop", "Rock / Pop"),
            ("Rock/Pop / Jazz", "Rock; Pop / Jazz"),
            ("Rock", "Rock"),
            ("/", "; "),
        ],
    )
    def test_the_slash_rule(self, value: str, expected: str) -> None:
        """One rule, and ``" / "`` is a list separator rather than a slash."""
        assert split_slash_genre(value) == expected
        assert apply_transform(TRANSFORM_SLASH_GENRE, value) == expected

    def test_verbatim_transform_changes_nothing(self) -> None:
        """The editable fields keep their text exactly as given."""
        assert apply_transform(TRANSFORM_VERBATIM, "AC/DC") == "AC/DC"

    @pytest.mark.parametrize(
        ("value", "expected"), [("Rock/Pop", True), ("Rock", False), (None, False)]
    )
    def test_needs_slash_genre_split(self, value: str | None, expected: bool) -> None:
        """Absence is not a slash, which is what keeps a blank tag untouched."""
        assert needs_slash_genre_split(value) is expected


@pytest.mark.parametrize("extension", REAL_CONTAINERS)
class TestEngineOnRealFiles:
    """Reads and writes through the handler, read back with mutagen."""

    def test_read_fields_reports_the_stored_value(
        self, tmp_path: Path, extension: str
    ) -> None:
        """The engine reads what an outside tool stored."""
        path = _export(tmp_path, extension)
        _seed_genre(path, "Rock/Pop")

        engine = TagFieldEngine(path)

        assert engine.read_fields()["genre"] == "Rock/Pop"

    def test_write_fields_stores_the_transformed_value(
        self, tmp_path: Path, extension: str
    ) -> None:
        """A write lands in the container and reads back through mutagen."""
        path = _export(tmp_path, extension)
        _seed_genre(path, "Rock")
        engine = TagFieldEngine(path)

        outcome = engine.write_fields({"genre": "Rock/Pop"})

        assert outcome.updated is True
        assert outcome.changed == ("genre",)
        assert _raw_genre(path) == "Rock; Pop"

    def test_dry_run_leaves_the_file_untouched(
        self, tmp_path: Path, extension: str
    ) -> None:
        """The gate is at the write site: no bytes, no mtime, no value."""
        path = _export(tmp_path, extension)
        _seed_genre(path, "Rock/Pop")
        before_digest = _digest(path)
        before_mtime = path.stat().st_mtime_ns

        outcome = TagFieldEngine(path).write_fields({"genre": "Rock/Pop"}, dry_run=True)

        assert outcome.updated is True
        assert outcome.dry_run is True
        assert _digest(path) == before_digest
        assert path.stat().st_mtime_ns == before_mtime
        assert _raw_genre(path) == "Rock/Pop"

    def test_a_value_that_already_matches_is_skipped(
        self, tmp_path: Path, extension: str
    ) -> None:
        """Re-running an applied rule rewrites nothing and says so."""
        path = _export(tmp_path, extension)
        _seed_genre(path, "Rock; Pop")
        before_digest = _digest(path)

        outcome = TagFieldEngine(path).write_fields({"genre": "Rock/Pop"})

        assert outcome.updated is False
        assert outcome.skipped == ("genre",)
        assert _digest(path) == before_digest

    def test_raw_updates_names_the_container_keys(
        self, tmp_path: Path, extension: str
    ) -> None:
        """The report deals in container keys, which is what a user sees."""
        path = _export(tmp_path, extension)
        _seed_genre(path, "Rock")

        updates = TagFieldEngine(path).raw_updates(
            {"genre": "Rock/Pop", "album_genre": "Jazz/Blues"}
        )

        assert rule_for("genre").key_for(TagFieldEngine(path).convention) in updates
        assert updates[rule_for("genre").key_for(TagFieldEngine(path).convention)] == (
            "Rock; Pop"
        )
        assert len(updates) == 2

    def test_delete_fields_removes_the_key(
        self, tmp_path: Path, extension: str
    ) -> None:
        """Removal goes through the same handler, so the container stays valid."""
        path = _export(tmp_path, extension)
        _seed_genre(path, "Rock")

        removed = TagFieldEngine(path).delete_fields(["genre"])

        assert removed == ("genre",)
        assert _raw_genre(path) is None


#: The extensions the format matrix marks as having no tag writer.  Derived,
#: never listed: a hardcoded list drifts the moment the matrix gains or loses a
#: row, and the sweep would then test a container the suite actually writes.
UNWRITABLE_CONTAINERS = sorted(
    extension
    for extension, capability in FORMAT_MATRIX.items()
    if not capability.tag_writable
)


class TestRefusals:
    """A container the suite cannot tag is refused, never guessed at."""

    def test_the_refusal_list_is_not_empty(self) -> None:
        """A sweep over an empty list would pass without testing anything."""
        assert UNWRITABLE_CONTAINERS, (
            "the format matrix marks every container tag-writable, so the "
            "refusal sweep below proves nothing"
        )

    @pytest.mark.parametrize("extension", UNWRITABLE_CONTAINERS)
    def test_a_container_without_a_writer_is_refused(
        self, tmp_path: Path, extension: str
    ) -> None:
        """The refusal carries the standard token and no file is touched.

        The bytes are deliberately not audio: a refusal that only fires after a
        successful decode is not a refusal, it is a parse error that happens to
        mention the format.
        """
        path = tmp_path / f"refused{extension}"
        path.write_bytes(b"not really audio")

        with pytest.raises(AudioFormatError, match="Unsupported format"):
            TagFieldEngine(path)

    def test_the_message_names_the_container(self, tmp_path: Path) -> None:
        """A refusal that does not say which container it refused is a mystery."""
        with pytest.raises(AudioFormatError, match=r"\.wma"):
            TagFieldEngine(tmp_path / "x.wma")


class TestHasTags:
    """``has_tags`` is what distinguishes a skip from an unchanged file."""

    def test_a_tagless_mp3_reports_no_container(self, tmp_path: Path) -> None:
        """A stripped MP3 has no ID3 block, so the tool counts it as a skip."""
        path = _export(tmp_path, ".mp3")
        mutagen.File(str(path)).delete()

        engine = TagFieldEngine(path)

        assert engine.convention == ID3
        assert engine.has_tags() is False

    def test_a_tagged_mp3_reports_a_container(self, tmp_path: Path) -> None:
        """The contrast half: without it the check could pass on any file."""
        path = _export(tmp_path, ".mp3")
        _seed_genre(path, "Rock")

        assert TagFieldEngine(path).has_tags() is True


class TestUndo:
    """The snapshot is recorded once, at the write site, and never for a dry run."""

    def test_a_dry_run_records_no_snapshot(self, tmp_path: Path) -> None:
        """An undo entry for a change that never happened can only lie."""
        path = _export(tmp_path, ".mp3")
        _seed_genre(path, "Rock/Pop")
        undo_db = tmp_path / "undo.db"
        engine = TagFieldEngine(path, snapshot_operation="tag_field_update")

        with active_batch("tag_field_updater", "tag_edit", db_path=undo_db):
            engine.write_fields({"genre": "Rock/Pop"}, dry_run=True)

        assert list_recent_batches(limit=10, db_path=undo_db) == []

    def test_a_live_write_records_one_snapshot(self, tmp_path: Path) -> None:
        """One file write is one undo record, whatever it changed."""
        path = _export(tmp_path, ".mp3")
        _seed_genre(path, "Rock/Pop")
        undo_db = tmp_path / "undo.db"
        engine = TagFieldEngine(path, snapshot_operation="tag_field_update")

        with active_batch("tag_field_updater", "tag_edit", db_path=undo_db):
            engine.write_fields(
                {"genre": "Rock/Pop", "album_genre": "Jazz/Blues"}, dry_run=False
            )

        batches = list_recent_batches(limit=10, db_path=undo_db)
        assert len(batches) == 1
        assert batches[0].tool_name == "tag_field_updater"
        assert batches[0].record_count == 1
