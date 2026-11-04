"""
tag_helper_base.py — Object-Oriented, format-aware audio tag read/write utility.

Part of audio_suite_shared. Single canonical copy used by all suite tools.
Refactored to use OO patterns for better maintainability and extensibility.

Supports: MP3, FLAC, OGG (Vorbis), M4A/MP4, Opus, WAV, AIFF, WavPack,
Monkey's Audio, Musepack, Speex, DSF

Each format handler lives in its own module (``tag_helper_mp3.py``,
``tag_helper_iffid3.py``, ``tag_helper_vorbis.py``, ``tag_helper_mp4.py``,
``tag_helper_apev2.py``, ``tag_helper_dsf.py``); this module keeps the
shared base and resolves the handler classes and the factory lazily, on
first access, so every existing importer keeps working while no handler
module has to be imported here at import time. These are the rules that make
the tag helpers authoritative; each names the module that owns it.

Changed in 1.1.0: registers the APEv2 (.wv/.ape/.mpc), DSF (.dsf) and Ogg Speex (.spx)
tag handlers.
Changed in 1.2.0: adds ``read_isrcs`` to the handler interface — the ISRC
retrieval half of the Audio Fingerprinter's MusicBrainz integration
(PLAN_feature_expansion.md D29).

Changed in 2.4.1: the six handler imports and ``TagHandlerFactory`` moved
out of this module; handler classes and the factory are resolved lazily by
``__getattr__``, so any tag-helper module may be the first import (WP-2).

Changed in 2.4.2: ``read_field_key`` / ``set_field_key`` join the handler
interface and each handler declares its ``convention`` — the two primitives
``audio_suite_shared.tag_field_engine`` needs so one field table can drive
every container without the engine touching mutagen (WP-6).
"""

import abc
import logging
from collections.abc import Callable as Callable
from dataclasses import dataclass
from importlib import import_module as _import_module
from typing import TYPE_CHECKING, Any, Union

from .exceptions import AudioTagError

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
    "disc",
    "year",
    "genre",
    "comment",
)
"""Canonical editable tag fields exposed by the freeform Tag Editor.

This tuple is also the canonical set
``audio_suite_shared.tag_field_engine`` builds its field table from, so a field
added here is a field the engine can read and write (and a field it cannot
place in a container fails loudly rather than silently).  ``genre`` carries a
key rule of its own in that table because the Tag Field Updater rewrites its
container key directly, preserving a v2.3 file's Latin-1 encoding.

Changed in 2.2.0: ``disc`` joins the set, so the Tag Field Updater's filename
source can write a parsed ``%disc%`` instead of dropping it.  Every format
already had a disc *read* (``read_disc_number``); only the write mapping was
missing.
"""


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

    #: The tag convention this handler speaks: ``"id3"``, ``"vorbis"``,
    #: ``"mp4"`` or ``"apev2"``.  ``audio_suite_shared.tag_field_engine`` reads
    #: it to pick a field's container key, so a new handler must declare it and
    #: implement the two key primitives below.
    convention: str = ""

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

    def read_duration(self) -> float | None:
        """Read the file's playing time from the already-loaded audio.

        Reads mutagen's ``info.length`` on the object :meth:`load` stored, so a
        caller that has loaded the handler once pays no second decode.  Used by
        the playlist export, where an ``#EXTINF`` line wants seconds and an
        unknown duration is honestly reported as None rather than guessed.

        Returns:
            Duration in seconds, or None when the loaded object exposes no
            numeric length (or nothing is loaded yet).
        """
        length = getattr(getattr(self._audio, "info", None), "length", None)
        if isinstance(length, (int, float)) and not isinstance(length, bool):
            return float(length)
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

    def read_field_key(self, key: str) -> str | None:
        """Read one container key in this handler's own convention.

        The base implementation refuses: a handler that has not said how its
        container stores a key cannot be driven by the field engine, and a
        silent ``None`` would look like an absent tag.

        Args:
            key: Container key in this convention (an ID3 frame id or
                ``TXXX:desc``, a Vorbis comment name, an MP4 atom/freeform key,
                or an APEv2 item name).

        Returns:
            The stored value, or None when the key is absent.

        Raises:
            AudioTagError: If this handler does not implement key access.
        """
        raise AudioTagError(
            f"read_field_key is not supported for {type(self).__name__}"
        )

    def set_field_key(self, key: str, value: str | None) -> None:
        """Store or remove one container key, without saving.

        Mutation only: the caller batches several fields and calls ``save()``
        once, so a five-field rewrite is one container write rather than five.

        Args:
            key: Container key in this convention.
            value: Value to store, or None to remove the key.

        Raises:
            AudioTagError: If this handler does not implement key access, or
                the key is not one this container can hold.
        """
        raise AudioTagError(f"set_field_key is not supported for {type(self).__name__}")

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


# ── Lazy re-exports ──────────────────────────────
# The handler modules subclass BaseTagHandler, so importing them here made
# this module unimportable unless it were the first one imported: that is the
# cycle that made a handler module an invalid first import (2.4.1 WP-2). The
# names below are resolved on first access instead (PEP 562). The factory
# lives in the leaf ``tag_handler_factory`` module and is listed here so an
# in-tree or third-party import of it from this module keeps working for this
# release; drop that entry once a minor has passed.
_LAZY_REEXPORTS: dict[str, str] = {
    "APEv2Handler": "tag_helper_apev2",
    "DSFID3Handler": "tag_helper_dsf",
    "IFFID3Handler": "tag_helper_iffid3",
    "MP3Handler": "tag_helper_mp3",
    "MP4Handler": "tag_helper_mp4",
    "TagHandlerFactory": "tag_handler_factory",
    "VorbisHandler": "tag_helper_vorbis",
}


def __getattr__(name: str) -> Any:
    """Resolve a re-exported name on first access.

    Args:
        name: Attribute requested from this module.

    Returns:
        The attribute, taken from the module named in ``_LAZY_REEXPORTS``.

    Raises:
        AttributeError: When the name is not one of the lazy re-exports.
    """
    module_name = _LAZY_REEXPORTS.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    return getattr(_import_module(f".{module_name}", __package__), name)


def __dir__() -> list[str]:
    """List this module's attributes, including the lazy re-exports.

    Returns:
        Sorted attribute names.
    """
    return sorted(set(globals()) | set(_LAZY_REEXPORTS))
