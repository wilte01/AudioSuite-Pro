"""
core/inspector.py
Reads audio file metadata without decoding the full audio stream.
"""

from __future__ import annotations

import logging
from pathlib import Path

try:
    from mutagen import MutagenError
except ImportError:
    MutagenError = Exception  # type: ignore[misc,assignment]

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS

from .models import AudioFileInfo

logger = logging.getLogger(__name__)


def inspect(path: Path) -> AudioFileInfo:
    """
    Return an AudioFileInfo for the given file.
    Falls back gracefully if mutagen is unavailable or the file is unreadable.
    """
    info = AudioFileInfo(path=path, format=path.suffix.lstrip(".").upper())

    try:
        from mutagen import File as MutagenFile

        mf = MutagenFile(str(path), easy=False)
        if mf is None:
            return info

        audio_info = getattr(mf, "info", None)
        if audio_info:
            # mutagen's OggOpusInfo has no `sample_rate` attribute (verified:
            # getattr returns the fallback every time for .opus files).
            # Opus is always 48000 Hz internally per RFC 6716 regardless of
            # the original source material's rate, so that is the correct
            # value here — not the generic 44100 fallback used for formats
            # where the attribute is simply absent for other reasons.
            default_sample_rate = 48000 if path.suffix.lower() == ".opus" else 44100
            info.sample_rate = getattr(audio_info, "sample_rate", default_sample_rate)
            info.channels = getattr(audio_info, "channels", 2)
            info.duration_sec = getattr(audio_info, "length", 0.0)
            raw_bitrate = getattr(audio_info, "bitrate", 0)
            info.bitrate_kbps = raw_bitrate // 1000

        info.tag_count = len(mf.tags) if mf.tags else 0

        if path.suffix.lower() == ".mp3":
            _enrich_mp3(path, info)

    except (MutagenError, OSError, ValueError) as exc:
        logger.warning("inspect(%s): %s", path.name, exc)

    return info


def _enrich_mp3(path: Path, info: AudioFileInfo) -> None:
    """Populate MP3-specific fields: VBR flag and ID3 version."""
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError
        from mutagen.mp3 import MP3, BitrateMode

        mp3 = MP3(str(path))
        mp3_info = mp3.info
        if mp3_info is not None:
            info.is_vbr = mp3_info.bitrate_mode in (
                BitrateMode.VBR,
                BitrateMode.ABR,
            )

        try:
            id3 = ID3(str(path))
            info.id3_version = id3.version[1] if id3.version[1] in (3, 4) else 3
        except ID3NoHeaderError:
            info.id3_version = 3

    except (MutagenError, OSError, ValueError) as exc:
        logger.warning("_enrich_mp3(%s): %s", path.name, exc)


def find_audio_files(target: Path) -> list[Path]:
    """Return all supported audio files under target (file or directory)."""
    if target.is_file():
        return [target] if target.suffix.lower() in SUPPORTED_EXTENSIONS else []
    if target.is_dir():
        return sorted(
            p for p in target.iterdir() if p.suffix.lower() in SUPPORTED_EXTENSIONS
        )
    return []
