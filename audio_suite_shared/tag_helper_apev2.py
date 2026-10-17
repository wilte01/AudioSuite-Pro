"""
tag_helper_apev2.py — WavPack / Monkey's Audio / Musepack (APEv2) tag handler.

The ``APEv2Handler`` implementation for the APEv2-tagged lossless formats
added by Sprint 1 of ``PLAN_feature_expansion.md`` item 1.1 (D15): ``.wv``
(WavPack), ``.ape`` (Monkey's Audio) and ``.mpc`` (Musepack).  All three
store tags in an APEv2 container (``mutagen.apev2``).

Import the public surface through ``audio_suite_shared.tag_helper_base``:
this module participates in the facade import cycle and must not be the
first tag-helper module imported in a fresh interpreter.

APEv2 value semantics (empirically pinned against mutagen 1.48, D20):
``tags[key]`` returns an ``APETextValue`` (a ``str`` subclass whose
``list()`` yields each ``\\x00``-separated value), so reads take
``list(tags[key])[0]`` — indexing the string itself would yield a single
*character*.  Cover art is the binary item ``Cover Art (Front)`` whose
``bytes()`` payload is ``filename\\x00jpegdata``.  APEv2 keys are matched
case-insensitively on lookup.

Changed in 1.1.0: new APEv2 tag handler for WavPack/APE/Musepack (.wv/.ape/.mpc).
Changed in 1.2.0: adds ``read_isrcs`` (the ``ISRC`` APEv2 item) for the Audio
Fingerprinter's ISRC retrieval (PLAN_feature_expansion.md D29).
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
# format modules keep sharing one logger and their records still reach the
# RotatingFileHandler attached to the "audio_suite" logger.
logger = logging.getLogger("audio_suite.audio_suite_shared.tag_helper_base")

_COVER_ART_KEY = "Cover Art (Front)"


class APEv2Handler(BaseTagHandler):
    """Handler for APEv2-tagged files: WavPack, Monkey's Audio, Musepack."""

    def load(self) -> None:
        """Load the audio file and its APEv2 tags.

        Selects ``mutagen.wavpack.WavPack`` for ``.wv`` files,
        ``mutagen.monkeysaudio.MonkeysAudio`` for ``.ape`` files and
        ``mutagen.musepack.Musepack`` for ``.mpc`` files, based on the
        file's extension.

        Raises:
            ValueError: If the file extension is not an APEv2 format.
        """
        import mutagen.monkeysaudio
        import mutagen.musepack
        import mutagen.wavpack

        ext = os.path.splitext(self.path)[1].lower()
        audio_cls: type[Any]
        if ext == ".wv":
            audio_cls = mutagen.wavpack.WavPack
        elif ext == ".ape":
            audio_cls = mutagen.monkeysaudio.MonkeysAudio
        elif ext == ".mpc":
            audio_cls = mutagen.musepack.Musepack
        else:
            raise AudioTagError(f"APEv2Handler cannot load extension: {ext}")

        self._audio = audio_cls(self.path)
        self._tags = self._audio.tags

    def save(self) -> None:
        """Save APEv2 tags back to the file."""
        if self._audio is not None:
            self._audio.save()

    def _ensure_tags(self) -> Any:
        """Guarantee an APEv2 tag container exists, creating one if necessary.

        Returns:
            The file's APEv2 tags object.
        """
        if self._tags is None:
            self._audio.add_tags()
            self._tags = self._audio.tags
        return self._tags

    def _read_text(self, *keys: str) -> str | None:
        """Return the first value of the first present APEv2 text item.

        Args:
            *keys: Candidate APEv2 key names, tried in order.

        Returns:
            The item's first value as a string, or None if absent.
        """
        if self._tags is None:
            return None
        for key in keys:
            if key in self._tags:
                try:
                    return str(list(self._tags[key])[0])
                except (IndexError, TypeError, ValueError):
                    return None
        return None

    def _write_text(self, key: str, value: str) -> None:
        """Write a single-value APEv2 text item and save.

        Args:
            key: APEv2 key name.
            value: Value to store.
        """
        tags = self._ensure_tags()
        tags[key] = value
        self.save()

    def read_bpm(self) -> int | None:
        """Read BPM from the ``BPM`` APEv2 item.

        Returns:
            Integer BPM, or None if absent or unparseable.
        """
        raw = self._read_text("BPM")
        if raw is not None:
            try:
                return int(float(raw))
            except ValueError:
                pass
        return None

    def write_bpm(self, bpm: int) -> None:
        """Write BPM to the ``BPM`` APEv2 item and save.

        Args:
            bpm: Beats-per-minute value to store.
        """
        self._write_text("BPM", str(bpm))

    def read_key(self) -> str | None:
        """Read the musical key from the ``INITIALKEY`` APEv2 item.

        Returns:
            Key string, or None if absent.
        """
        return self._read_text("INITIALKEY")

    def write_key(self, key: str) -> None:
        """Write the musical key to the ``INITIALKEY`` item and save.

        Args:
            key: Key string to store.
        """
        self._write_text("INITIALKEY", key)

    def read_tempo_marking(self) -> str | None:
        """Read the tempo marking from the ``TEMPO`` APEv2 item.

        Returns:
            Tempo marking string, or None if absent.
        """
        return self._read_text("TEMPO")

    def write_tempo_marking(self, marking: str) -> None:
        """Write the tempo marking to the ``TEMPO`` item and save.

        Args:
            marking: Tempo label string to store.
        """
        self._write_text("TEMPO", marking)

    def read_genre(self) -> str | None:
        """Read the genre from the ``GENRE`` APEv2 item.

        Returns:
            Genre string, or None if absent.
        """
        return self._read_text("GENRE")

    def write_genre(self, genre: str) -> None:
        """Write the genre to the ``GENRE`` item and save.

        Args:
            genre: Genre string to store.
        """
        self._write_text("GENRE", genre)

    def read_mood(self) -> str | None:
        """Read the mood from the ``MOOD`` (fallback ``TMOO``) APEv2 item.

        Returns:
            Mood string, or None if absent.
        """
        return self._read_text("MOOD", "TMOO")

    def write_mood(self, mood: str) -> None:
        """Write the mood to the ``MOOD`` item and save.

        Args:
            mood: Mood string to store.
        """
        self._write_text("MOOD", mood)

    def write_mood_confidence(self, confidence: str) -> None:
        """Write the mood confidence to the ``MOODCONFIDENCE`` item and save.

        Args:
            confidence: Confidence value string (e.g. ``'0.87'``).
        """
        self._write_text("MOODCONFIDENCE", confidence)

    def read_energy(self) -> str | None:
        """Read the energy level from ``ENERGYLEVEL`` (fallback ``ENERGY``).

        Returns:
            Energy level string (e.g. ``'5'``), or None if absent.
        """
        return self._read_text("ENERGYLEVEL", "ENERGY")

    def write_energy(self, energy: str) -> None:
        """Write the energy level to the ``ENERGYLEVEL`` item and save.

        Args:
            energy: Energy band string (e.g. ``'5'``).
        """
        self._write_text("ENERGYLEVEL", str(energy))

    def embed_artwork(self, jpeg_bytes: bytes) -> None:
        """Embed JPEG cover art as the ``Cover Art (Front)`` binary item.

        Replaces any existing cover art before saving.

        Args:
            jpeg_bytes: Raw JPEG image bytes.
        """
        from mutagen.apev2 import APEBinaryValue

        tags = self._ensure_tags()
        for key in list(tags.keys()):
            if key.lower() == _COVER_ART_KEY.lower():
                del tags[key]
        tags[_COVER_ART_KEY] = APEBinaryValue(b"cover.jpg\x00" + jpeg_bytes)
        self.save()

    def extract_artwork(self) -> bytes | None:
        """Extract raw picture bytes from the ``Cover Art (Front)`` item.

        Returns:
            Raw image bytes, or None if the file has no artwork.
        """
        if self._tags is None:
            return None
        for key in self._tags.keys():
            if key.lower() == _COVER_ART_KEY.lower():
                try:
                    _filename, _sep, data = bytes(self._tags[key]).partition(b"\x00")
                except Exception:
                    logger.debug(
                        "Failed to parse artwork from %s", self.path, exc_info=True
                    )
                    return None
                return data or None
        return None

    def has_artwork(self) -> bool:
        """Return True if a ``Cover Art (Front)`` binary item is present.

        Returns:
            True when the file carries embedded cover art.
        """
        if self._tags is None:
            return False
        return any(key.lower() == _COVER_ART_KEY.lower() for key in self._tags.keys())

    def read_custom_genre_fields(self) -> dict[str, str | None]:
        """Read suite-specific custom genre fields from APEv2 items.

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
        return {field: self._read_text(field) for field in fields}

    def write_genre_sync_result(self, genre: str, derived_value: str) -> None:
        """Write genre and GENREDERIVED APEv2 items and save.

        Args:
            genre:         Genre string to store.
            derived_value: Value for the ``GENREDERIVED`` item.
        """
        tags = self._ensure_tags()
        tags["GENRE"] = genre
        tags["GENREDERIVED"] = derived_value
        self.save()

    def write_album_genre_result(
        self, album_genre: str, derived_marker: str = "Y"
    ) -> None:
        """Write ALBUMGENRE and ALBUMDERIVED APEv2 items and save.

        Args:
            album_genre: Consolidated, semicolon-separated genre string.
            derived_marker: Value for the ``ALBUMDERIVED`` item. Defaults
                to ``"Y"``.
        """
        tags = self._ensure_tags()
        tags["ALBUMGENRE"] = album_genre
        tags["ALBUMDERIVED"] = derived_marker
        self.save()

    def read_artist_album(self) -> tuple[str, str]:
        """Read the ``ARTIST`` and ``ALBUM`` APEv2 items.

        Returns:
            Two-tuple ``(artist, album)``, defaulting to ``'Unknown'``.
        """
        return self._read_text("ARTIST") or "Unknown", (
            self._read_text("ALBUM") or "Unknown"
        )

    def read_artist_title(self) -> tuple[str, str]:
        """Read the ``ARTIST`` and ``TITLE`` APEv2 items.

        Returns:
            Two-tuple ``(artist, title)``, defaulting to ``'Unknown'``.
        """
        return self._read_text("ARTIST") or "Unknown", (
            self._read_text("TITLE") or "Unknown"
        )

    def read_album_artist(self) -> str | None:
        """Read the ``ALBUMARTIST`` APEv2 item.

        Returns:
            Album artist string, or None if absent.
        """
        return self._read_text("ALBUMARTIST")

    def read_custom_field(self, name: str) -> str | None:
        """Read one arbitrary APEv2 text item by its canonical name.

        Args:
            name: Canonical field name, e.g. ``'MUSICBRAINZ_ALBUMID'``.

        Returns:
            The item's first value as a string, or None if absent.
        """
        return self._read_text(name)

    def read_isrcs(self) -> tuple[str, ...]:
        """Read the ISRCs stored in the ``ISRC`` APEv2 item.

        An APEv2 item's value is an ``APETextValue`` — a ``str`` subclass whose
        ``list()`` yields each ``\\x00``-separated value — so multiple ISRCs
        are written as one item and read back here as a tuple.  Indexing the
        value directly would yield a single *character* (the pinned D20
        semantics), which is why this does not use the single-value reader.

        Returns:
            Every non-empty ISRC, deduplicated, in stored order.
        """
        if self._tags is None:
            return ()
        for key in self._tags.keys():
            if key.upper() != "ISRC":
                continue
            try:
                values = list(self._tags[key])
            except (TypeError, ValueError):
                return ()
            found: list[str] = []
            for value in values:
                text = str(value).strip()
                if text and text not in found:
                    found.append(text)
            return tuple(found)
        return ()

    def read_disc_number(self) -> str | None:
        """Read the disc number from the ``DISCNUMBER`` APEv2 item.

        Returns:
            The disc number string, or None if absent.
        """
        return self._read_text("DISCNUMBER")

    def read_replaygain(self) -> tuple[str | None, str | None]:
        """Read ReplayGain gains from the APEv2 items.

        Returns:
            Two-tuple ``(track_gain, album_gain)`` from the
            ``REPLAYGAIN_TRACK_GAIN`` and ``REPLAYGAIN_ALBUM_GAIN`` items,
            or None for each absent value.
        """
        return self._read_text("REPLAYGAIN_TRACK_GAIN"), self._read_text(
            "REPLAYGAIN_ALBUM_GAIN"
        )

    def read_synced_lyrics(self) -> str | None:
        """Return LRC text from the ``SYNCEDLYRICS`` (fallback ``LYRICS``) item.

        Returns:
            LRC lyric text, or None if no lyric item is present.
        """
        return self._read_text("SYNCEDLYRICS", "LYRICS")

    def read_lyrics_tags(self) -> LyricsTags:
        """Read the ``SYNCEDLYRICS`` and ``LYRICS`` APEv2 items.

        Unlike :meth:`read_synced_lyrics`, the synced item does not fall back
        to the plain ``LYRICS`` item, so both can be reported independently.

        Returns:
            :class:`LyricsTags` with each item's text, or None per field.
        """
        return LyricsTags(
            synced=self._read_text("SYNCEDLYRICS"),
            plain=self._read_text("LYRICS"),
        )

    def write_synced_lyrics(self, lrc_text: str) -> None:
        """Write LRC text to the ``SYNCEDLYRICS`` APEv2 item and save.

        Plain unsynced lyrics stored in ``LYRICS`` are left untouched so both
        coexist.

        Args:
            lrc_text: LRC lyrics text to store verbatim.
        """
        self._write_text("SYNCEDLYRICS", lrc_text)

    def write_plain_lyrics(self, text: str) -> None:
        """Write plain lyrics to the ``LYRICS`` APEv2 item and save.

        Synced lyrics stored in ``SYNCEDLYRICS`` are left untouched so both
        can coexist.

        Args:
            text: Plain lyric text to store.
        """
        self._write_text("LYRICS", text)

    _KEYS_BY_FIELD: dict[str, tuple[str, ...]] = {
        "title": ("TITLE",),
        "artist": ("ARTIST",),
        "album": ("ALBUM",),
        "album_artist": ("ALBUMARTIST",),
        "track": ("TRACK", "TRACKNUMBER"),
        "year": ("DATE", "YEAR"),
        "genre": ("GENRE",),
        "comment": ("COMMENT", "DESCRIPTION"),
    }

    def read_editable_tags(self) -> dict[str, str | None]:
        """Read the freeform editor fields from APEv2 items.

        Returns:
            Dict mapping every field in ``EDITABLE_FIELDS`` to its string
            value, or ``None`` when the field is absent.
        """
        result = super().read_editable_tags()
        for field, keys in self._KEYS_BY_FIELD.items():
            result[field] = self._read_text(*keys)
        return result

    def write_editable_tag(self, field: str, value: str | None) -> None:
        """Write or clear one freeform editor field in an APEv2 item.

        Args:
            field: Canonical field name from ``EDITABLE_FIELDS``.
            value: String value to store, or ``None`` to remove the field.

        Raises:
            AudioTagError: If the field is not editable for APEv2 files.
        """
        keys = self._KEYS_BY_FIELD.get(field)
        if keys is None:
            raise AudioTagError(f"Unsupported editable tag field: {field}")

        tags = self._ensure_tags()
        for key in keys:
            if key in tags:
                del tags[key]
        if value is not None:
            tags[keys[0]] = value
        self.save()

    def delete_tags(self) -> None:
        """Remove the APEv2 tag container and reload the audio file."""
        if self._audio is None:
            return
        self._audio.delete()
        self.load()

    def set_raw_tags(self, tags: Any) -> None:
        """Persist a raw APEv2 tags object directly to the file.

        Mirrors :meth:`VorbisHandler.set_raw_tags`: when the file already
        carries an APEv2 container, the incoming mapping is merged into the
        handler's own loaded container (``clear`` + ``update``) rather than
        rebound, so a foreign tags object still persists on save.

        Args:
            tags: APEv2 tags object (or mapping) to save, or None (no-op).
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
                logger.debug("Failed to save raw APEv2 tags to %s", self.path)
            raise
