"""
cue_split.py — Split a single-file audio image into tracks from a CUE sheet.

Each track is cut from its source image with FFmpeg using ``-ss`` / ``-to``
on the exact track timestamps and ``-c copy`` (no re-encode).  All external
process invocation is routed through ``run_secure_subprocess()`` so every
argument is validated for injection risk; metadata values are sanitised
before being embedded in ``-metadata`` arguments.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from pathlib import Path

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.cue_parser import parse_cue_file
from audio_suite_shared.exceptions import (
    AudioExternalToolError,
    AudioFileNotFoundError,
)
from audio_suite_shared.secure_subprocess import run_secure_subprocess

logger = logging.getLogger(__name__)

_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/*?:"<>|]')
# Characters DANGEROUS_CHARS + shell-metacharacters the subprocess validator
# rejects inside arguments.  Single quotes are preserved where possible.
_META_UNSAFE_CHARS = set('"<>`|;&$(')


def _safe_filename(name: str) -> str:
    """Return *name* with characters illegal in Windows filenames replaced."""
    return _ILLEGAL_FILENAME_CHARS.sub("_", name).strip()


def _clean_meta(value: str) -> str:
    """Sanitise a metadata value so it is a safe subprocess argument.

    Double quotes and shell metacharacters are replaced/removed so the value
    never trips the subprocess security validator.
    """
    cleaned: list[str] = []
    for ch in value:
        if ch in _META_UNSAFE_CHARS:
            cleaned.append(" ")
        else:
            cleaned.append(ch)
    return "".join(cleaned)


def _ffmpeg_time(ms: int) -> str:
    return f"{ms / 1000:.3f}"


def _locate_image(cue_dir: Path, filename: str) -> Path:
    """Resolve a FILE reference relative to the CUE sheet's directory."""
    candidate = Path(filename)
    if not candidate.is_absolute():
        candidate = cue_dir / candidate
    resolved = candidate.resolve()
    if not resolved.is_file():
        raise AudioFileNotFoundError(
            "Audio image referenced by the CUE sheet was not found",
            path=str(resolved),
        )
    return resolved


def split_cue_file(
    cue_path: str | Path,
    output_dir: str | Path,
    *,
    ffmpeg: str = "ffmpeg",
    timeout: int = 7200,
    progress_cb: Callable[[str], None] | None = None,
) -> list[str]:
    """Split the audio image(s) referenced by *cue_path* into per-track files.

    Args:
        cue_path:    Path to the CUE sheet (UTF-8).
        output_dir:  Destination folder; created if it does not exist.
        ffmpeg:      FFmpeg executable (a name on PATH or an absolute path).
        timeout:     Per-track subprocess timeout in seconds.
        progress_cb: Optional callback invoked as each track starts,
                     receiving a human-readable progress message.

    Returns:
        The absolute paths written, in track order.

    Raises:
        CueParseError:         The CUE sheet is malformed.
        ValueError:            A track lacks an INDEX 01, the image format is
                               unsupported as a split target, or the sheet has
                               no tracks at all.
        AudioFileNotFoundError:A referenced image file does not exist.
        AudioExternalToolError:FFmpeg failed for one of the tracks.
        SubprocessSecurityError: An FFmpeg argument failed validation.
    """
    sheet = parse_cue_file(cue_path)
    cue_dir = Path(cue_path).resolve().parent
    out_root = Path(output_dir)
    out_root.mkdir(parents=True, exist_ok=True)

    album_title = sheet.title or ""
    written: list[str] = []

    for entry in sheet.files:
        if not entry.tracks:
            continue
        image = _locate_image(cue_dir, entry.filename)
        ext = image.suffix.lower()
        if ext not in SUPPORTED_EXTENSIONS:
            raise ValueError(
                f"Image format {ext!r} (from FILE {entry.filename!r}) "
                "is not a supported split target"
            )
        tracks = entry.tracks
        for ordinal, track in enumerate(tracks):
            index01 = track.index01
            if index01 is None:
                raise ValueError(
                    f"Track {track.number:02d} has no INDEX 01; cannot split"
                )
            start_ms = index01.start_ms
            end_ms: int | None = None
            for later in tracks[ordinal + 1 :]:
                later_index = later.index01
                if later_index is not None:
                    end_ms = later_index.start_ms
                    break

            title = track.title or f"Track {track.number:02d}"
            out_name = f"{track.number:02d} - {_safe_filename(title)}{ext}"
            out_path = out_root / out_name

            args: list[str] = [
                "-y",
                "-hide_banner",
                "-ss",
                _ffmpeg_time(start_ms),
            ]
            if end_ms is not None:
                args.extend(["-to", _ffmpeg_time(end_ms)])
            args.extend(["-i", str(image), "-map_metadata", "-1", "-c", "copy"])
            if title:
                args.extend(["-metadata", f"title={_clean_meta(title)}"])
            track_performer = track.performer or sheet.performer or ""
            if track_performer:
                args.extend(["-metadata", f"artist={_clean_meta(track_performer)}"])
            args.extend(["-metadata", f"track={track.number:02d}"])
            if album_title:
                args.extend(["-metadata", f"album={_clean_meta(album_title)}"])
            args.append(str(out_path))

            if progress_cb is not None:
                progress_cb(f"Track {track.number:02d}: {title}")

            proc = run_secure_subprocess(
                ffmpeg, args, capture_output=True, check=False, timeout=timeout
            )
            if proc.returncode != 0:
                stderr = (proc.stderr or "").strip()
                raise AudioExternalToolError(
                    f"Failed to split track {track.number:02d} ({title!r})",
                    tool=ffmpeg,
                    returncode=proc.returncode,
                    stderr=stderr or None,
                )
            written.append(str(out_path))

    if not written:
        raise ValueError("The CUE sheet contains no FILE entries with tracks to split")
    return written
