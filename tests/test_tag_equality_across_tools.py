"""
test_tag_equality_across_tools.py — two tools, one tag layer, same bytes' worth.

The Tag Editor and the Tag Field Updater write the same fields through
different doors: the editor calls ``write_editable_tag`` per field, the updater
parses a filename and calls the same layer through ``apply_filename_fields``.
Before the one tag layer they also carried their own idea of what a genre slash
means, and only a cross-tool test can see a divergence like that — each tool's
own suite happily agrees with itself.

So each case writes the *same* edit into two copies of one source file, through
the two tools' own entry points, and then compares what mutagen reads back: the
canonical fields, and the raw containers atom by atom.  Decoded values are
compared, not file bytes: two writers legitimately differ in atom ordering and
padding, and a byte comparison would fail for the wrong reason.

The refusal half is the same argument one level down: a container with no tag
writer (``.wma``) must be refused by both tools with the same message, or one of
them is quietly writing somewhere it should not.

Changed in 2.4.2: new — plan WP-6 (C-M2), the cross-tool equality lock.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import mutagen
import pytest
from pydub import AudioSegment

from audio_suite_shared.tag_helper_reader import read_editable_tags
from tag_editor.core.processor import FieldEdit, TagEditorProcessor
from tag_field_updater.core.processor import TagProcessor

#: The editable fields, with values a filename pattern can carry (no separators).
EDITS: dict[str, str] = {
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "Album Artist",
    "track": "3",
    "disc": "2",
    "year": "2020",
    "genre": "Rock; Pop",
    "comment": "A note",
}

#: Order the pattern and the filename name the fields in.
_ORDER: tuple[str, ...] = (
    "title",
    "artist",
    "album",
    "album_artist",
    "track",
    "disc",
    "year",
    "genre",
    "comment",
)

#: ``~~`` is the separator because a tag value may contain " - " but not this.
_SEPARATOR = "~~"

#: Fields a container's tag layer does not carry.  ``.m4a`` has no ``disc``
#: mapping in the shared editable layer (its MP4 helper refuses the field), which
#: is pre-existing behaviour this change does not touch; the other eight fields
#: still prove the equal-write contract for that container.
_UNSUPPORTED: dict[str, tuple[str, ...]] = {".m4a": ("disc",)}

_EXPORTERS: dict[str, str] = {
    ".mp3": "mp3",
    ".flac": "flac",
    ".m4a": "ipod",
    ".wav": "wav",
}

CONTAINERS = [".mp3", ".flac", ".m4a", ".wav"]


def _fields(extension: str) -> dict[str, str]:
    """The edits this container's tag layer can carry, in pattern order."""
    skipped = _UNSUPPORTED.get(extension, ())
    return {name: EDITS[name] for name in _ORDER if name not in skipped}


def _pattern(extension: str) -> str:
    """The filename pattern for this container's fields."""
    return _SEPARATOR.join(f"%{name}%" for name in _fields(extension))


def _filename(extension: str) -> str:
    """The filename that carries this container's field values."""
    return _SEPARATOR.join(_fields(extension).values())


def _source(tmp_path: Path, extension: str) -> Path:
    """Build the untagged source file both tools will edit.

    Args:
        tmp_path: Directory to write into.
        extension: Container extension, dotted.

    Returns:
        The source path.

    Raises:
        pytest.skip.Exception: When this host has no encoder for the container.
    """
    path = tmp_path / f"source{extension}"
    try:
        AudioSegment.silent(duration=200).export(
            str(path), format=_EXPORTERS[extension]
        )
    except Exception as exc:  # pragma: no cover - host without the encoder
        pytest.skip(
            f"this host cannot encode {extension} ({type(exc).__name__}); "
            "the other containers still cover the equal-write contract"
        )
    return path


def _raw_view(path: Path) -> dict[str, str]:
    """Render the container's tags as comparable text, whatever the convention.

    Args:
        path: The audio file.

    Returns:
        One comparable mapping per container.
    """
    audio = mutagen.File(str(path))
    assert audio is not None
    extension = path.suffix.lower()
    view: dict[str, str] = {}
    if audio.tags is None:
        return view
    if extension in (".mp3", ".wav"):
        for frame in audio.tags.values():
            key = getattr(frame, "FrameID", type(frame).__name__)
            desc = getattr(frame, "desc", "")
            view[f"{key}:{desc}" if desc else key] = str(frame)
        return view
    for key, values in audio.tags.items():
        renamed = str(key)
        if renamed.startswith("----:com.apple.iTunes:"):
            # MP4 freeforms keep their payload as bytes; render them as text so
            # both writers are compared on what a reader would see.
            renamed = renamed[len("----:com.apple.iTunes:") :]
        view[renamed] = "|".join(
            value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
            for value in values
        )
    return view


@pytest.mark.parametrize("extension", CONTAINERS)
class TestBothToolsWriteTheSameTags:
    """The same edit through each tool, compared after reload."""

    def test_editable_fields_are_equal(self, tmp_path: Path, extension: str) -> None:
        """Every supported field in, identical fields out, per container."""
        source = _source(tmp_path, extension)
        editor_copy = tmp_path / f"editor{extension}"
        updater_copy = tmp_path / f"{_filename(extension)}{extension}"
        shutil.copyfile(source, editor_copy)
        shutil.copyfile(source, updater_copy)

        edits = _fields(extension)
        results = TagEditorProcessor().apply_edits(
            [FieldEdit(editor_copy, name, value) for name, value in edits.items()]
        )
        assert [result.error for result in results] == [None] * len(edits), (
            f"the editor failed on {extension}: "
            f"{[result.error for result in results if result.error]}"
        )

        updater = TagProcessor(patterns=(_pattern(extension),))
        outcome = updater.process_file(updater_copy)
        assert outcome.error is None, (
            f"the updater failed on {extension}: {outcome.error}"
        )
        assert outcome.updated is True, f"the updater wrote nothing on {extension}"

        editor_tags = read_editable_tags(str(editor_copy))
        updater_tags = read_editable_tags(str(updater_copy))
        assert editor_tags == updater_tags, (
            "the two tools read back different tags for the same edit"
        )
        assert {name: editor_tags.get(name) for name in edits} == edits

    def test_the_raw_containers_are_equal(self, tmp_path: Path, extension: str) -> None:
        """Not just the canonical view: the atoms themselves agree.

        A divergent frame id (``TYER`` against ``TDRC``) would pass a canonical
        comparison and still leave two libraries that no other tool reads the
        same way.
        """
        source = _source(tmp_path, extension)
        editor_copy = tmp_path / f"editor{extension}"
        updater_copy = tmp_path / f"{_filename(extension)}{extension}"
        shutil.copyfile(source, editor_copy)
        shutil.copyfile(source, updater_copy)
        edits = _fields(extension)
        TagEditorProcessor().apply_edits(
            [FieldEdit(editor_copy, name, value) for name, value in edits.items()]
        )
        TagProcessor(patterns=(_pattern(extension),)).process_file(updater_copy)

        editor_view = _raw_view(editor_copy)
        updater_view = _raw_view(updater_copy)

        assert editor_view, f"the editor wrote no tags on {extension}"
        assert editor_view == updater_view


class TestTheRefusalIsTheSame:
    """A container neither tool can tag is refused identically."""

    def test_wma_is_refused_by_both_tools(self, tmp_path: Path) -> None:
        """``.wma`` has no tag handler, so both tools must say the same thing.

        The matrix marks the container ``tag_writable = False`` (WP-1); the
        refusal is the user-visible consequence and it must not differ between
        the two tools — one of them writing where the other refuses would be the
        drift this change exists to remove.
        """
        source = tmp_path / "refused.wma"
        try:
            AudioSegment.silent(duration=200).export(str(source), format="asf")
        except Exception as exc:  # pragma: no cover - host without the encoder
            pytest.skip(f"this host cannot encode .wma ({type(exc).__name__})")

        updater_copy = tmp_path / f"{_filename('.wma')}.wma"
        editor_copy = tmp_path / "editor.wma"
        shutil.copyfile(source, updater_copy)
        shutil.copyfile(source, editor_copy)

        editor_results = TagEditorProcessor().apply_edits(
            [FieldEdit(editor_copy, "title", "Title")]
        )
        updater_result = TagProcessor(patterns=(_pattern(".wma"),)).process_file(
            updater_copy
        )

        assert editor_results[0].error, "the editor reported no error for .wma"
        assert updater_result.error, "the updater reported no error for .wma"
        assert updater_result.error == editor_results[0].error
