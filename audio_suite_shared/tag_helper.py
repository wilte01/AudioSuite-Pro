"""
tag_helper.py — Backward-compatible re-export stub.

All public API is now in sub-modules (tag_helper_base, tag_helper_reader,
tag_helper_writer, tag_helper_art). This stub preserves every import path
that existing callers rely on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from audio_suite_shared.exceptions import AudioTagError, map_to_audio_error

if TYPE_CHECKING:
    from mutagen.id3 import ID3

from .audio_formats import SUPPORTED_EXTENSIONS
from .tag_helper_art import embed_artwork
from .tag_helper_base import (
    BaseTagHandler,
    IFFID3Handler,
    MP3Handler,
    MP4Handler,
    TagHandlerFactory,
    VorbisHandler,
)
from .tag_helper_reader import (
    has_artwork,
    is_supported,
    read_album_artist,
    read_artist_album,
    read_artist_title,
    read_bpm,
    read_custom_genre_fields,
    read_energy,
    read_genre,
    read_key,
    read_mood,
    read_replaygain,
    read_synced_lyrics,
    read_tags_raw,
    read_tempo_marking,
)
from .tag_helper_writer import (
    write_album_genre_result,
    write_bpm,
    write_energy,
    write_genre,
    write_genre_sync_result,
    write_key,
    write_mood,
    write_mood_confidence,
    write_replaygain,
    write_synced_lyrics,
    write_tags_raw,
    write_tempo_marking,
)


def read_tag_text(audio: "ID3", frame_key: str) -> str | None:
    """Return the first text value of an ID3 frame, or None if absent/empty.

    Args:
        audio:     Mutagen ID3 object loaded from the target file.
        frame_key: ID3 frame identifier string, e.g. ``"TBPM"`` or
                   ``"TXXX:TEMPO"``.

    Returns:
        Stripped text value of the first text element, or ``None`` if the
        frame is missing, the text list is empty, or the value is blank.
    """
    frame = audio.get(frame_key)
    if frame is None:
        return None
    try:
        val: str = frame.text[0].strip()
        return val if val else None
    except (IndexError, AttributeError):
        return None


__all__ = [
    "AudioTagError",
    "BaseTagHandler",
    "IFFID3Handler",
    "MP3Handler",
    "MP4Handler",
    "SUPPORTED_EXTENSIONS",
    "TagHandlerFactory",
    "VorbisHandler",
    "embed_artwork",
    "has_artwork",
    "is_supported",
    "map_to_audio_error",
    "read_mood",
    "read_album_artist",
    "read_artist_album",
    "read_artist_title",
    "read_bpm",
    "read_custom_genre_fields",
    "read_energy",
    "read_genre",
    "read_key",
    "read_replaygain",
    "read_synced_lyrics",
    "read_tag_text",
    "read_tags_raw",
    "read_tempo_marking",
    "write_album_genre_result",
    "write_bpm",
    "write_energy",
    "write_genre",
    "write_genre_sync_result",
    "write_key",
    "write_mood",
    "write_mood_confidence",
    "write_replaygain",
    "write_synced_lyrics",
    "write_tags_raw",
    "write_tempo_marking",
]
