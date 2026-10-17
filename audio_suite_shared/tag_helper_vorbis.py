"""
tag_helper_vorbis.py — FLAC / Ogg Vorbis / Opus / Speex tag handler.

The ``VorbisHandler`` implementation, relocated verbatim from
``tag_helper_base.py`` by iteration-7 C2 (plan-governed god-file split).
Speex (``.spx``) support was added by Sprint 1 of
``PLAN_feature_expansion.md`` item 1.1 (D15): ``mutagen.oggspeex.OggSpeex``
exposes the same Vorbis-comment tag surface as ``OggVorbis`` (verified in
D20), so it shares this handler with only a new ``load()`` branch.
Import the public surface through ``audio_suite_shared.tag_helper_base``:
this module participates in the facade import cycle and must not be the
first tag-helper module imported in a fresh interpreter.

Changed in 1.1.0: adds an Ogg Speex (.spx) load branch to the Vorbis handler.
Changed in 1.2.0: adds ``read_isrcs`` (the ``ISRC`` Vorbis comment) for the
Audio Fingerprinter's ISRC retrieval (PLAN_feature_expansion.md D29).
"""

import logging
import os
from typing import Any

from .exceptions import AudioTagError
from .tag_helper_base import BaseTagHandler, LyricsTags

# Emit through the tag-helper subsystem logger: the logger name is part of
# the module's observable behaviour (pinned by the test suite's caplog
# filters) and must survive the per-format module split unchanged. The name
# tracks tag_helper_base's own namespaced logger (iteration-8 C8), so all
# four format modules keep sharing one logger and their records still reach
# the RotatingFileHandler attached to the "audio_suite" logger.
logger = logging.getLogger("audio_suite.audio_suite_shared.tag_helper_base")


class VorbisHandler(BaseTagHandler):
    """Handler for Vorbis-comment files: FLAC, OGG, Opus, and Speex."""

    def load(self) -> None:
        """Load the audio file and its Vorbis comment tags."""
        ext = os.path.splitext(self.path)[1].lower()
        if ext == ".flac":
            from mutagen.flac import FLAC

            self._audio = FLAC(self.path)
        elif ext == ".opus":
            from mutagen.oggopus import OggOpus

            self._audio = OggOpus(self.path)
        elif ext == ".spx":
            from mutagen.oggspeex import OggSpeex

            self._audio = OggSpeex(self.path)
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

    def read_custom_field(self, name: str) -> str | None:
        """Read one custom tag from the Vorbis comments.

        Args:
            name: Canonical field name, e.g. ``'MUSICBRAINZ_ALBUMID'``.

        Returns:
            The comment's first value as a string, or None if absent or empty.
        """
        if self._audio and name in self._audio:
            values = self._audio[name]
            if values:
                return str(values[0])
        return None

    def read_isrcs(self) -> tuple[str, ...]:
        """Read the ISRCs stored in the ``ISRC`` Vorbis comment.

        Vorbis comment keys are matched case-insensitively by mutagen, so the
        comment is found however the tagging application cased it, and every
        value of the comment is returned (a recording may carry several).

        Returns:
            Every non-empty ISRC, deduplicated, in stored order.
        """
        if self._audio is None:
            return ()
        if "ISRC" not in self._audio:
            return ()
        found: list[str] = []
        for value in self._audio["ISRC"]:
            text = str(value).strip()
            if text and text not in found:
                found.append(text)
        return tuple(found)

    def read_disc_number(self) -> str | None:
        """Read the disc number from the ``discnumber`` Vorbis comment.

        Returns:
            The disc number string, or None if absent.
        """
        if self._audio and "discnumber" in self._audio:
            values = self._audio["discnumber"]
            if values:
                return str(values[0])
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
