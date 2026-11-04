"""
test_transformation_rules.py — one rule, every container, gated at the write site.

Audit H1 (plan A1) found that all eight ``process_*_file`` rules called
``record_tag_edit_snapshot(...)`` and ``audio.save()`` unconditionally: the
``dry_run`` argument the CLI accepted never reached them.  The eight rules are
now one :func:`process_file` over ``audio_suite_shared.tag_field_engine``, so
the gate has one place to be right and one place to be tested — the engine's
``write_fields`` — but *this* module still has to hand the flag over.  A rule
that dropped ``dry_run`` would still look fine in the engine's own suite, so
the sweep below drives the rule itself and asserts the outcome on disk.

Two halves, and the pairing is the point:

* against **real encoded files** for every container this host can produce,
  asserting SHA-256, mtime and the tag read back through mutagen;
* against a **recording stand-in** for the engine, for the one thing a real file
  cannot show — that the rule passes the caller's ``dry_run`` value into
  ``write_fields`` verbatim.

Changed in 2.4.2: the per-rule table, its marker-writing stand-ins and the
``process_*_file`` sweep are replaced by the one rule's real-file sweep plus an
engine stand-in; the ``TAG_MAPPINGS`` import is gone with the table it read
(plan WP-6, C-M2).
"""

from __future__ import annotations

import hashlib
import inspect
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from mutagen.aiff import AIFF
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TCON
from mutagen.mp3 import MP3
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from pydub import AudioSegment

from audio_suite_shared.tag_field_engine import FIELD_RULES
from audio_suite_shared.tag_field_engine import ID3 as ID3_CONVENTION
from tag_field_updater.core import transformation_rules as rules
from tag_field_updater.core.mapping_engine import SLASH_FIELDS, SUPPORTED_EXTENSIONS
from tag_field_updater.core.transformation_rules import _SkipFile, process_file

# ---------------------------------------------------------------------------
# Fixture data
# ---------------------------------------------------------------------------

ORIGINAL_VALUE = "Rock/Pop"
REWRITTEN_VALUE = "Rock; Pop"

#: The ID3-backed containers, keyed by extension: each opens its own class.
_ID3_OPENERS: dict[str, Any] = {".mp3": MP3, ".wav": WAVE, ".aiff": AIFF}

#: Vorbis-comment containers.
_VORBIS_OPENERS: dict[str, Any] = {".flac": FLAC, ".ogg": OggVorbis, ".opus": OggOpus}


def digest(path: Path) -> str:
    """SHA-256 of the file's bytes."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _encode(path: Path, exporter: str) -> bool:
    """Encode a short silent file, reporting whether this host can."""
    try:
        AudioSegment.silent(duration=200).export(str(path), format=exporter)
    except Exception:  # pragma: no cover - host without the encoder
        return False
    return True


def _write_genre(path: Path, extension: str) -> None:
    """Store :data:`ORIGINAL_VALUE` as the genre, in the container's own shape."""
    if extension in _ID3_OPENERS:
        audio = _ID3_OPENERS[extension](str(path))
        if audio.tags is None:
            audio.add_tags()
        audio.tags.add(TCON(encoding=3, text=ORIGINAL_VALUE))
        audio.save()
        return
    audio = _VORBIS_OPENERS[extension](str(path))
    audio["genre"] = [ORIGINAL_VALUE]
    audio.save()


def _read_genre(path: Path, extension: str) -> str | None:
    """Read the genre back through mutagen, whatever the convention."""
    if extension in _ID3_OPENERS:
        audio = _ID3_OPENERS[extension](str(path))
        frames = audio.tags.getall("TCON") if audio.tags else []
        return str(frames[0]) if frames else None
    audio = _VORBIS_OPENERS[extension](str(path))
    values = audio.get("genre") or []
    return str(values[0]) if values else None


def _strip_id3(path: Path) -> None:
    """Remove the tag container pydub's MP3 encoder leaves behind."""
    ID3(str(path)).delete()


#: ``(extension, pydub exporter)`` for every container this suite can build.
REAL_CONTAINERS: list[tuple[str, str]] = [
    (".mp3", "mp3"),
    (".flac", "flac"),
    (".ogg", "ogg"),
    (".opus", "opus"),
    (".wav", "wav"),
    (".aiff", "aiff"),
]


@pytest.fixture(params=REAL_CONTAINERS, ids=lambda item: item[0])
def tagged_file(request: pytest.FixtureRequest, tmp_path: Path) -> Path:
    """A real file in the requested container whose genre carries a bare slash."""
    extension, exporter = request.param
    path = tmp_path / f"source{extension}"
    if not _encode(path, exporter):
        pytest.skip(f"this host cannot encode {extension}")
    _write_genre(path, extension)
    return path


# ---------------------------------------------------------------------------
# The gate, measured on disk
# ---------------------------------------------------------------------------


class TestTheDryRunGateHoldsOnRealFiles:
    """A dry run computes the rewrite and leaves the file byte-identical."""

    def test_dry_run_changes_nothing(self, tagged_file: Path) -> None:
        """Bytes, mtime and the read-back tag all survive a dry run."""
        extension = tagged_file.suffix
        before_digest = digest(tagged_file)
        before_mtime = tagged_file.stat().st_mtime_ns

        result = process_file(tagged_file, dry_run=True)

        assert result.error is None, f"the rule failed on {extension}: {result.error}"
        assert result.updated is True, (
            f"the rule found nothing to rewrite in {extension}"
        )
        assert result.tags_updated, f"the rule named no rewritten key for {extension}"
        assert _read_genre(tagged_file, extension) == ORIGINAL_VALUE
        assert digest(tagged_file) == before_digest, (
            f"a dry run rewrote {extension} — the flag did not reach the write site"
        )
        assert tagged_file.stat().st_mtime_ns == before_mtime

    def test_live_run_rewrites_the_same_fixture(self, tagged_file: Path) -> None:
        """The contrast half: without it the dry-run half proves nothing."""
        extension = tagged_file.suffix
        before_digest = digest(tagged_file)

        result = process_file(tagged_file)

        assert result.error is None, f"the rule failed on {extension}: {result.error}"
        assert result.updated is True
        assert _read_genre(tagged_file, extension) == REWRITTEN_VALUE
        assert digest(tagged_file) != before_digest, (
            f"a live run did not rewrite {extension}, so its dry run proved nothing"
        )

    def test_a_second_live_run_is_an_unchanged_file(self, tagged_file: Path) -> None:
        """Once the slash is gone the rule reports an unchanged file, not an edit."""
        process_file(tagged_file)

        result = process_file(tagged_file)

        assert result.error is None
        assert result.updated is False
        assert result.tags_updated == ()
        assert _read_genre(tagged_file, tagged_file.suffix) == REWRITTEN_VALUE


# ---------------------------------------------------------------------------
# Skip and refusal semantics
# ---------------------------------------------------------------------------


class TestSkipAndRefusal:
    """The three outcomes a scan counts must not move with the refactor."""

    def test_mp3_without_a_tag_container_is_a_skip(self, tmp_path: Path) -> None:
        """An untagged MP3 is a skip, not an error (the old ``_SkipFile`` path)."""
        path = tmp_path / "untagged.mp3"
        if not _encode(path, "mp3"):
            pytest.skip("this host cannot encode .mp3")
        _strip_id3(path)

        with pytest.raises(_SkipFile) as caught:
            process_file(path, dry_run=True)

        assert caught.value.reason == "no ID3 tags found"

    def test_a_file_with_no_slash_is_unchanged(self, tmp_path: Path) -> None:
        """A tagged file with no bare slash is untouched and reported unchanged."""
        path = tmp_path / "clean.mp3"
        if not _encode(path, "mp3"):
            pytest.skip("this host cannot encode .mp3")
        _write_genre(path, ".mp3")
        audio = MP3(str(path))
        audio.tags.add(TCON(encoding=3, text="Rock; Pop"))
        audio.save()
        before = digest(path)

        result = process_file(path)

        assert result.error is None
        assert result.updated is False
        assert digest(path) == before

    def test_a_corrupt_container_is_an_error_not_a_skip(self, tmp_path: Path) -> None:
        """Undecodable bytes in a writable container are reported, never ignored.

        The engine raises whatever the decoder raised; mapping it to a user
        message is this module's job, and a scan that silently skipped the file
        would leave a corrupt track in the library with no line in the report.
        """
        path = tmp_path / "corrupt.dsf"
        path.write_bytes(b"not really audio")
        before = digest(path)

        result = process_file(path)

        assert result.error, "a corrupt file was reported as clean"
        assert digest(path) == before

    def test_wma_is_refused_and_left_alone(self, tmp_path: Path) -> None:
        """``.wma`` has no tag writer, so the rule reports an error and writes nothing.

        The container stays in ``SUPPORTED_EXTENSIONS`` on purpose: reaching the
        rule and being refused is visible in the report, while dropping it would
        make every WMA file vanish as a silent skip (WP-1's matrix marks the
        container ``tag_writable = False``).
        """
        path = tmp_path / "refused.wma"
        if not _encode(path, "asf"):
            pytest.skip("this host cannot encode .wma")
        assert path.suffix in SUPPORTED_EXTENSIONS
        before = digest(path)

        result = process_file(path)

        assert result.error, "the rule reported no error for a container it cannot tag"
        assert digest(path) == before


# ---------------------------------------------------------------------------
# The flag reaches the write site
# ---------------------------------------------------------------------------


class _RecordingEngine:
    """An engine stand-in that records how the rule called it."""

    def __init__(self, path: Path, calls: list[tuple[dict[str, str], bool]]) -> None:
        self.path = path
        self.calls = calls
        self.convention = ID3_CONVENTION

    def has_tags(self) -> bool:
        """Claim a tag container so the rule takes its normal path."""
        return True

    def read_fields(self) -> dict[str, str]:
        """Return the one field the slash rule reads."""
        return {"genre": ORIGINAL_VALUE}

    def write_fields(
        self, pending: dict[str, str], dry_run: bool = False
    ) -> SimpleNamespace:
        """Record the call and report the write the engine would have made."""
        self.calls.append((dict(pending), dry_run))
        return SimpleNamespace(updated=True, keys=["genre"], changed=["genre"])


class TestTheRuleHandsTheFlagOver:
    """``dry_run`` must arrive at ``write_fields`` exactly as the caller sent it."""

    @pytest.mark.parametrize("dry_run", [True, False])
    def test_write_fields_receives_the_callers_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, dry_run: bool
    ) -> None:
        """Both halves, because a stand-in that always sees ``True`` cannot fail."""
        calls: list[tuple[dict[str, str], bool]] = []

        def factory(path: Path) -> _RecordingEngine:
            return _RecordingEngine(path, calls)

        monkeypatch.setattr(rules, "TagFieldEngine", factory)

        result = process_file(tmp_path / "any.flac", dry_run=dry_run)

        assert result.error is None
        assert result.updated is True
        assert len(calls) == 1, "the rule wrote more than once per file"
        pending, received = calls[0]
        assert received is dry_run, (
            "the rule dropped or rewrote dry_run on the way to the write site"
        )
        assert pending == {"genre": ORIGINAL_VALUE}, (
            "the rule handed the engine a transformed value, not the stored one"
        )

    def test_default_is_a_live_run(self) -> None:
        """A caller that says nothing gets the write, as every rule did before."""
        parameter = inspect.signature(process_file).parameters["dry_run"]
        assert parameter.default is False


# ---------------------------------------------------------------------------
# Non-vacuity: there is one rule and it owns every field the tool names
# ---------------------------------------------------------------------------


class TestTheModuleHasOneRule:
    """The eight ``process_*_file`` names are gone, and nothing re-adds them."""

    def test_no_per_format_rule_survives(self) -> None:
        """A reintroduced per-format rule would be the second copy all over again."""
        leftovers = sorted(
            name
            for name in dir(rules)
            if name.startswith("process_") and name != "process_file"
        )
        assert leftovers == [], f"per-format rules reintroduced: {leftovers}"

    def test_the_module_imports_no_mutagen(self) -> None:
        """Container knowledge lives in the engine; this module must stay free of it."""
        source = Path(rules.__file__).read_text(encoding="utf-8")
        imported = [
            line
            for line in source.splitlines()
            if line.startswith(("import mutagen", "from mutagen"))
        ]
        assert imported == [], f"mutagen re-entered the rule module: {imported}"

    def test_every_slash_field_is_an_engine_rule(self) -> None:
        """Each field the tool rewrites resolves to a rule in the one table."""
        names = {rule.name for rule in FIELD_RULES}
        assert SLASH_FIELDS, "the tool declares no fields"
        missing = sorted(set(SLASH_FIELDS) - names)
        assert missing == [], f"fields with no engine rule: {missing}"
