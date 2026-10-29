"""
core/tags.py
Reads tags from a source file and writes them to the (already-written) output file.

Handles:
  - MP3   : Full ID3 interface — preserves all frame types including TXXX
            user-defined frames, APIC cover art, WXXX URL frames, etc.
            Output ID3 version (v2.3 or v2.4) is matched to the source.
  - FLAC  : Vorbis comment tags
  - OGG   : Vorbis comment tags
  - Opus  : Vorbis comment tags (verified: mutagen exposes the same
            dict-style interface as FLAC/OGG for .opus files)
  - M4A   : MP4 atom tags (iTunes-style)
  - WAV   : Tags if present
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

from __future__ import annotations

import logging
from pathlib import Path

try:
    from mutagen import MutagenError
    from mutagen.id3 import ID3
except ImportError:
    from audio_suite_shared.exceptions import MutagenError  # type: ignore[assignment]

    ID3 = None  # type: ignore[misc,assignment]

logger = logging.getLogger(__name__)


def copy_tags(src: Path, dst: Path) -> tuple[bool, int]:
    """
    Copy all tags from src to dst.

    Returns
    -------
    (success, frames_copied)
    """
    try:
        from mutagen import File as MutagenFile  # noqa: F401  (existence check)
    except ImportError:
        logger.warning("mutagen not installed - tags will not be preserved")
        return False, 0

    if src.suffix.lower() == ".mp3":
        return _copy_id3(src, dst)
    return _copy_generic(src, dst)


# ──────────────────────────────────────────────────────────────────────────────
# MP3 / ID3
# ──────────────────────────────────────────────────────────────────────────────


def _copy_id3(src: Path, dst: Path) -> tuple[bool, int]:
    """
    Copy all ID3 frames from src to dst, preserving the source ID3 version.

    pedalboard writes a bare MP3 stream with no ID3 header; we create a
    fresh ID3() object when ID3NoHeaderError is raised on the destination,
    then save it with v2_version matching the source (v2.3 or v2.4).
    """
    from mutagen.id3 import (  # local import — safe if mutagen absent
        ID3,
        ID3NoHeaderError,
    )

    try:
        src_id3 = ID3(str(src))
    except ID3NoHeaderError:
        logger.warning("_copy_id3: source %s has no ID3 header", src.name)
        return False, 0
    except (MutagenError, OSError, ValueError) as exc:
        logger.error("_copy_id3: cannot read %s - %s", src.name, exc, exc_info=True)
        return False, 0

    try:
        dst_id3 = ID3(str(dst))
    except ID3NoHeaderError:
        dst_id3 = ID3()  # create fresh header for bare pedalboard output

    for key, frame in src_id3.items():
        dst_id3[key] = frame

    # Detect source ID3 minor version (2.3 or 2.4) and match on output.
    src_minor = (
        src_id3.version[1] if src_id3.version and src_id3.version[1] in (3, 4) else 3
    )

    try:
        dst_id3.save(str(dst), v2_version=src_minor, v1=2)
    except (MutagenError, OSError, ValueError) as exc:
        logger.error("_copy_id3: save failed for %s - %s", dst.name, exc, exc_info=True)
        return False, 0

    _log_id3_summary(src_id3, src_minor)
    return True, len(src_id3)


def _log_id3_summary(id3: "ID3", version: int) -> None:
    standard, txxx, other = [], [], []
    for key, frame in id3.items():
        if key.startswith("TXXX"):
            val = getattr(frame, "text", ["?"])
            txxx.append(f"{key} = {val[0]!r}" if val else key)
        elif key.startswith("APIC"):
            other.append("APIC (cover art)")
        else:
            standard.append(key)

    logger.info(
        "ID3v2.%d - %d frame(s): %d standard, %d TXXX, %d other",
        version,
        len(id3),
        len(standard),
        len(txxx),
        len(other),
    )
    for t in txxx:
        logger.debug("  TXXX: %s", t)


# ──────────────────────────────────────────────────────────────────────────────
# Generic (FLAC, OGG, M4A, WAV …)
# ──────────────────────────────────────────────────────────────────────────────


def _copy_generic(src: Path, dst: Path) -> tuple[bool, int]:
    from mutagen import File as MutagenFile

    try:
        src_tags = MutagenFile(str(src), easy=False)
        dst_tags = MutagenFile(str(dst), easy=False)
    except (MutagenError, OSError, ValueError) as exc:
        logger.error("_copy_generic: cannot open files - %s", exc, exc_info=True)
        return False, 0

    if src_tags is None or dst_tags is None or not src_tags.tags:
        return False, 0

    copied = 0
    for key, val in src_tags.items():
        try:
            dst_tags[key] = val
            copied += 1
        except (MutagenError, OSError, ValueError) as exc:
            logger.debug("_copy_generic: skipping tag %s - %s", key, exc)

    try:
        dst_tags.save()
    except (MutagenError, OSError, ValueError) as exc:
        logger.error("_copy_generic: save failed - %s", exc, exc_info=True)
        return False, 0

    logger.info("Tags copied: %d", copied)
    return True, copied
