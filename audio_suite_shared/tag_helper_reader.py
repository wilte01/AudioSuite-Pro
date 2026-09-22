"""
tag_helper_reader.py — Read-only facade functions for audio tag access.

Part of audio_suite_shared. All functions delegate to TagHandlerFactory
and handle errors uniformly.
"""

from __future__ import annotations

from typing import Any

from .audio_formats import SUPPORTED_EXTENSIONS
from .exceptions import handle_audio_errors
from .tag_helper_base import LyricsTags, TagHandlerFactory


@handle_audio_errors(reraise=False, return_on_error=False, context="tag_read")
def is_supported(filename: str) -> bool:
    """Return True if the filename has a supported audio extension.

    Args:
        filename: Filename or path to check.

    Returns:
        True if the extension is in ``SUPPORTED_EXTENSIONS``.
    """
    return filename.lower().endswith(SUPPORTED_EXTENSIONS)


@handle_audio_errors(reraise=False, return_on_error=None, context="tag_read")
def read_bpm(path: str) -> int | None:
    """Read the BPM tag from any supported audio file.

    Args:
        path: Path to the audio file.

    Returns:
        Integer BPM, or None on failure.
    """
    return TagHandlerFactory.get_handler(path).read_bpm()


@handle_audio_errors(reraise=False, return_on_error=None, context="tag_read")
def read_key(path: str) -> str | None:
    """Read the musical key tag from any supported audio file.

    Args:
        path: Path to the audio file.

    Returns:
        Key string, or None on failure.
    """
    return TagHandlerFactory.get_handler(path).read_key()


@handle_audio_errors(reraise=False, return_on_error=None, context="tag_read")
def read_tempo_marking(path: str) -> str | None:
    """Read the tempo-marking custom tag from any supported audio file.

    Args:
        path: Path to the audio file.

    Returns:
        Tempo marking string, or None on failure.
    """
    return TagHandlerFactory.get_handler(path).read_tempo_marking()


@handle_audio_errors(reraise=False, return_on_error=None, context="tag_read")
def read_genre(path: str) -> str | None:
    """Read the genre tag from any supported audio file.

    Args:
        path: Path to the audio file.

    Returns:
        Genre string, or None on failure.
    """
    return TagHandlerFactory.get_handler(path).read_genre()


_EMPTY_GENRE_FIELDS: dict[str, str | None] = {
    "GENREDERIVED": None,
    "ALBUMGENRE": None,
    "ALBUMDERIVED": None,
    "ARTISTGENRE": None,
}


@handle_audio_errors(
    reraise=False, return_on_error=_EMPTY_GENRE_FIELDS, context="tag_read"
)
def read_custom_genre_fields(path: str) -> dict[str, str | None]:
    """Read suite-specific custom genre fields from any supported audio file.

    Args:
        path: Path to the audio file.

    Returns:
        Dict mapping field names to values or None.  Returns all-None dict
        on any failure.
    """
    return TagHandlerFactory.get_handler(path).read_custom_genre_fields()


@handle_audio_errors(reraise=False, return_on_error=None, context="tag_read")
def read_album_artist(path: str) -> str | None:
    """Read the album artist tag from any supported audio file.

    Args:
        path: Path to the audio file.

    Returns:
        Album artist string, or None on failure.
    """
    return TagHandlerFactory.get_handler(path).read_album_artist()


@handle_audio_errors(
    reraise=False, return_on_error=("Unknown", "Unknown"), context="tag_read"
)
def read_artist_album(path: str) -> tuple[str, str]:
    """Read the artist and album tags from any supported audio file.

    Args:
        path: Path to the audio file.

    Returns:
        Two-tuple ``(artist, album)``, defaulting to ``('Unknown', 'Unknown')``
        on any failure.
    """
    return TagHandlerFactory.get_handler(path).read_artist_album()


@handle_audio_errors(
    reraise=False, return_on_error=("Unknown", "Unknown"), context="tag_read"
)
def read_artist_title(path: str) -> tuple[str, str]:
    """Read the artist and title tags from any supported audio file.

    Args:
        path: Path to the audio file.

    Returns:
        Two-tuple ``(artist, title)``, defaulting to ``('Unknown', 'Unknown')``
        on any failure.
    """
    return TagHandlerFactory.get_handler(path).read_artist_title()


@handle_audio_errors(reraise=False, return_on_error=None, context="tag_read")
def read_mood(path: str) -> str | None:
    """Read the mood tag from any supported audio file.

    ID3: TMOO frame.  Vorbis/MP4: ``MOOD`` or ``TMOO`` comment.

    Args:
        path: Path to the audio file.

    Returns:
        Mood string (e.g. ``'Energetic'``), or None if absent.
    """
    return TagHandlerFactory.get_handler(path).read_mood()


@handle_audio_errors(reraise=False, return_on_error=None, context="tag_read")
def read_energy(path: str) -> str | None:
    """Read the energy level tag from any supported audio file.

    ID3: TXXX:ENERGYLEVEL or TXXX:ENERGY. Vorbis/MP4: ENERGYLEVEL or ENERGY.

    Args:
        path: Path to the audio file.

    Returns:
        Energy level string (e.g. ``'5'``), or None if absent.
    """
    return TagHandlerFactory.get_handler(path).read_energy()


@handle_audio_errors(reraise=False, return_on_error=False, context="tag_read")
def has_artwork(path: str) -> bool:
    """Return True if the file has embedded cover artwork.

    Args:
        path: Path to the audio file.

    Returns:
        True when cover art is present, False on absence or read failure.
    """
    return TagHandlerFactory.get_handler(path).has_artwork()


@handle_audio_errors(reraise=False, return_on_error=(None, None), context="tag_read")
def read_replaygain(path: str) -> tuple[str | None, str | None]:
    """Read the ReplayGain track and album gains from the file.

    Args:
        path: Path to the audio file.

    Returns:
        Two-tuple ``(track_gain, album_gain)`` string values, or
        ``(None, None)`` on failure.
    """
    return TagHandlerFactory.get_handler(path).read_replaygain()


@handle_audio_errors(reraise=False, return_on_error=None, context="tag_read")
def read_synced_lyrics(path: str) -> str | None:
    """Read LRC-formatted synced lyrics from any supported audio file.

    MP3/WAV/AIFF read the ID3 SYLT lyric frame; FLAC/OGG/Opus read the
    ``SYNCEDLYRICS`` (falling back to ``LYRICS``) Vorbis comment field.

    Args:
        path: Path to the audio file.

    Returns:
        LRC lyrics text, or None if absent or on read failure.
    """
    return TagHandlerFactory.get_handler(path).read_synced_lyrics()


@handle_audio_errors(reraise=False, return_on_error=LyricsTags(), context="tag_read")
def read_lyrics_tags(path: str) -> LyricsTags:
    """Read synced and plain lyrics from a file in a single handler load.

    MP3/WAV/AIFF read the ID3 SYLT and USLT frames; FLAC/OGG/Opus read the
    ``SYNCEDLYRICS`` and ``LYRICS`` Vorbis comments; M4A/MP4 read the
    ``\xa9lyr`` atom.

    Args:
        path: Path to the audio file.

    Returns:
        :class:`LyricsTags` with the synced/plain lyric text, or an all-None
        instance when the file stores neither (or on read failure).
    """
    return TagHandlerFactory.get_handler(path).read_lyrics_tags()


@handle_audio_errors(reraise=False, return_on_error=None, context="tag_read")
def read_tags_raw(path: str) -> Any:
    """Return the raw mutagen tags object for a file without interpretation.

    Args:
        path: Path to the audio file.

    Returns:
        Raw mutagen tags object, or None on failure.
    """
    return TagHandlerFactory.get_handler(path).get_raw_tags()
