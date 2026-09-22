"""
cue_generator.py — Generate CUE sheet text from track metadata and timestamps.

Builds a spec-compliant CUE sheet whose INDEX 01 values are derived from the
provided ``start_ms`` offsets, so a generated sheet always matches the audio
it describes.  Produces text that the parser in ``cue_parser`` round-trips
identically for the supported commands.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

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
