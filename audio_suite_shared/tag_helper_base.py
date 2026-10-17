"""
tag_helper_base.py — Object-Oriented, format-aware audio tag read/write utility.

Part of audio_suite_shared. Single canonical copy used by all suite tools.
Refactored to use OO patterns for better maintainability and extensibility.

Supports: MP3, FLAC, OGG (Vorbis), M4A/MP4, Opus, WAV, AIFF, WavPack,
Monkey's Audio, Musepack, Speex, DSF

Each format handler lives in its own module (``tag_helper_mp3.py``,
``tag_helper_iffid3.py``, ``tag_helper_vorbis.py``, ``tag_helper_mp4.py``,
``tag_helper_apev2.py``, ``tag_helper_dsf.py``); this module keeps the
shared base and the factory and re-exports the handler classes so every
existing importer keeps working unchanged.

Changed in 1.1.0: registers the APEv2 (.wv/.ape/.mpc), DSF (.dsf) and Ogg Speex (.spx)
tag handlers.
Changed in 1.2.0: adds ``read_isrcs`` to the handler interface — the ISRC
retrieval half of the Audio Fingerprinter's MusicBrainz integration
(PLAN_feature_expansion.md D29).
"""

import abc
import logging
import os
from collections.abc import Callable as Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Union

from .exceptions import AudioFormatError, AudioTagError

if TYPE_CHECKING:
    from mutagen.aiff import AIFF
    from mutagen.flac import FLAC
    from mutagen.mp3 import MP3
    from mutagen.mp4 import MP4
    from mutagen.oggopus import OggOpus
    from mutagen.oggvorbis import OggVorbis
    from mutagen.wave import WAVE

    MutagenAudio = Union[MP3, FLAC, OggVorbis, OggOpus, MP4, WAVE, AIFF]
    """Union type covering all mutagen audio objects handled by the tag helpers."""

# Initialize logger for shared component
logger = logging.getLogger(f"audio_suite.{__name__}")

EDITABLE_FIELDS: tuple[str, ...] = (
    "title",
    "artist",
    "album",
    "album_artist",
    "track",
    "year",
    "genre",
    "comment",
)
"""Canonical editable tag fields exposed by the freeform Tag Editor."""


@dataclass(frozen=True)
class LyricsTags:
    """Lyric content read from a file's tags in a single handler load.

    Attributes:
        synced: LRC-formatted synced lyrics, or None if absent.
        plain: Unsynced (plain text) lyrics, or None if absent.
    """

    synced: str | None = None
    plain: str | None = None

    @property
    def has_any(self) -> bool:
        """Whether the file carries any lyric content (synced or plain)."""
        return self.synced is not None or self.plain is not None


# ── Abstract Base Class ───────────────────────────────────────────────────────


class BaseTagHandler(abc.ABC):
    """Abstract base class for format-specific tag handling."""

    def __init__(self, path: str) -> None:
        """Initialise the handler with the path to the audio file.

        Args:
            path: Absolute or relative path to the audio file.
        """
        self.path = path
        self._audio: Any = None
        self._tags: Any = None

    @abc.abstractmethod
    def load(self) -> None:
        """Load the audio file and its tags from disk."""

    @abc.abstractmethod
    def save(self) -> None:
        """Save the in-memory tags back to the file on disk."""

    @abc.abstractmethod
    def read_bpm(self) -> int | None:
        """Read the BPM tag.

        Returns:
            Integer BPM value, or None if the tag is absent or unreadable.
        """

    @abc.abstractmethod
    def write_bpm(self, bpm: int) -> None:
        """Write the BPM tag and save immediately.

        Args:
            bpm: Beats-per-minute value to store.
        """

    @abc.abstractmethod
    def read_key(self) -> str | None:
        """Read the musical Key tag.

        Returns:
            Key string (e.g. ``'Am'``), or None if absent.
        """

    @abc.abstractmethod
    def write_key(self, key: str) -> None:
        """Write the musical Key tag and save immediately.

        Args:
            key: Key string to store (e.g. ``'Am'``).
        """

    @abc.abstractmethod
    def read_tempo_marking(self) -> str | None:
        """Read the tempo-marking custom tag (TXXX:TEMPO equivalent).

        Returns:
            Tempo marking string, or None if absent.
        """

    @abc.abstractmethod
    def write_tempo_marking(self, marking: str) -> None:
        """Write the tempo-marking custom tag and save immediately.

        Args:
            marking: Human-readable tempo label (e.g. ``'Allegro'``).
        """

    @abc.abstractmethod
    def read_genre(self) -> str | None:
        """Read the Genre tag.

        Returns:
            Genre string, or None if absent.
        """

    @abc.abstractmethod
    def write_genre(self, genre: str) -> None:
        """Write the Genre tag and save immediately.

        Args:
            genre: Genre string to store.
        """

    @abc.abstractmethod
    def embed_artwork(self, jpeg_bytes: bytes) -> None:
        """Embed JPEG cover artwork, replacing any existing artwork.

        Args:
            jpeg_bytes: Raw JPEG image bytes to embed.
        """

    @abc.abstractmethod
    def extract_artwork(self) -> bytes | None:
        """Extract the raw bytes of the first embedded cover artwork.

        Returns:
            Raw image bytes (typically JPEG), or None if the file carries
            no cover artwork.
        """

    @abc.abstractmethod
    def read_custom_genre_fields(self) -> dict[str, str | None]:
        """Read suite-specific custom genre fields.

        Returns:
            Dict with keys ``TITLEGENRE``, ``ARTISTGENRE``, ``ALBUMGENRE``,
            ``ALBUMARTISTGENRE``, ``GENREDERIVED``, each mapping to a string
            value or None if absent.
        """

    @abc.abstractmethod
    def write_genre_sync_result(self, genre: str, derived_value: str) -> None:
        """Write the resolved genre and the derived-genre marker tag.

        Args:
            genre:         Final genre string to store in the standard tag.
            derived_value: Value for the ``GENREDERIVED`` custom field.
        """

    def write_album_genre_result(
        self, album_genre: str, derived_marker: str = "Y"
    ) -> None:
        """Write the consolidated ALBUMGENRE tag and ALBUMDERIVED marker.

        Args:
            album_genre: Consolidated, semicolon-separated genre string.
            derived_marker: Value for the album-derived marker. Defaults to
                ``"Y"``.

        Raises:
            AudioTagError: If the file's handler does not support this write.
        """
        raise AudioTagError(
            f"write_album_genre_result is not supported for {type(self).__name__}"
        )

    def read_artist_album(self) -> tuple[str, str]:
        """Read the Artist and Album tags.

        Returns:
            Two-tuple ``(artist, album)``.  Falls back to ``'Unknown'`` for
            any tag that is absent or unreadable.
        """
        return "Unknown", "Unknown"

    def read_artist_title(self) -> tuple[str, str]:
        """Read the Artist and Title tags.

        Returns:
            Two-tuple ``(artist, title)``.  Falls back to ``'Unknown'`` for
            any tag that is absent or unreadable.
        """
        return "Unknown", "Unknown"

    def read_album_artist(self) -> str | None:
        """Read the Album Artist tag.

        Returns:
            Album artist string, or None if absent.
        """
        return None

    def read_custom_field(self, name: str) -> str | None:
        """Read one arbitrary custom tag by its canonical field name.

        The base implementation returns None; each format handler overrides it
        with the lookup appropriate to its tag convention (ID3 ``TXXX``
        description, Vorbis comment key, or MP4 freeform atom).

        Args:
            name: Canonical field name, e.g. ``'MUSICBRAINZ_ALBUMID'``.

        Returns:
            The field value as a string, or None if absent or unreadable.
        """
        return None

    def read_isrcs(self) -> tuple[str, ...]:
        """Read every ISRC recorded in the file.

        The base implementation returns an empty tuple; each format handler
        overrides it with the lookup appropriate to its tag convention (ID3
        ``TSRC``, the ``ISRC`` Vorbis comment, the iTunes freeform ``ISRC``
        atom, or the ``ISRC`` APEv2 item).

        Returns:
            Every ISRC the file records, deduplicated, in stored order. An
            absent or untaggable ISRC list yields an empty tuple, never None,
            so callers can iterate unconditionally.
        """
        return ()

    def read_disc_number(self) -> str | None:
        """Read the disc number tag.

        Returns:
            Disc number as a string, or None if absent.
        """
        return None

    def read_mood(self) -> str | None:
        """Read the Mood tag.

        Returns:
            Mood string, or None if absent.
        """
        return None

    def read_energy(self) -> str | None:
        """Read the Energy Level tag.

        Returns:
            Energy level string (e.g. ``'5'``), or None if absent.
        """
        return None

    def write_mood(self, mood: str) -> None:
        """Write the Mood tag and save immediately.

        Args:
            mood: Mood string to store.

        Raises:
            AudioTagError: If the file's handler does not support mood writes.
        """
        raise AudioTagError(f"write_mood is not supported for {type(self).__name__}")

    def write_mood_confidence(self, confidence: str) -> None:
        """Write the mood-confidence tag and save immediately.

        Args:
            confidence: Confidence value string (e.g. ``'0.87'``).

        Raises:
            AudioTagError: If the file's handler does not support mood writes.
        """
        raise AudioTagError(
            f"write_mood_confidence is not supported for {type(self).__name__}"
        )

    def write_energy(self, energy: str) -> None:
        """Write the energy level tag and save immediately.

        Args:
            energy: Energy band string (e.g. ``'5'``).

        Raises:
            AudioTagError: If the file's handler does not support energy writes.
        """
        raise AudioTagError(f"write_energy is not supported for {type(self).__name__}")

    def read_synced_lyrics(self) -> str | None:
        """Read the synced-lyrics (LRC) content from the file's tags.

        Returns:
            LRC-formatted lyric text, or None if the file has no synced
            lyrics embedded (or the format stores none).
        """
        return None

    def write_synced_lyrics(self, lrc_text: str) -> None:
        """Embed LRC-formatted synced lyrics and save immediately.

        Args:
            lrc_text: LRC lyrics text to store.

        Raises:
            AudioTagError: If the file's handler does not support synced
                lyrics writes.
        """
        raise AudioTagError(
            f"write_synced_lyrics is not supported for {type(self).__name__}"
        )

    def read_lyrics_tags(self) -> LyricsTags:
        """Read both synced and plain lyrics in a single handler load.

        Returns:
            A :class:`LyricsTags` with the synced/plain lyric text, or an
            all-None instance when the format stores neither.
        """
        return LyricsTags()

    def write_plain_lyrics(self, text: str) -> None:
        """Embed unsynced (plain text) lyrics and save immediately.

        Args:
            text: Plain lyric text to store.

        Raises:
            AudioTagError: If the file's handler does not support plain
                lyric writes.
        """
        raise AudioTagError(
            f"write_plain_lyrics is not supported for {type(self).__name__}"
        )

    def has_artwork(self) -> bool:
        """Return True if the file has embedded cover artwork.

        Returns:
            True when cover art is present in the file's tag container.
        """
        return False

    def read_replaygain(self) -> tuple[str | None, str | None]:
        """Read the ReplayGain track and album gain tags.

        Returns:
            Two-tuple ``(track_gain, album_gain)`` as string values (e.g.
            ``'+0.10 dB'``), or None for each absent value.
        """
        return None, None

    def read_editable_tags(self) -> dict[str, str | None]:
        """Read the freeform editor fields from the file's tags.

        Returns:
            Dict mapping every field in ``EDITABLE_FIELDS`` to its string
            value, or ``None`` when the field is absent.
        """
        return {field: None for field in EDITABLE_FIELDS}

    def write_editable_tag(self, field: str, value: str | None) -> None:
        """Write or clear one freeform editor field and save immediately.

        Args:
            field: Canonical field name from ``EDITABLE_FIELDS``.
            value: String value to store, or ``None`` to remove the field.

        Raises:
            AudioTagError: If the handler cannot edit the requested field.
        """
        raise AudioTagError(
            f"write_editable_tag is not supported for {type(self).__name__}"
        )

    def delete_tags(self) -> None:
        """Remove the file's tag container without touching its audio payload.

        Raises:
            AudioTagError: If the handler cannot delete tags.
        """
        raise AudioTagError(f"delete_tags is not supported for {type(self).__name__}")

    def get_raw_tags(self) -> Any:
        """Return the raw mutagen tags object for direct manipulation.

        Returns:
            The underlying mutagen tags object, or None if not loaded.
        """
        return self._tags

    def set_raw_tags(self, tags: Any) -> None:
        """Replace the internal tags object and persist it to disk.

        Args:
            tags: A mutagen tags object (or None to clear).
        """
        self._tags = tags


# ── Facade re-exports / handler registry inputs ─────────────────────────
# The per-format handler modules import BaseTagHandler from this module,
# so they cannot be imported while this module is still initialising; the
# imports therefore sit here, after the base class is fully defined (the
# redundant-alias form marks them as explicit re-exports for type
# checkers). Consequence: in a fresh interpreter the FIRST import of this
# cluster must be tag_helper_base (or any module that reaches it), never
# a handler module directly — direct-first-entry would find the handler
# module only partially initialised.
from .tag_helper_apev2 import APEv2Handler as APEv2Handler  # noqa: E402
from .tag_helper_dsf import DSFID3Handler as DSFID3Handler  # noqa: E402
from .tag_helper_iffid3 import IFFID3Handler as IFFID3Handler  # noqa: E402
from .tag_helper_mp3 import MP3Handler as MP3Handler  # noqa: E402
from .tag_helper_mp4 import MP4Handler as MP4Handler  # noqa: E402
from .tag_helper_vorbis import VorbisHandler as VorbisHandler  # noqa: E402


class TagHandlerFactory:
    """Factory for obtaining the appropriate tag handler for a file."""

    _handlers: dict[str, type[BaseTagHandler]] = {
        ".mp3": MP3Handler,
        ".flac": VorbisHandler,
        ".ogg": VorbisHandler,
        ".opus": VorbisHandler,
        ".spx": VorbisHandler,
        ".m4a": MP4Handler,
        ".mp4": MP4Handler,
        ".wav": IFFID3Handler,
        ".aiff": IFFID3Handler,
        ".aif": IFFID3Handler,
        ".wv": APEv2Handler,
        ".ape": APEv2Handler,
        ".mpc": APEv2Handler,
        ".dsf": DSFID3Handler,
    }

    @classmethod
    def get_handler(cls, path: str) -> BaseTagHandler:
        """Return a loaded handler appropriate for the file's extension.

        Args:
            path: Path to the audio file.

        Returns:
            A fully loaded ``BaseTagHandler`` subclass instance.

        Raises:
            ValueError: If the file extension has no registered handler.
        """
        ext = os.path.splitext(path)[1].lower()
        handler_cls = cls._handlers.get(ext)
        if not handler_cls:
            raise AudioFormatError(f"Unsupported format: {ext}")

        handler = handler_cls(path)
        handler.load()
        return handler
