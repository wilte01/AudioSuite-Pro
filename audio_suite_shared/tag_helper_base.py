"""
tag_helper_base.py — Object-Oriented, format-aware audio tag read/write utility.

Part of audio_suite_shared. Single canonical copy used by all suite tools.
Refactored to use OO patterns for better maintainability and extensibility.

Supports: MP3, FLAC, OGG (Vorbis), M4A/MP4, Opus, WAV, AIFF
"""

import abc
import logging
import os
from collections.abc import Callable
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
logger = logging.getLogger(__name__)

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


# ── Lazy Loading Imports ──────────────────────────────────────────────────────
# These are imported inside methods to speed up initial module load time.
# mutagen.mp3, mutagen.id3, mutagen.flac, mutagen.oggvorbis,
# mutagen.oggopus, mutagen.mp4

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


# ── Concrete Handlers ─────────────────────────────────────────────────────────
# NOTE: IFFID3Handler is defined after MP3Handler (below) since it subclasses it.


class MP3Handler(BaseTagHandler):
    """Handler for MP3 files using ID3 tags."""

    def load(self) -> None:
        """Load the MP3 file and its ID3 tags.

        Falls back to a tagless MP3 object if the ID3 header is unreadable.
        """
        from mutagen.id3 import ID3
        from mutagen.mp3 import MP3

        try:
            self._audio = MP3(self.path, ID3=ID3)
            self._tags = self._audio.tags
        except Exception as _id3_exc:
            # ID3 header unreadable — fall back to tagless MP3 load
            logger.debug(
                "ID3 load failed for %s, falling back: %s", self.path, _id3_exc
            )
            self._audio = MP3(self.path)
            self._tags = self._audio.tags

    def save(self) -> None:
        """Save ID3 tags back to the MP3 file."""
        if self._audio is not None:
            self._audio.save()

    def _ensure_tags(self) -> None:
        """Guarantee an ID3 tag container exists, creating one if necessary."""
        if self._tags is None:
            self._audio.add_tags()
            self._tags = self._audio.tags

    def read_bpm(self) -> int | None:
        """Read the BPM from the TBPM ID3 frame.

        Returns:
            Integer BPM, or None if the frame is absent or unparseable.
        """
        if self._tags and "TBPM" in self._tags:
            try:
                return int(float(str(self._tags["TBPM"].text[0])))
            except (ValueError, IndexError):
                pass
        return None

    def write_bpm(self, bpm: int) -> None:
        """Write BPM to the TBPM ID3 frame and save.

        Args:
            bpm: Beats-per-minute value to store.
        """
        from mutagen.id3 import TBPM

        self._ensure_tags()
        self._tags.add(TBPM(encoding=3, text=str(bpm)))
        self.save()

    def read_key(self) -> str | None:
        """Read the musical key from the TKEY ID3 frame.

        Returns:
            Key string, or None if absent.
        """
        if self._tags and "TKEY" in self._tags:
            try:
                return str(self._tags["TKEY"].text[0])
            except (ValueError, IndexError):
                pass
        return None

    def write_key(self, key: str) -> None:
        """Write the musical key to the TKEY ID3 frame and save.

        Args:
            key: Key string to store.
        """
        from mutagen.id3 import TKEY

        self._ensure_tags()
        self._tags.add(TKEY(encoding=3, text=key))
        self.save()

    def read_tempo_marking(self) -> str | None:
        """Read the tempo marking from the TXXX:TEMPO custom ID3 frame.

        Returns:
            Tempo marking string, or None if absent.
        """
        from mutagen.id3 import TXXX

        if self._tags:
            for tag in self._tags.values():
                if isinstance(tag, TXXX) and tag.desc == "TEMPO":  # type: ignore[attr-defined]
                    return str(tag.text[0]) if tag.text else None  # type: ignore[attr-defined]
        return None

    def write_tempo_marking(self, marking: str) -> None:
        """Write the tempo marking to the TXXX:TEMPO frame and save.

        Args:
            marking: Tempo label string to store.
        """
        from mutagen.id3 import TXXX

        self._ensure_tags()
        self._tags.add(TXXX(encoding=3, desc="TEMPO", text=marking))
        self.save()

    def read_genre(self) -> str | None:
        """Read genre from the TCON ID3 frame.

        Returns:
            Genre string, or None if absent.
        """
        if self._tags and "TCON" in self._tags:
            try:
                return str(self._tags["TCON"].text[0])
            except (ValueError, IndexError):
                pass
        return None

    def read_mood(self) -> str | None:
        """Read mood from the TMOO ID3 frame.

        Returns:
            Mood string, or None if absent.
        """
        if self._tags and "TMOO" in self._tags:
            try:
                return str(self._tags["TMOO"].text[0])
            except (ValueError, IndexError):
                pass
        return None

    def read_energy(self) -> str | None:
        """Read energy level from the TXXX:ENERGYLEVEL or TXXX:ENERGY frame.

        Returns:
            Energy level string (e.g. ``'5'``), or None if absent.
        """
        if self._tags:
            for frame_id in ("TXXX:ENERGYLEVEL", "TXXX:ENERGY"):
                if frame_id in self._tags:
                    try:
                        return str(self._tags[frame_id].text[0])
                    except (ValueError, IndexError):
                        pass
        return None

    def write_mood(self, mood: str) -> None:
        """Write mood to the TMOO ID3 frame and save.

        Args:
            mood: Mood string to store (e.g. ``'Energetic;Bright;Confident'``).
        """
        from mutagen.id3 import TMOO

        self._ensure_tags()
        self._tags.add(TMOO(encoding=3, text=[mood]))
        self.save()

    def write_mood_confidence(self, confidence: str) -> None:
        """Write mood confidence to the TXXX:MOOD_CONFIDENCE frame and save.

        Args:
            confidence: Confidence value string (e.g. ``'0.87'``).
        """
        from mutagen.id3 import TXXX

        self._ensure_tags()
        self._tags.delall("TXXX:MOOD_CONFIDENCE")
        self._tags.add(TXXX(encoding=3, desc="MOOD_CONFIDENCE", text=[confidence]))
        self.save()

    def write_energy(self, energy: str) -> None:
        """Write energy level to the TXXX:ENERGYLEVEL frame and save.

        Args:
            energy: Energy band string (e.g. ``'5'``).
        """
        from mutagen.id3 import TXXX

        self._ensure_tags()
        self._tags.delall("TXXX:ENERGYLEVEL")
        self._tags.add(TXXX(encoding=3, desc="ENERGYLEVEL", text=[str(energy)]))
        self.save()

    def write_genre(self, genre: str) -> None:
        """Write genre to the TCON ID3 frame and save.

        Args:
            genre: Genre string to store.
        """
        from mutagen.id3 import TCON

        self._ensure_tags()
        self._tags.add(TCON(encoding=3, text=[genre]))
        self.save()

    def embed_artwork(self, jpeg_bytes: bytes) -> None:
        """Embed JPEG cover art in the APIC frame, replacing any existing art.

        Args:
            jpeg_bytes: Raw JPEG image bytes.
        """
        from mutagen.id3 import APIC

        self._ensure_tags()
        self._tags.delall("APIC")
        self._tags.add(
            APIC(
                encoding=3,
                mime="image/jpeg",
                type=3,
                desc="Cover",
                data=jpeg_bytes,
            )
        )
        self.save()

    def extract_artwork(self) -> bytes | None:
        """Extract raw picture bytes from the first APIC (cover art) frame.

        Returns:
            Raw image bytes from the first APIC frame, or None if the file
            carries no cover art.
        """
        if not self._tags:
            return None
        frames = self._tags.getall("APIC")
        if not frames:
            return None
        data: bytes = frames[0].data
        return data

    def read_custom_genre_fields(self) -> dict[str, str | None]:
        """Read suite-specific custom genre fields from TXXX frames.

        Returns:
            Dict mapping field names to values or None.
        """
        fields = (
            "TITLEGENRE",
            "ARTISTGENRE",
            "ALBUMGENRE",
            "ALBUMARTISTGENRE",
            "GENREDERIVED",
        )
        result: dict[str, str | None] = {k: None for k in fields}
        if self._tags:
            for frame in self._tags.getall("TXXX"):
                key = frame.desc.upper()
                if key in result:
                    result[key] = frame.text[0] if frame.text else None
        return result

    def write_genre_sync_result(self, genre: str, derived_value: str) -> None:
        """Write the resolved genre (TCON) and GENREDERIVED marker (TXXX) and save.

        Args:
            genre:         Genre string for the standard TCON frame.
            derived_value: Value for the TXXX:GENREDERIVED custom frame.
        """
        from mutagen.id3 import TCON, TXXX

        self._ensure_tags()
        self._tags.add(TCON(encoding=3, text=[genre]))
        self._tags.delall("TXXX:GENREDERIVED")
        self._tags.add(TXXX(encoding=3, desc="GENREDERIVED", text=[derived_value]))
        self.save()

    def write_album_genre_result(
        self, album_genre: str, derived_marker: str = "Y"
    ) -> None:
        """Write the consolidated ALBUMGENRE tag and ALBUMDERIVED marker, then save.

        Used by Album Genre Tagger to persist the album-level consolidated
        genre string and flag the file as having been processed.

        Args:
            album_genre: Consolidated, semicolon-separated genre string to
                store in the TXXX:ALBUMGENRE custom frame.
            derived_marker: Value for the TXXX:ALBUMDERIVED custom frame.
                Defaults to "Y".
        """
        from mutagen.id3 import TXXX

        self._ensure_tags()
        self._tags.delall("TXXX:ALBUMGENRE")
        self._tags.add(TXXX(encoding=3, desc="ALBUMGENRE", text=[album_genre]))
        self._tags.delall("TXXX:ALBUMDERIVED")
        self._tags.add(TXXX(encoding=3, desc="ALBUMDERIVED", text=[derived_marker]))
        self.save()

    def read_artist_album(self) -> tuple[str, str]:
        """Read TPE1 (artist) and TALB (album) ID3 frames.

        Returns:
            Two-tuple ``(artist, album)``, defaulting to ``'Unknown'``.
        """
        artist = "Unknown"
        album = "Unknown"
        if self._tags:
            try:
                if self._tags.get("TPE1"):
                    artist = str(self._tags["TPE1"].text[0])
                if self._tags.get("TALB"):
                    album = str(self._tags["TALB"].text[0])
            except (ValueError, IndexError):
                pass
        return artist, album

    def read_artist_title(self) -> tuple[str, str]:
        """Read TPE1 (artist) and TIT2 (title) ID3 frames.

        Returns:
            Two-tuple ``(artist, title)``, defaulting to ``'Unknown'``.
        """
        artist = "Unknown"
        title = "Unknown"
        if self._tags:
            try:
                if self._tags.get("TPE1"):
                    artist = str(self._tags["TPE1"].text[0])
                if self._tags.get("TIT2"):
                    title = str(self._tags["TIT2"].text[0])
            except (ValueError, IndexError):
                pass
        return artist, title

    def read_album_artist(self) -> str | None:
        """Read the Album Artist from the TPE2 ID3 frame.

        Returns:
            Album artist string, or None if absent.
        """
        if self._tags and "TPE2" in self._tags:
            try:
                return str(self._tags["TPE2"].text[0])
            except (ValueError, IndexError):
                return None
        return None

    def has_artwork(self) -> bool:
        """Return True if at least one APIC (cover art) frame is present.

        Returns:
            True when an APIC frame exists in the ID3 tag container.
        """
        return bool(self._tags) and bool(self._tags.getall("APIC"))

    def read_replaygain(self) -> tuple[str | None, str | None]:
        """Read ReplayGain gains from ``TXXX:REPLAYGAIN_*`` frames.

        Description matching is case-insensitive.

        Returns:
            Two-tuple ``(track_gain, album_gain)``, or None for each absent
            or empty frame.
        """
        track_gain: str | None = None
        album_gain: str | None = None
        if self._tags:
            for frame in self._tags.getall("TXXX"):
                desc = str(frame.desc).upper()
                if desc == "REPLAYGAIN_TRACK_GAIN" and frame.text:
                    track_gain = str(frame.text[0])
                elif desc == "REPLAYGAIN_ALBUM_GAIN" and frame.text:
                    album_gain = str(frame.text[0])
        return track_gain, album_gain

    def write_synced_lyrics(self, lrc_text: str) -> None:
        """Embed LRC lyrics as an ID3 SYLT frame and save.

        Uses ``SYLT`` with ``format=2`` (enhanced text / LRC), ``type=1``
        (lyrics) and the neutral ``lang="XXX"`` description key so players
        recognise the frame as synchronised lyrics. Any existing SYLT frame
        is replaced.

        Any legacy ``TXXX:SYNCEDLYRICS`` frames (written by MusicBrainz
        Picard and similar taggers) are also removed to prevent duplicates.

        Args:
            lrc_text: LRC lyrics text. Timestamps are validated.

        Raises:
            LrcParseError: If *lrc_text* contains lyric text without a
                timestamp or a malformed ``[offset:]`` tag.
        """
        from mutagen.id3 import SYLT

        from .lrc_handler import parse_lrc

        document = parse_lrc(lrc_text)
        self._ensure_tags()
        self._tags.delall("SYLT")
        self._tags.delall("TXXX:SYNCEDLYRICS")
        self._tags.add(
            SYLT(
                encoding=3,
                lang="XXX",
                format=2,
                type=1,
                desc="",
                text=[(line.text, line.timestamp_ms) for line in document.lines],
            )
        )
        self.save()

    def read_synced_lyrics(self) -> str | None:
        """Return LRC-formatted lyrics from the first SYLT lyric frame.

        Only SYLT frames flagged as lyrics (``type == 1``) are considered;
        the first matching frame is used.

        Falls back to the ``TXXX:SYNCEDLYRICS`` custom frame (the
        convention used by MusicBrainz Picard and others) when no SYLT
        frame is present, so legacy-tagged files are still recognised.

        Returns:
            LRC lyric text, or None if no lyric frame is present.
        """
        from .lrc_handler import generate_lrc

        if self._tags:
            for frame in self._tags.getall("SYLT"):
                if frame.type == 1:
                    lines: list[tuple[int, str]] = [
                        (int(time_ms), str(text)) for text, time_ms in frame.text
                    ]
                    return generate_lrc(lines)
            txxx = self._tags.getall("TXXX:SYNCEDLYRICS")
            if txxx and txxx[0].text:
                return str(txxx[0].text[0])
        return None

    def read_lyrics_tags(self) -> LyricsTags:
        """Read the ID3 SYLT (synced) and first USLT (plain) lyric frames.

        Falls back to ``TXXX:SYNCEDLYRICS`` when no SYLT frame is present.

        Returns:
            :class:`LyricsTags` with the SYLT lyric-frame text and the first
            USLT frame's text, or None for each absent frame.
        """
        from .lrc_handler import generate_lrc

        synced: str | None = None
        plain: str | None = None
        if self._tags:
            for frame in self._tags.getall("SYLT"):
                if frame.type == 1:
                    lines: list[tuple[int, str]] = [
                        (int(time_ms), str(text)) for text, time_ms in frame.text
                    ]
                    synced = generate_lrc(lines)
                    break
            if synced is None:
                txxx = self._tags.getall("TXXX:SYNCEDLYRICS")
                if txxx and txxx[0].text:
                    synced = str(txxx[0].text[0])
            uslt_frames = self._tags.getall("USLT")
            if uslt_frames:
                plain = str(uslt_frames[0].text)
        return LyricsTags(synced=synced, plain=plain)

    def write_plain_lyrics(self, text: str) -> None:
        """Embed unsynced lyrics as an ID3 USLT frame and save.

        Uses ``USLT`` with the neutral ``lang="XXX"`` and an empty
        description so players recognise the frame as plain lyrics. Any
        existing USLT frame is replaced.

        Args:
            text: Plain lyric text to store.
        """
        from mutagen.id3 import USLT

        self._ensure_tags()
        self._tags.delall("USLT")
        self._tags.add(USLT(encoding=3, lang="XXX", desc="", text=text))
        self.save()

    def read_editable_tags(self) -> dict[str, str | None]:
        """Read the freeform editor fields from ID3 frames.

        Year values prefer the modern TDRC frame and fall back to legacy
        TYER. Comment values read the first COMM frame regardless of its
        language or description.

        Returns:
            Dict mapping every field in ``EDITABLE_FIELDS`` to its string
            value, or ``None`` when the field is absent.
        """
        frame_by_field: dict[str, str] = {
            "title": "TIT2",
            "artist": "TPE1",
            "album": "TALB",
            "album_artist": "TPE2",
            "track": "TRCK",
            "genre": "TCON",
        }
        result = super().read_editable_tags()
        if self._tags:
            for field, frame_id in frame_by_field.items():
                result[field] = self._read_id3_frame_text(frame_id)
            year = self._read_id3_frame_text("TDRC")
            if year is None:
                year = self._read_id3_frame_text("TYER")
            result["year"] = year
            result["comment"] = self._read_id3_comment()
        return result

    def write_editable_tag(self, field: str, value: str | None) -> None:
        """Write or clear one freeform editor field in its ID3 frame.

        Args:
            field: Canonical field name from ``EDITABLE_FIELDS``.
            value: String value to store, or ``None`` to remove the field.

        Raises:
            AudioTagError: If the field is not editable for ID3 files.
        """
        from mutagen.id3 import COMM, TALB, TCON, TDRC, TIT2, TPE1, TPE2, TRCK

        frame_by_field: dict[str, str] = {
            "title": "TIT2",
            "artist": "TPE1",
            "album": "TALB",
            "album_artist": "TPE2",
            "track": "TRCK",
            "genre": "TCON",
        }
        if field not in frame_by_field and field not in ("year", "comment"):
            raise AudioTagError(f"Unsupported editable tag field: {field}")

        self._ensure_tags()
        if field == "comment":
            self._tags.delall("COMM")
            if value is not None:
                self._tags.setall(
                    "COMM", [COMM(encoding=3, lang="XXX", desc="", text=value)]
                )
        elif field == "year":
            self._tags.delall("TDRC")
            self._tags.delall("TYER")
            if value is not None:
                self._tags.add(TDRC(encoding=3, text=[value]))
        else:
            frame_id = frame_by_field[field]
            frame_classes: dict[str, Callable[..., object]] = {
                "TIT2": TIT2,
                "TPE1": TPE1,
                "TALB": TALB,
                "TPE2": TPE2,
                "TRCK": TRCK,
                "TCON": TCON,
            }
            frame_cls = frame_classes.get(frame_id)
            if frame_cls is None:
                raise AudioTagError(f"Unsupported ID3 frame: {frame_id}")
            self._tags.delall(frame_id)
            if value is not None:
                self._tags.add(frame_cls(encoding=3, text=[value]))
        self.save()

    def delete_tags(self) -> None:
        """Remove the ID3 tag container and reload the audio file."""
        if self._audio is None:
            return
        self._audio.delete()
        self.load()

    def _read_id3_frame_text(self, frame_id: str) -> str | None:
        """Read the first text value from an ID3 frame.

        Args:
            frame_id: ID3 frame identifier.

        Returns:
            The frame's first text value, or ``None`` when absent or empty.
        """
        if not self._tags:
            return None
        frames = self._tags.getall(frame_id)
        if not frames:
            return None
        try:
            text = frames[0].text
            if not text:
                return None
            return str(text[0])
        except (AttributeError, IndexError, TypeError):
            return None

    def _read_id3_comment(self) -> str | None:
        """Read the first COMM frame's text.

        Returns:
            Comment text, or ``None`` when no COMM frame has text.
        """
        if not self._tags:
            return None
        frames = self._tags.getall("COMM")
        if not frames:
            return None
        try:
            text = frames[0].text
            if not text:
                return None
            return str(text[0])
        except (AttributeError, IndexError, TypeError):
            return None

    def set_raw_tags(self, tags: Any) -> None:
        """Persist a raw mutagen tags object directly to the MP3 file.

        Reloads internal state after saving to keep it consistent.

        Args:
            tags: Mutagen tags object to save, or None (no-op).
        """
        if tags is None:
            return
        try:
            tags.save(self.path)
            # Re-load to ensure internal state is consistent
            self.load()
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to save raw MP3 tags to %s", self.path)
            raise


class IFFID3Handler(MP3Handler):
    """Handler for WAV and AIFF files, both of which embed ID3 tags.

    ``mutagen.wave.WAVE`` and ``mutagen.aiff.AIFF`` both expose a ``tags``
    attribute backed by ``mutagen.id3.ID3``, identical to ``mutagen.mp3.MP3``.
    All read/write logic (TCON, TXXX, TPE1, TPE2, TALB, APIC, etc.) is
    therefore inherited unchanged from :class:`MP3Handler`; only the
    format-specific ``load()`` differs.
    """

    _MUTAGEN_CLASS_BY_EXT: dict[str, str] = {
        ".wav": "wave.WAVE",
        ".aiff": "aiff.AIFF",
        ".aif": "aiff.AIFF",
    }

    def load(self) -> None:
        """Load the WAV or AIFF file and its ID3 tags.

        Selects ``mutagen.wave.WAVE`` for ``.wav`` files and
        ``mutagen.aiff.AIFF`` for ``.aiff``/``.aif`` files, based on the
        file's extension. Falls back to a tagless load if ID3 parsing
        fails on an otherwise valid file (e.g. unusual padding).

        Raises:
            ValueError: If the file extension is neither WAV nor AIFF.
        """
        import mutagen.aiff
        import mutagen.wave

        ext = os.path.splitext(self.path)[1].lower()
        audio_cls: type[mutagen.wave.WAVE] | type[mutagen.aiff.AIFF]
        if ext == ".wav":
            audio_cls = mutagen.wave.WAVE
        elif ext in (".aiff", ".aif"):
            audio_cls = mutagen.aiff.AIFF
        else:
            raise AudioFormatError(f"IFFID3Handler cannot load extension: {ext}")

        try:
            self._audio = audio_cls(self.path)
            self._tags = self._audio.tags
        except Exception as _id3_exc:
            logger.debug(
                "ID3 load failed for %s, retrying without tags: %s",
                self.path,
                _id3_exc,
            )
            self._audio = audio_cls(self.path)
            self._tags = self._audio.tags


class VorbisHandler(BaseTagHandler):
    """Handler for Vorbis-comment files: FLAC, OGG, and Opus."""

    def load(self) -> None:
        """Load the audio file and its Vorbis comment tags."""
        ext = os.path.splitext(self.path)[1].lower()
        if ext == ".flac":
            from mutagen.flac import FLAC

            self._audio = FLAC(self.path)
        elif ext == ".opus":
            from mutagen.oggopus import OggOpus

            self._audio = OggOpus(self.path)
        else:
            from mutagen.oggvorbis import OggVorbis

            self._audio = OggVorbis(self.path)
        self._tags = self._audio.tags if hasattr(self._audio, "tags") else self._audio

    def save(self) -> None:
        """Save Vorbis comment tags back to the file."""
        if self._audio is not None:
            self._audio.save()

    def _ensure_tags(self) -> None:
        """Guarantee the Vorbis tags dict exists."""
        if not hasattr(self._audio, "tags"):
            self._tags = self._audio
            return
        if self._audio.tags is None:
            self._audio.add_tags()
        self._tags = self._audio.tags

    def read_bpm(self) -> int | None:
        """Read BPM from the ``bpm`` Vorbis comment field.

        Returns:
            Integer BPM, or None if absent or unparseable.
        """
        if self._audio and "bpm" in self._audio:
            try:
                return int(float(self._audio["bpm"][0]))
            except (ValueError, IndexError):
                pass
        return None

    def write_bpm(self, bpm: int) -> None:
        """Write BPM to the ``bpm`` Vorbis comment field and save.

        Args:
            bpm: Beats-per-minute value to store.
        """
        self._ensure_tags()
        self._audio["bpm"] = [str(bpm)]
        self.save()

    def read_key(self) -> str | None:
        """Read the musical key from the ``initialkey`` Vorbis comment field.

        Returns:
            Key string, or None if absent.
        """
        if self._audio and "initialkey" in self._audio:
            return str(self._audio["initialkey"][0])
        return None

    def write_key(self, key: str) -> None:
        """Write the musical key to the ``initialkey`` field and save.

        Args:
            key: Key string to store.
        """
        self._ensure_tags()
        self._audio["initialkey"] = [key]
        self.save()

    def read_tempo_marking(self) -> str | None:
        """Read the tempo marking from the ``tempo`` Vorbis comment field.

        Returns:
            Tempo marking string, or None if absent.
        """
        if self._audio and "tempo" in self._audio:
            return str(self._audio["tempo"][0])
        return None

    def write_tempo_marking(self, marking: str) -> None:
        """Write the tempo marking to the ``tempo`` field and save.

        Args:
            marking: Tempo label string to store.
        """
        self._ensure_tags()
        self._audio["tempo"] = [marking]
        self.save()

    def read_genre(self) -> str | None:
        """Read genre from the ``genre`` Vorbis comment field.

        Returns:
            Genre string, or None if absent.
        """
        if self._audio and "genre" in self._audio:
            return str(self._audio["genre"][0])
        return None

    def read_mood(self) -> str | None:
        """Read mood from the ``mood`` Vorbis comment field.

        Returns:
            Mood string, or None if absent.
        """
        if self._audio and "mood" in self._audio:
            return str(self._audio["mood"][0])
        if self._audio and "TMOO" in self._audio:
            return str(self._audio["TMOO"][0])
        return None

    def read_energy(self) -> str | None:
        """Read energy level from the ENERGYLEVEL or ENERGY field.

        Returns:
            Energy level string (e.g. ``'5'``), or None if absent.
        """
        if self._audio:
            for key in ("ENERGYLEVEL", "energylevel", "ENERGY", "energy"):
                if key in self._audio:
                    try:
                        return str(self._audio[key][0])
                    except (ValueError, IndexError):
                        pass
        return None

    def write_mood(self, mood: str) -> None:
        """Write mood to the ``mood`` Vorbis comment field and save.

        Args:
            mood: Mood string to store.
        """
        self._ensure_tags()
        self._audio["mood"] = [mood]
        self.save()

    def write_mood_confidence(self, confidence: str) -> None:
        """Write mood confidence to the ``MOODCONFIDENCE`` field and save.

        Args:
            confidence: Confidence value string (e.g. ``'0.87'``).
        """
        self._ensure_tags()
        self._audio["MOODCONFIDENCE"] = [confidence]
        self.save()

    def write_energy(self, energy: str) -> None:
        """Write energy level to the ``ENERGYLEVEL`` field and save.

        Args:
            energy: Energy band string (e.g. ``'5'``).
        """
        self._ensure_tags()
        self._audio["ENERGYLEVEL"] = [str(energy)]
        self.save()

    def write_genre(self, genre: str) -> None:
        """Write genre to the ``genre`` Vorbis comment field and save.

        Args:
            genre: Genre string to store.
        """
        self._ensure_tags()
        self._audio["genre"] = [genre]
        self.save()

    def embed_artwork(self, jpeg_bytes: bytes) -> None:
        """Embed JPEG cover art, replacing any existing artwork.

        FLAC uses ``mutagen.flac.Picture``; Ogg/Opus uses base64-encoded
        ``metadata_block_picture``.

        Args:
            jpeg_bytes: Raw JPEG image bytes.
        """
        ext = os.path.splitext(self.path)[1].lower()
        if ext == ".flac":
            from mutagen.flac import FLAC, Picture

            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.data = jpeg_bytes
            audio = FLAC(self.path)
            audio.clear_pictures()
            audio.add_picture(pic)
            audio.save()
            self._audio = audio
            self._tags = audio.tags
        else:
            import base64

            from mutagen.flac import Picture

            pic = Picture()
            pic.type = 3
            pic.mime = "image/jpeg"
            pic.data = jpeg_bytes
            encoded = base64.b64encode(pic.write()).decode("ascii")
            self._ensure_tags()
            self._audio["metadata_block_picture"] = [encoded]
            self.save()

    def extract_artwork(self) -> bytes | None:
        """Extract raw picture bytes from the file's embedded artwork.

        FLAC returns the first ``Picture`` block's data; Ogg/Opus base64-decode
        and parse the ``metadata_block_picture`` Vorbis comment field.

        Returns:
            Raw image bytes, or None if the file has no artwork or the stored
            artwork cannot be parsed.
        """
        import base64
        from io import BytesIO

        from mutagen.flac import Picture

        ext = os.path.splitext(self.path)[1].lower()
        if ext == ".flac":
            pictures = getattr(self._audio, "pictures", None) or []
            if not pictures:
                return None
            flac_data: bytes = pictures[0].data
            return flac_data
        if self._audio and "metadata_block_picture" in self._audio:
            try:
                raw = base64.b64decode(self._audio["metadata_block_picture"][0])
                picture = Picture()
                picture.load(BytesIO(raw))
                picture_data: bytes = picture.data
                return picture_data
            except Exception:
                logger.debug(
                    "Failed to parse artwork from %s", self.path, exc_info=True
                )
        return None

    def read_custom_genre_fields(self) -> dict[str, str | None]:
        """Read suite-specific custom genre fields from Vorbis comment fields.

        Returns:
            Dict mapping field names to values or None.
        """
        fields = (
            "titlegenre",
            "artistgenre",
            "albumgenre",
            "albumartistgenre",
            "genrederived",
        )
        result = {}
        for field in fields:
            key = field.upper()
            result[key] = (
                self._audio[field][0] if self._audio and field in self._audio else None
            )
        return result

    def write_genre_sync_result(self, genre: str, derived_value: str) -> None:
        """Write genre and GENREDERIVED Vorbis comment fields and save.

        Args:
            genre:         Genre string to store.
            derived_value: Value for the ``genrederived`` field.
        """
        self._ensure_tags()
        self._audio["genre"] = [genre]
        self._audio["genrederived"] = [derived_value]
        self.save()

    def write_album_genre_result(
        self, album_genre: str, derived_marker: str = "Y"
    ) -> None:
        """Write ALBUMGENRE and ALBUMDERIVED Vorbis comment fields and save.

        Args:
            album_genre: Consolidated, semicolon-separated genre string.
            derived_marker: Value for the ``ALBUMDERIVED`` field. Defaults
                to ``"Y"``.
        """
        self._ensure_tags()
        self._audio["ALBUMGENRE"] = [album_genre]
        self._audio["ALBUMDERIVED"] = [derived_marker]
        self.save()

    def read_artist_album(self) -> tuple[str, str]:
        """Read the ``artist`` and ``album`` Vorbis comment fields.

        Returns:
            Two-tuple ``(artist, album)``, defaulting to ``'Unknown'``.
        """
        artist = (
            self._audio["artist"][0]
            if self._audio and "artist" in self._audio
            else "Unknown"
        )
        album = (
            self._audio["album"][0]
            if self._audio and "album" in self._audio
            else "Unknown"
        )
        return artist, album

    def read_artist_title(self) -> tuple[str, str]:
        """Read the ``artist`` and ``title`` Vorbis comment fields.

        Returns:
            Two-tuple ``(artist, title)``, defaulting to ``'Unknown'``.
        """
        artist = (
            self._audio["artist"][0]
            if self._audio and "artist" in self._audio
            else "Unknown"
        )
        title = (
            self._audio["title"][0]
            if self._audio and "title" in self._audio
            else "Unknown"
        )
        return artist, title

    def read_album_artist(self) -> str | None:
        """Read the ``albumartist`` Vorbis comment field.

        Returns:
            Album artist string, or None if absent.
        """
        if self._audio and "albumartist" in self._audio:
            return str(self._audio["albumartist"][0])
        return None

    def has_artwork(self) -> bool:
        """Return True if FLAC picture blocks or an Ogg metadata block exist.

        Returns:
            True when the file carries embedded cover art.
        """
        ext = os.path.splitext(self.path)[1].lower()
        if ext == ".flac":
            return bool(getattr(self._audio, "pictures", None))
        return bool(self._audio) and "metadata_block_picture" in self._audio

    def read_replaygain(self) -> tuple[str | None, str | None]:
        """Read ReplayGain gains from Vorbis comment fields.

        Returns:
            Two-tuple ``(track_gain, album_gain)`` from the
            ``replaygain_track_gain`` and ``replaygain_album_gain`` fields,
            or None for each absent field.
        """
        track_gain = (
            str(self._audio["replaygain_track_gain"][0])
            if self._audio and "replaygain_track_gain" in self._audio
            else None
        )
        album_gain = (
            str(self._audio["replaygain_album_gain"][0])
            if self._audio and "replaygain_album_gain" in self._audio
            else None
        )
        return track_gain, album_gain

    def write_synced_lyrics(self, lrc_text: str) -> None:
        """Write LRC text to the ``SYNCEDLYRICS`` Vorbis comment and save.

        Plain unsynced lyrics stored in ``LYRICS`` are left untouched so both
        coexist.

        Args:
            lrc_text: LRC lyrics text to store verbatim.
        """
        self._ensure_tags()
        self._audio["syncedlyrics"] = [lrc_text]
        self.save()

    def read_synced_lyrics(self) -> str | None:
        """Return LRC text from the ``SYNCEDLYRICS`` Vorbis comment field.

        Falls back to the plain ``LYRICS`` field when no synced field exists
        (e.g. files tagged by older tools). Field lookup is case-insensitive
        per the Vorbis comment spec.

        Returns:
            LRC lyric text, or None if no lyric comment field is present.
        """
        if self._audio:
            for key in ("syncedlyrics", "lyrics"):
                if key in self._audio:
                    return str(self._audio[key][0])
        return None

    def read_lyrics_tags(self) -> LyricsTags:
        """Read the ``SYNCEDLYRICS`` and ``LYRICS`` Vorbis comment fields.

        Unlike :meth:`read_synced_lyrics`, the synced field does not fall
        back to the plain ``LYRICS`` field, so both can be reported
        independently. Field lookup is case-insensitive per the Vorbis
        comment spec.

        Returns:
            :class:`LyricsTags` with each field's text, or None per field.
        """
        synced: str | None = None
        plain: str | None = None
        if self._audio:
            if "syncedlyrics" in self._audio:
                synced = str(self._audio["syncedlyrics"][0])
            if "lyrics" in self._audio:
                plain = str(self._audio["lyrics"][0])
        return LyricsTags(synced=synced, plain=plain)

    def write_plain_lyrics(self, text: str) -> None:
        """Write plain lyrics to the ``LYRICS`` Vorbis comment and save.

        Synced lyrics stored in ``SYNCEDLYRICS`` are left untouched so both
        can coexist.

        Args:
            text: Plain lyric text to store.
        """
        self._ensure_tags()
        self._audio["lyrics"] = [text]
        self.save()

    def read_editable_tags(self) -> dict[str, str | None]:
        """Read the freeform editor fields from Vorbis comments.

        Returns:
            Dict mapping every field in ``EDITABLE_FIELDS`` to its string
            value, or ``None`` when the field is absent.
        """
        keys_by_field: dict[str, tuple[str, ...]] = {
            "title": ("title",),
            "artist": ("artist",),
            "album": ("album",),
            "album_artist": ("albumartist",),
            "track": ("tracknumber",),
            "year": ("date",),
            "genre": ("genre",),
            "comment": ("comment", "description"),
        }
        result = super().read_editable_tags()
        if self._audio:
            for field, keys in keys_by_field.items():
                for key in keys:
                    if key in self._audio:
                        try:
                            result[field] = str(self._audio[key][0])
                        except (IndexError, TypeError, ValueError):
                            result[field] = None
                        break
        return result

    def write_editable_tag(self, field: str, value: str | None) -> None:
        """Write or clear one freeform editor field in a Vorbis comment.

        Args:
            field: Canonical field name from ``EDITABLE_FIELDS``.
            value: String value to store, or ``None`` to remove the field.

        Raises:
            AudioTagError: If the field is not editable for Vorbis files.
        """
        keys_by_field: dict[str, tuple[str, ...]] = {
            "title": ("title",),
            "artist": ("artist",),
            "album": ("album",),
            "album_artist": ("albumartist",),
            "track": ("tracknumber",),
            "year": ("date",),
            "genre": ("genre",),
            "comment": ("comment", "description"),
        }
        keys = keys_by_field.get(field)
        if keys is None:
            raise AudioTagError(f"Unsupported editable tag field: {field}")

        self._ensure_tags()
        for key in keys:
            if key in self._audio:
                del self._audio[key]
        if value is not None:
            self._audio[keys[0]] = [value]
        self.save()

    def delete_tags(self) -> None:
        """Remove the Vorbis comment block and reload the audio file."""
        if self._audio is None:
            return
        self._audio.delete()
        self.load()

    def set_raw_tags(self, tags: Any) -> None:
        """Persist a raw mutagen tags object directly to the Vorbis file.

        mutagen FLAC serializes the Vorbis comment dict it captured into its
        metadata block list at load time, so rebinding ``self._audio.tags``
        to a different object silently drops the incoming data on save.
        Mutate the handler's own loaded comment dict in place instead so a
        foreign tags object (e.g. restored from another file) still persists.

        Args:
            tags: Mutagen tags object (or mapping) to save, or None (no-op).
        """
        if tags is None:
            return
        try:
            current = self._audio.tags
            if current is None:
                self._audio.tags = tags
            elif current is not tags:
                current.clear()
                current.update(tags)
            self.save()
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to save raw Vorbis tags to %s", self.path)
            raise


class MP4Handler(BaseTagHandler):
    """Handler for M4A/MP4 files using iTunes-style atoms."""

    def load(self) -> None:
        """Load the MP4/M4A file and its atom-based tags."""
        from mutagen.mp4 import MP4

        self._audio = MP4(self.path)
        self._tags = self._audio.tags

    def save(self) -> None:
        """Save MP4 atom tags back to the file."""
        if self._audio is not None:
            self._audio.save()

    def _ensure_tags(self) -> None:
        """Guarantee the MP4 tags dict exists, creating one if necessary."""
        if self._tags is None:
            self._audio.add_tags()
            self._tags = self._audio.tags

    def read_bpm(self) -> int | None:
        """Read BPM from the ``tmpo`` MP4 atom.

        Returns:
            Integer BPM, or None if absent.
        """
        if self._tags and "tmpo" in self._tags:
            try:
                return int(self._tags["tmpo"][0])
            except (ValueError, IndexError):
                pass
        return None

    def write_bpm(self, bpm: int) -> None:
        """Write BPM to the ``tmpo`` MP4 atom and save.

        Args:
            bpm: Beats-per-minute value to store.
        """
        self._ensure_tags()
        self._tags["tmpo"] = [bpm]
        self.save()

    def read_key(self) -> str | None:
        """Read the musical key from the ``----:com.apple.iTunes:initialkey`` atom.

        Returns:
            Key string, or None if absent.
        """
        if self._tags and "----:com.apple.iTunes:initialkey" in self._tags:
            try:
                return str(self._tags["----:com.apple.iTunes:initialkey"][0].decode())
            except (IndexError, AttributeError):
                pass
        return None

    def write_key(self, key: str) -> None:
        """Write the musical key to the iTunes ``initialkey`` atom and save.

        Args:
            key: Key string to store.
        """
        from mutagen.mp4 import MP4FreeForm

        self._ensure_tags()
        self._tags["----:com.apple.iTunes:initialkey"] = [MP4FreeForm(key.encode())]
        self.save()

    def read_tempo_marking(self) -> str | None:
        """Read the tempo marking from the iTunes ``TEMPO`` custom atom.

        Returns:
            Tempo marking string, or None if absent.
        """
        if self._tags and "----:com.apple.iTunes:TEMPO" in self._tags:
            try:
                return str(self._tags["----:com.apple.iTunes:TEMPO"][0].decode())
            except (IndexError, AttributeError):
                pass
        return None

    def write_tempo_marking(self, marking: str) -> None:
        """Write the tempo marking to the iTunes ``TEMPO`` custom atom and save.

        Args:
            marking: Tempo label string to store.
        """
        from mutagen.mp4 import MP4FreeForm

        self._ensure_tags()
        self._tags["----:com.apple.iTunes:TEMPO"] = [MP4FreeForm(marking.encode())]
        self.save()

    def read_genre(self) -> str | None:
        """Read genre from the ``\xa9gen`` MP4 atom.

        Returns:
            Genre string, or None if absent.
        """
        if self._tags and "\xa9gen" in self._tags:
            return str(self._tags["\xa9gen"][0])
        return None

    def read_mood(self) -> str | None:
        """Read mood from MP4 ``\xa9moo`` or ``mood`` atom.

        Returns:
            Mood string, or None if absent.
        """
        for key in ("\xa9moo", "mood"):
            if self._tags and key in self._tags:
                return str(self._tags[key][0])
        return None

    def read_energy(self) -> str | None:
        """Read energy level from MP4 ENERGYLEVEL or ENERGY freeform atom.

        Returns:
            Energy level string (e.g. ``'5'``), or None if absent.
        """
        if self._tags:
            for key in (
                "----:com.apple.iTunes:ENERGYLEVEL",
                "----:com.apple.iTunes:ENERGY",
            ):
                if key in self._tags:
                    try:
                        val = self._tags[key][0]
                        if hasattr(val, "decode"):
                            return str(val.decode())
                        return str(val)
                    except (IndexError, AttributeError):
                        pass
        return None

    def write_mood(self, mood: str) -> None:
        """Write mood to the ``\xa9moo`` MP4 atom and save.

        Args:
            mood: Mood string to store.
        """
        self._ensure_tags()
        self._tags["\xa9moo"] = [mood]
        self.save()

    def write_mood_confidence(self, confidence: str) -> None:
        """Write mood confidence to the MOOD_CONFIDENCE freeform atom and save.

        Args:
            confidence: Confidence value string (e.g. ``'0.87'``).
        """
        from mutagen.mp4 import MP4FreeForm

        self._ensure_tags()
        self._tags["----:com.apple.iTunes:MOOD_CONFIDENCE"] = [
            MP4FreeForm(confidence.encode())
        ]
        self.save()

    def write_energy(self, energy: str) -> None:
        """Write energy level to the ENERGYLEVEL freeform atom and save.

        Args:
            energy: Energy band string (e.g. ``'5'``).
        """
        from mutagen.mp4 import MP4FreeForm

        self._ensure_tags()
        self._tags["----:com.apple.iTunes:ENERGYLEVEL"] = [
            MP4FreeForm(str(energy).encode())
        ]
        self.save()

    def write_genre(self, genre: str) -> None:
        """Write genre to the ``\xa9gen`` MP4 atom and save.

        Args:
            genre: Genre string to store.
        """
        self._ensure_tags()
        self._tags["\xa9gen"] = [genre]
        self.save()

    def embed_artwork(self, jpeg_bytes: bytes) -> None:
        """Embed JPEG cover art in the ``covr`` MP4 atom, replacing existing art.

        Args:
            jpeg_bytes: Raw JPEG image bytes.
        """
        from mutagen.mp4 import MP4Cover

        self._ensure_tags()
        self._tags["covr"] = [MP4Cover(jpeg_bytes, imageformat=MP4Cover.FORMAT_JPEG)]
        self.save()

    def extract_artwork(self) -> bytes | None:
        """Extract raw picture bytes from the ``covr`` (cover art) atom.

        Returns:
            Raw image bytes from the first ``covr`` entry, or None if the
            file carries no cover art.
        """
        if not self._tags or "covr" not in self._tags:
            return None
        try:
            return bytes(self._tags["covr"][0])
        except (IndexError, TypeError, ValueError):
            return None

    def read_custom_genre_fields(self) -> dict[str, str | None]:
        """Read suite-specific custom genre fields from iTunes freeform atoms.

        Returns:
            Dict mapping field names to values or None.
        """
        fields = (
            "TITLEGENRE",
            "ARTISTGENRE",
            "ALBUMGENRE",
            "ALBUMARTISTGENRE",
            "GENREDERIVED",
        )
        result: dict[str, str | None] = {k: None for k in fields}
        if self._tags:
            for field in fields:
                atom_key = f"----:com.apple.iTunes:{field}"
                if atom_key in self._tags:
                    try:
                        result[field] = self._tags[atom_key][0].decode()
                    except (IndexError, AttributeError):
                        pass
        return result

    def write_genre_sync_result(self, genre: str, derived_value: str) -> None:
        """Write genre and GENREDERIVED iTunes freeform atoms and save.

        Args:
            genre:         Genre string for the ``\xa9gen`` atom.
            derived_value: Value for the ``GENREDERIVED`` freeform atom.
        """
        from mutagen.mp4 import MP4FreeForm

        self._ensure_tags()
        self._tags["\xa9gen"] = [genre]
        self._tags["----:com.apple.iTunes:GENREDERIVED"] = [
            MP4FreeForm(derived_value.encode())
        ]
        self.save()

    def write_album_genre_result(
        self, album_genre: str, derived_marker: str = "Y"
    ) -> None:
        """Write ALBUMGENRE and ALBUMDERIVED iTunes freeform atoms and save.

        Args:
            album_genre: Consolidated, semicolon-separated genre string.
            derived_marker: Value for the ``ALBUMDERIVED`` freeform atom.
                Defaults to ``"Y"``.
        """
        from mutagen.mp4 import MP4FreeForm

        self._ensure_tags()
        self._tags["----:com.apple.iTunes:ALBUMGENRE"] = [
            MP4FreeForm(album_genre.encode())
        ]
        self._tags["----:com.apple.iTunes:ALBUMDERIVED"] = [
            MP4FreeForm(derived_marker.encode())
        ]
        self.save()

    def read_artist_album(self) -> tuple[str, str]:
        """Read the ``\xa9ART`` (artist) and ``\xa9alb`` (album) MP4 atoms.

        Returns:
            Two-tuple ``(artist, album)``, defaulting to ``'Unknown'``.
        """
        artist = "Unknown"
        album = "Unknown"
        if self._tags:
            if "\xa9ART" in self._tags:
                artist = self._tags["\xa9ART"][0]
            if "\xa9alb" in self._tags:
                album = self._tags["\xa9alb"][0]
        return artist, album

    def read_artist_title(self) -> tuple[str, str]:
        """Read the ``\xa9ART`` (artist) and ``\xa9nam`` (title) MP4 atoms.

        Returns:
            Two-tuple ``(artist, title)``, defaulting to ``'Unknown'``.
        """
        artist = "Unknown"
        title = "Unknown"
        if self._tags:
            if "\xa9ART" in self._tags:
                artist = self._tags["\xa9ART"][0]
            if "\xa9nam" in self._tags:
                title = self._tags["\xa9nam"][0]
        return artist, title

    def read_album_artist(self) -> str | None:
        """Read the Album Artist from the ``aART`` MP4 atom.

        Returns:
            Album artist string, or None if absent.
        """
        if self._tags and "aART" in self._tags:
            return str(self._tags["aART"][0])
        return None

    def read_lyrics_tags(self) -> LyricsTags:
        """Read the ``\xa9lyr`` (lyrics) MP4 atom.

        M4A/MP4 store only plain lyrics; synced lyric text cannot be
        represented in a standard atom, so ``synced`` is always None.

        Returns:
            :class:`LyricsTags` with plain text from ``\xa9lyr``, or None.
        """
        plain: str | None = None
        if self._tags and "\xa9lyr" in self._tags:
            plain = str(self._tags["\xa9lyr"][0])
        return LyricsTags(synced=None, plain=plain)

    def write_plain_lyrics(self, text: str) -> None:
        """Embed plain lyrics in the ``\xa9lyr`` MP4 atom and save.

        Args:
            text: Plain lyric text to store.
        """
        self._ensure_tags()
        self._tags["\xa9lyr"] = [text]
        self.save()

    def has_artwork(self) -> bool:
        """Return True if a ``covr`` (cover art) atom is present.

        Returns:
            True when the MP4 tag container holds a ``covr`` atom.
        """
        return bool(self._tags) and "covr" in self._tags

    def read_replaygain(self) -> tuple[str | None, str | None]:
        """Read ReplayGain gains from iTunes ``replaygain_*`` freeform atoms.

        Returns:
            Two-tuple ``(track_gain, album_gain)`` read from the
            ``----:com.apple.iTunes:replaygain_track_gain`` and
            ``----:com.apple.iTunes:replaygain_album_gain`` atoms, or None
            for each absent value.
        """
        track_gain: str | None = None
        album_gain: str | None = None
        if self._tags:
            keys = {
                "replaygain_track_gain": "----:com.apple.iTunes:replaygain_track_gain",
                "replaygain_album_gain": "----:com.apple.iTunes:replaygain_album_gain",
            }
            for attr, key in keys.items():
                if key not in self._tags:
                    continue
                try:
                    value = str(self._tags[key][0].decode())
                except (IndexError, AttributeError):
                    value = None
                if attr == "replaygain_track_gain":
                    track_gain = value
                else:
                    album_gain = value
        return track_gain, album_gain

    def read_editable_tags(self) -> dict[str, str | None]:
        """Read the freeform editor fields from MP4 atoms.

        Returns:
            Dict mapping every field in ``EDITABLE_FIELDS`` to its string
            value, or ``None`` when the atom is absent.
        """
        keys_by_field: dict[str, str] = {
            "title": "\xa9nam",
            "artist": "\xa9ART",
            "album": "\xa9alb",
            "album_artist": "aART",
            "year": "\xa9day",
            "genre": "\xa9gen",
            "comment": "\xa9cmt",
        }
        result = super().read_editable_tags()
        if self._tags:
            for field, key in keys_by_field.items():
                if key in self._tags:
                    try:
                        result[field] = str(self._tags[key][0])
                    except (IndexError, TypeError, ValueError):
                        result[field] = None
            result["track"] = self._read_mp4_track()
        return result

    def write_editable_tag(self, field: str, value: str | None) -> None:
        """Write or clear one freeform editor field in an MP4 atom.

        Args:
            field: Canonical field name from ``EDITABLE_FIELDS``.
            value: String value to store, or ``None`` to remove the field.

        Raises:
            AudioTagError: If the field is not editable for MP4 files.
        """
        keys_by_field: dict[str, str] = {
            "title": "\xa9nam",
            "artist": "\xa9ART",
            "album": "\xa9alb",
            "album_artist": "aART",
            "year": "\xa9day",
            "genre": "\xa9gen",
            "comment": "\xa9cmt",
        }
        if field != "track" and field not in keys_by_field:
            raise AudioTagError(f"Unsupported editable tag field: {field}")

        self._ensure_tags()
        if field == "track":
            if "trkn" in self._tags:
                del self._tags["trkn"]
            if value is not None:
                track, total = self._parse_track_value(value)
                self._tags["trkn"] = [(track, total)]
        else:
            key = keys_by_field[field]
            if key in self._tags:
                del self._tags[key]
            if value is not None:
                self._tags[key] = [value]
        self.save()

    def delete_tags(self) -> None:
        """Remove the MP4 tag container and reload the audio file."""
        if self._audio is None:
            return
        self._audio.delete()
        self.load()

    def _read_mp4_track(self) -> str | None:
        """Read the track number atom as an editor string.

        Returns:
            ``"N"`` when no disc total is stored, ``"N/M"`` when both values
            are present, or ``None`` when the atom is absent.
        """
        if not self._tags or "trkn" not in self._tags:
            return None
        try:
            track, total = self._tags["trkn"][0]
            if total in (0, None):
                return str(track)
            return f"{track}/{total}"
        except (IndexError, TypeError, ValueError):
            return None

    def _parse_track_value(self, value: str) -> tuple[int, int]:
        """Parse an editor track value into an MP4 track tuple.

        Args:
            value: Track string in ``"N"`` or ``"N/M"`` form.

        Returns:
            Two-tuple ``(track, total)`` with zero for an absent total.

        Raises:
            AudioTagError: If the value cannot be parsed.
        """
        parts = value.split("/", 1)
        try:
            track = int(parts[0])
            total = int(parts[1]) if len(parts) == 2 else 0
        except ValueError as exc:
            raise AudioTagError(f"Invalid track value for MP4: {value}") from exc
        return track, total

    def set_raw_tags(self, tags: Any) -> None:
        """Persist a raw mutagen tags object directly to the MP4 file.

        Args:
            tags: Mutagen tags object to save, or None (no-op).
        """
        if tags is None:
            return
        try:
            self._audio.tags = tags
            self.save()
        except Exception:
            if logger.isEnabledFor(logging.DEBUG):
                logger.debug("Failed to save raw MP4 tags to %s", self.path)
            raise


class TagHandlerFactory:
    """Factory for obtaining the appropriate tag handler for a file."""

    _handlers: dict[str, type[BaseTagHandler]] = {
        ".mp3": MP3Handler,
        ".flac": VorbisHandler,
        ".ogg": VorbisHandler,
        ".opus": VorbisHandler,
        ".m4a": MP4Handler,
        ".mp4": MP4Handler,
        ".wav": IFFID3Handler,
        ".aiff": IFFID3Handler,
        ".aif": IFFID3Handler,
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
