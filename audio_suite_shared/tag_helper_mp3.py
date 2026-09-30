"""
tag_helper_mp3.py — MP3 (ID3) tag handler.

The ``MP3Handler`` implementation, relocated verbatim from
``tag_helper_base.py`` by iteration-7 C2 (plan-governed god-file split).
Import the public surface through ``audio_suite_shared.tag_helper_base``:
this module participates in the facade import cycle and must not be the
first tag-helper module imported in a fresh interpreter.
"""

import logging
from collections.abc import Callable
from typing import Any

from .exceptions import AudioTagError
from .tag_helper_base import BaseTagHandler, LyricsTags

# Emit through the tag-helper subsystem logger: the logger name is part of
# the module's observable behaviour (pinned by the test suite's caplog
# filters) and must survive the per-format module split unchanged.
logger = logging.getLogger("audio_suite_shared.tag_helper_base")


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
