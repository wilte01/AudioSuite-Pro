"""
tag_helper_mp4.py — M4A / MP4 (iTunes atom) tag handler.

The ``MP4Handler`` implementation, relocated verbatim from
``tag_helper_base.py`` by iteration-7 C2 (plan-governed god-file split).
Import the public surface through ``audio_suite_shared.tag_helper_base``:
this module participates in the facade import cycle and must not be the
first tag-helper module imported in a fresh interpreter.
"""

import logging
from typing import Any

from .exceptions import AudioTagError
from .tag_helper_base import BaseTagHandler, LyricsTags

# Emit through the tag-helper subsystem logger: the logger name is part of
# the module's observable behaviour (pinned by the test suite's caplog
# filters) and must survive the per-format module split unchanged.
logger = logging.getLogger("audio_suite_shared.tag_helper_base")


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

    def read_custom_field(self, name: str) -> str | None:
        """Read one custom tag from its iTunes freeform atom.

        Args:
            name: Canonical field name, e.g. ``'MUSICBRAINZ_ALBUMID'``.

        Returns:
            The atom's decoded value as a string, or None if absent or empty.
        """
        if not self._tags:
            return None
        key = f"----:com.apple.iTunes:{name}"
        if key not in self._tags:
            return None
        try:
            return str(self._tags[key][0].decode())
        except (IndexError, AttributeError, UnicodeDecodeError):
            return None

    def read_disc_number(self) -> str | None:
        """Read the disc number from the ``disk`` MP4 atom.

        MP4 stores the disc as a ``(disc, total)`` tuple; the total is not
        part of the disc number and is dropped.

        Returns:
            The disc number string, or None if absent or unreadable.
        """
        if self._tags and "disk" in self._tags:
            try:
                value = self._tags["disk"][0]
                if isinstance(value, tuple) and value:
                    return str(value[0])
                return str(value)
            except (IndexError, TypeError):
                return None
        return None

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
