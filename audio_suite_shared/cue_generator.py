"""
cue_generator.py — Generate CUE sheet text from track metadata and timestamps.

Builds a spec-compliant CUE sheet whose INDEX 01 values are derived from the
provided ``start_ms`` offsets, so a generated sheet always matches the audio
it describes.  Produces text that the parser in ``cue_parser`` round-trips
identically for the supported commands.

Changed in 2.6.0: adds the folder export — ``scan_audio_files``,
``folder_specs`` and ``build_folder_cue`` — so ``audiosuite cue generate`` and
the CUE Sheet Generator window share one implementation of the folder scan, the
track-number precedence (tag, then ``NN - Title`` name, then position) and the
per-format ``FILE`` token.  A duplicate track number raises rather than
rendering a sheet no player can read.
"""

from __future__ import annotations

import logging
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .audio_formats import is_supported_format
from .tag_helper_reader import read_editable_tags

logger = logging.getLogger(f"audio_suite.{__name__}")

FRAMES_PER_SECOND = 75
FRAMES_PER_MINUTE = FRAMES_PER_SECOND * 60
# Largest representable MM:SS:FF with the 2-digit frame/second/minute fields.
_MAX_FRAMES = 599 * FRAMES_PER_MINUTE + 59 * FRAMES_PER_SECOND + 74


_FILE_TYPE_BY_EXTENSION = {
    ".aac": "MP4",
    ".aif": "AIFF",
    ".aiff": "AIFF",
    ".ape": "APE",
    ".flac": "FLAC",
    ".m4a": "MP4",
    ".mp3": "MP3",
    ".mp4": "MP4",
    ".ogg": "OGG",
    ".oga": "OGG",
    ".opus": "OGG",
    ".wav": "WAVE",
    ".wma": "WMA",
}


def derive_file_type(filename: str) -> str:
    """Return the CUE ``FILE`` type token for *filename*'s extension.

    Unknown extensions fall back to ``WAVE`` so the sheet always carries a
    plausible, spec-permitted type token.
    """
    return _FILE_TYPE_BY_EXTENSION.get(Path(filename).suffix.lower(), "WAVE")


@dataclass(frozen=True)
class TrackSpec:
    """Metadata for a single track in a generated sheet."""

    number: int
    title: str
    performer: str = ""
    start_ms: int = 0
    isrc: str = ""

    def __post_init__(self) -> None:
        if not 1 <= self.number <= 99:
            raise ValueError(f"Track number must be 01-99, got {self.number}")
        if self.start_ms < 0:
            raise ValueError(f"start_ms must be >= 0, got {self.start_ms}")


@dataclass(frozen=True)
class CueFileSpec:
    """One FILE block in a generated sheet."""

    filename: str
    tracks: tuple[TrackSpec, ...] = ()
    file_type: str | None = None

    def __post_init__(self) -> None:
        if not self.filename:
            raise ValueError("CUE filename must not be empty")
        if self.file_type is None:
            object.__setattr__(self, "file_type", derive_file_type(self.filename))
        if not self.file_type:
            raise ValueError("CUE file type must not be empty")


def _quote(value: str) -> str:
    return value.replace('"', '""')


def ms_to_frames(ms: int) -> int:
    """Convert a millisecond offset into CD frames (75 frames/second)."""
    return int(round(ms * FRAMES_PER_SECOND / 1000))


def format_msf(frames: int) -> str:
    """Format a frame count as ``MM:SS:FF``.

    Out-of-range counts are clamped to the maximum representable timestamp
    (``599:59:74``) so a very long album never produces an invalid token.
    """
    if frames < 0:
        frames = 0
    total = min(frames, _MAX_FRAMES)
    mm, rem = divmod(total, FRAMES_PER_MINUTE)
    ss, ff = divmod(rem, FRAMES_PER_SECOND)
    return f"{mm:02d}:{ss:02d}:{ff:02d}"


def build_cue(
    *,
    title: str = "",
    performer: str = "",
    rem: Sequence[str] = (),
    catalog: str = "",
    files: Sequence[CueFileSpec],
) -> str:
    """Compile CUE sheet text describing *files*.

    Args:
        title:     Album title (emitted as sheet-level ``TITLE``).
        performer: Album artist (emitted as sheet-level ``PERFORMER``).
        rem:       Sheet-level comment lines (each emitted as one ``REM``).
        catalog:   UPC/EAN catalogue number (emitted as ``CATALOG``).
        files:     FILE blocks; each track's ``start_ms`` becomes its
                   ``INDEX 01`` timestamp, so the sheet matches the audio.

    Returns:
        The CUE sheet text (always ends with a single trailing newline).
    """
    lines: list[str] = []
    for comment in rem:
        lines.append(f"REM {comment}")
    if catalog:
        lines.append(f"CATALOG {catalog}")
    if performer:
        lines.append(f'PERFORMER "{_quote(performer)}"')
    if title:
        lines.append(f'TITLE "{_quote(title)}"')
    for file in files:
        lines.append(f'FILE "{_quote(file.filename)}" {file.file_type}')
        for track in file.tracks:
            lines.append(f"  TRACK {track.number:02d} AUDIO")
            if track.title:
                lines.append(f'    TITLE "{_quote(track.title)}"')
            if track.performer:
                lines.append(f'    PERFORMER "{_quote(track.performer)}"')
            if track.isrc:
                lines.append(f"    ISRC {track.isrc}")
            lines.append(f"    INDEX 01 {format_msf(ms_to_frames(track.start_ms))}")
    return "\n".join(lines).rstrip("\n") + "\n"


def write_cue(path: str | Path, cue_text: str) -> None:
    """Write *cue_text* to *path* as UTF-8 text with ``\\n`` line endings.

    Args:
        path:     Destination ``.cue`` file.
        cue_text: Sheet text as produced by :func:`build_cue`.

    Raises:
        OSError: If the file cannot be written.
    """
    payload = cue_text if cue_text.endswith("\n") else cue_text + "\n"
    Path(path).write_text(payload, encoding="utf-8", newline="")


def _natural_sort_key(name: str) -> list[str | int]:
    """Return a filename's case-insensitive natural-order key.

    ``...9.flac`` sorts before ``...10.flac``, which a plain string sort gets
    wrong — and the folder's file order is the fallback track order.

    Args:
        name: The file's name.

    Returns:
        Alternating text and integer chunks, usable as a sort key.
    """
    parts: list[str | int] = []
    for chunk in re.split(r"(\d+)", name.lower()):
        parts.append(int(chunk) if chunk.isdigit() else chunk)
    return parts


def scan_audio_files(target_path: Path, *, recursive: bool = False) -> list[Path]:
    """List the supported audio files at *target_path* in natural sort order.

    A single file is returned on its own when its extension is supported; a
    folder is read one level deep (sub-folders belong to other albums) and an
    unsupported extension is dropped rather than passed to the tag reader.

    Args:
        target_path: A folder of tracks or one audio file.
        recursive: Walk sub-folders too.  A sheet never wants that — a sub-folder
            is a different album — but a whole-library utility such as the
            artwork extractor does, and it reuses this scan rather than
            declaring a second audio-extension table of its own.

    Returns:
        The files the sheet will describe, in the order it will number them.
    """
    if not target_path.is_dir():
        if is_supported_format(target_path.name):
            return [target_path]
        return []
    if recursive:
        found: list[Path] = []
        for directory, dirnames, filenames in os.walk(target_path):
            dirnames.sort()
            found.extend(
                Path(directory) / name
                for name in filenames
                if is_supported_format(name)
            )
        # Album folders in name order, tracks naturally ordered inside each, so
        # a walk is reproducible instead of inheriting the filesystem's order.
        return sorted(
            found,
            key=lambda path: (str(path.parent).lower(), _natural_sort_key(path.name)),
        )
    return sorted(
        (
            path
            for path in target_path.iterdir()
            if path.is_file() and is_supported_format(path.name)
        ),
        key=lambda path: _natural_sort_key(path.name),
    )


#: A leading ``"NN - "`` / ``"NN._"`` track-number prefix on a ripped filename.
_TRACK_PREFIX_RE = re.compile(r"^(\d{1,2})\s*[._\-]\s*(.+)$")


def _tag_track_number(path: Path) -> int | None:
    """Return the file's own track number, or ``None`` when it has none.

    Read through the shared tag facade rather than a private mutagen call, so
    every container's track field is resolved the same way the Tag Editor
    reads it.  A ``3/12`` value yields ``3``: the sheet numbers tracks 1-99.

    Args:
        path: The audio file.

    Returns:
        The number 1-99 the tags carry, or ``None`` when absent, unreadable or
        outside that range.
    """
    value = read_editable_tags(str(path)).get("track")
    if not value:
        return None
    digits = re.match(r"\s*(\d+)", str(value))
    if digits is None:
        return None
    number = int(digits.group(1))
    return number if 1 <= number <= 99 else None


def _file_track_info(path: Path, fallback_number: int) -> tuple[int, str, str]:
    """Return ``(number, title, performer)`` for one file in a folder sheet.

    The tag's track number wins, then a ``"NN - Title.ext"`` filename prefix,
    then the file's position.  The title prefers the tag, then the filename
    without its prefix.  The performer is empty when the file stores neither
    an artist nor a title, which is the untagged-file case.

    Args:
        path: The audio file.
        fallback_number: The file's 1-based position, used when nothing else
            names a number.

    Returns:
        The track number, its title and its performer.
    """
    number = _tag_track_number(path)
    stem_tail = path.stem
    match = _TRACK_PREFIX_RE.match(path.stem)
    if match:
        if number is None:
            number = int(match.group(1))
        stem_tail = match.group(2).strip()

    artist, title = _read_artist_title(path)
    resolved_number = number if number is not None else fallback_number
    if artist in ("", "Unknown") and title in ("", "Unknown"):
        # No tags at all: the filename carries the title, and an empty
        # performer is honest rather than a fabricated "Unknown".
        return resolved_number, stem_tail or path.stem, ""
    return resolved_number, title or path.stem, artist


def _read_artist_title(path: Path) -> tuple[str, str]:
    """Read ``(artist, title)`` through the shared tag facade.

    Split out so the module exposes one seam a test can patch, and so the
    folder sheet never grows a second reader of its own.

    Args:
        path: The audio file.

    Returns:
        The file's artist and title, ``("Unknown", "Unknown")`` when unread.
    """
    from .tag_helper_reader import read_artist_title

    return read_artist_title(str(path))


def folder_specs(files: Sequence[Path]) -> list[CueFileSpec]:
    """Build one ``FILE`` block per track file, in album order.

    A sheet over a folder of separate files names each file in its own block,
    and every ``INDEX 01`` is therefore ``00:00:00`` — the offset is relative
    to its own ``FILE``, so no duration has to be measured (or guessed) to
    describe the folder.

    Args:
        files: The track files, in album order.

    Returns:
        The sheet's ``FILE`` blocks.

    Raises:
        ValueError: Two files claim the same track number.  Renumbering them
            silently would produce a sheet whose tracks no longer match the
            album, so the sheet is refused instead.
    """
    specs: list[CueFileSpec] = []
    seen: dict[int, Path] = {}
    for index, audio in enumerate(files, start=1):
        number, track_title, performer = _file_track_info(audio, index)
        previous = seen.get(number)
        if previous is not None:
            raise ValueError(
                f"Track number {number:02d} is claimed by both "
                f"'{previous.name}' and '{audio.name}'; fix the tags or rename "
                "the files so every track has its own number."
            )
        seen[number] = audio
        specs.append(
            CueFileSpec(
                filename=audio.name,
                tracks=(
                    TrackSpec(number=number, title=track_title, performer=performer),
                ),
            )
        )
    return specs


def build_folder_cue(
    files: Sequence[Path], *, title: str = "", performer: str = ""
) -> str:
    """Render the CUE text describing a folder's track files.

    Args:
        files: The track files, in album order.
        title: Album title (sheet-level ``TITLE``).
        performer: Album artist (sheet-level ``PERFORMER``).

    Returns:
        The sheet text, ending with one newline.

    Raises:
        ValueError: No files were given, or two files claim one track number.
    """
    if not files:
        raise ValueError("A CUE sheet needs at least one audio file.")
    return build_cue(title=title, performer=performer, files=folder_specs(files))
