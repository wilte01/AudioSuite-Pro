"""
tag_writer.py
Writes ReplayGain tags to audio files.

The format-specific write strategy (TXXX frames for ID3-backed MP3/WAV/AIFF,
``----:com.apple.iTunes:`` freeform atoms for M4A/MP4, and native
VorbisComment fields for FLAC/OGG/Opus) now lives in
``audio_suite_shared.tag_helper_writer.write_replaygain``, which also
snapshots the file's previous tag state into the active undo batch before
writing.  This module keeps the MUTAGEN_AVAILABLE graceful-degradation
pattern and maps any write failure into a ``(ok, message)`` result for the
pipeline.
"""

import logging

from audio_suite_shared.exceptions import (
    AudioSuiteError,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.tag_helper_writer import write_replaygain

logger = logging.getLogger(__name__)

try:
    import mutagen

    MUTAGEN_AVAILABLE = True
except ImportError:
    MUTAGEN_AVAILABLE = False

_REPLAYGAIN_FIELDS: tuple[str, ...] = (
    "REPLAYGAIN_TRACK_GAIN",
    "REPLAYGAIN_ALBUM_GAIN",
    "REPLAYGAIN_TRACK_PEAK",
    "REPLAYGAIN_ALBUM_PEAK",
)


def write_replaygain_tags(
    file_path: str,
    track_gain_str: str,
    track_peak_str: str,
    album_gain_str: str,
    album_peak_str: str,
) -> tuple[bool, str]:
    """
    Write the four ReplayGain tags to a single audio file.

    Args:
        file_path:       Absolute path to the audio file.
        track_gain_str:  Formatted gain string, e.g. '+2.34 dB'.
        track_peak_str:  Formatted peak string, e.g. '0.912345'.
        album_gain_str:  Formatted album gain string, e.g. '+1.80 dB'.
        album_peak_str:  Formatted album peak string, e.g. '0.956789'.

    Returns:
        (True, 'TAGGED')   on success or when mutagen is unavailable.
        (False, message)   on error.
    """
    if not MUTAGEN_AVAILABLE:
        return True, "TAGGED"  # mutagen absent — treat as no-op success

    values = {
        "REPLAYGAIN_TRACK_GAIN": track_gain_str,
        "REPLAYGAIN_ALBUM_GAIN": album_gain_str,
        "REPLAYGAIN_TRACK_PEAK": track_peak_str,
        "REPLAYGAIN_ALBUM_PEAK": album_peak_str,
    }

    try:
        write_replaygain(file_path, values)
        return True, "TAGGED"
    except (AudioSuiteError, mutagen.MutagenError, OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc, context={"operation": "write_replaygain_tags"})
        logger.error("ReplayGain tag write failed: %s", mapped, exc_info=True)
        return False, user_message_for(mapped)
