"""
Tests for the tag-completeness read APIs in audio_suite_shared.

Covers the handlers added for the Tag Completeness Dashboard (gap 4.4):
    - BaseTagHandler.has_artwork() / read_replaygain() defaults
    - MP3Handler + inherited IFFID3Handler artwork + ReplayGain reads
    - VorbisHandler artwork + ReplayGain reads
    - MP4Handler artwork + ReplayGain reads
    - tag_helper_reader.has_artwork() / read_replaygain() facades

Artwork and ReplayGain reads are exercised via direct mutagen ID3 objects
(no file I/O) and mocked handler facades, so no ffmpeg is required.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from mutagen.id3 import APIC, ID3, TXXX

from audio_suite_shared.exceptions import AudioTagError
from audio_suite_shared.tag_helper import read_artist_title, read_replaygain
from audio_suite_shared.tag_helper_base import MP3Handler, MP4Handler, VorbisHandler
from audio_suite_shared.tag_helper_reader import has_artwork


def _id3_tags(*frames) -> ID3:
    tags = ID3()
    for frame in frames:
        tags.add(frame)
    return tags


def _apic_frame() -> APIC:
    return APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=b"jpeg")


def _txxx(desc: str, text: str) -> TXXX:
    return TXXX(encoding=3, desc=desc, text=[text])


def _bare_mp3(tags: ID3 | None) -> MP3Handler:
    handler = object.__new__(MP3Handler)
    handler.path = "track.mp3"
    handler._tags = tags
    return handler


def _bare_vorbis(path: str, audio) -> VorbisHandler:
    handler = object.__new__(VorbisHandler)
    handler.path = path
    handler._audio = audio
    return handler


def _bare_mp4(tags: dict | None) -> MP4Handler:
    handler = object.__new__(MP4Handler)
    handler.path = "track.m4a"
    handler._tags = tags
    return handler


# ── MP3 / IFFID3 ──────────────────────────────────────────────────────────────


class TestMP3Completeness:
    def test_base_defaults(self) -> None:
        from audio_suite_shared.tag_helper_base import BaseTagHandler

        class _Concrete(BaseTagHandler):
            def load(self) -> None:  # pragma: no cover - never invoked
                raise NotImplementedError

            def save(self) -> None:  # pragma: no cover - never invoked
                raise NotImplementedError

            def read_bpm(self) -> int | None:
                return None

            def write_bpm(self, bpm: int) -> None:
                raise NotImplementedError  # pragma: no cover

            def read_key(self) -> str | None:
                return None

            def write_key(self, key: str) -> None:
                raise NotImplementedError  # pragma: no cover

            def read_tempo_marking(self) -> str | None:
                return None

            def write_tempo_marking(self, marking: str) -> None:
                raise NotImplementedError  # pragma: no cover

            def read_genre(self) -> str | None:
                return None

            def write_genre(self, genre: str) -> None:
                raise NotImplementedError  # pragma: no cover

            def embed_artwork(self, jpeg_bytes: bytes) -> None:
                raise NotImplementedError  # pragma: no cover

            def extract_artwork(self) -> bytes | None:
                return None

            def read_custom_genre_fields(self) -> dict[str, str | None]:
                return {}

            def write_genre_sync_result(self, genre: str, derived_value: str) -> None:
                raise NotImplementedError  # pragma: no cover

        handler = object.__new__(_Concrete)
        assert handler.has_artwork() is False
        assert handler.read_replaygain() == (None, None)
        assert handler.extract_artwork() is None
        with pytest.raises(AudioTagError, match="write_album_genre_result"):
            handler.write_album_genre_result("Rock")

    def test_has_artwork_true_with_apic(self) -> None:
        assert _bare_mp3(_id3_tags(_apic_frame())).has_artwork() is True

    def test_has_artwork_false_without_apic(self) -> None:
        assert _bare_mp3(_id3_tags(_txxx("TEMPO", "Allegro"))).has_artwork() is False

    def test_has_artwork_false_without_tags(self) -> None:
        assert _bare_mp3(None).has_artwork() is False

    def test_replaygain_absent_returns_none_tuple(self) -> None:
        assert _bare_mp3(_id3_tags()).read_replaygain() == (None, None)

    def test_replaygain_reads_uppercase_frames(self) -> None:
        tags = _id3_tags(
            _txxx("REPLAYGAIN_TRACK_GAIN", "+0.50 dB"),
            _txxx("REPLAYGAIN_ALBUM_GAIN", "-0.10 dB"),
        )
        assert _bare_mp3(tags).read_replaygain() == ("+0.50 dB", "-0.10 dB")

    def test_replaygain_descriptions_match_case_insensitively(self) -> None:
        tags = _id3_tags(_txxx("replaygain_track_gain", "+1.00 dB"))
        assert _bare_mp3(tags).read_replaygain() == ("+1.00 dB", None)

    def test_iffid3_inherits_id3_artwork_and_replaygain(self) -> None:
        from audio_suite_shared.tag_helper_base import IFFID3Handler

        handler = object.__new__(IFFID3Handler)
        handler.path = "track.wav"
        handler._tags = _id3_tags(
            _apic_frame(), _txxx("REPLAYGAIN_ALBUM_GAIN", "-2.00 dB")
        )
        assert handler.has_artwork() is True
        assert handler.read_replaygain() == (None, "-2.00 dB")

    def test_extract_artwork_returns_apic_data(self) -> None:
        assert _bare_mp3(_id3_tags(_apic_frame())).extract_artwork() == b"jpeg"

    def test_extract_artwork_none_without_apic(self) -> None:
        assert _bare_mp3(_id3_tags(_txxx("TEMPO", "Allegro"))).extract_artwork() is None


# ── Vorbis (FLAC / OGG / Opus) ────────────────────────────────────────────────


class TestVorbisCompleteness:
    def test_flac_has_artwork_true_with_pictures(self) -> None:
        handler = _bare_vorbis("track.flac", SimpleNamespace(pictures=[b"jpeg"]))
        assert handler.has_artwork() is True

    def test_flac_has_artwork_false_without_pictures(self) -> None:
        handler = _bare_vorbis("track.flac", SimpleNamespace(pictures=[]))
        assert handler.has_artwork() is False

    def test_ogg_has_artwork_true_with_metadata_block(self) -> None:
        handler = _bare_vorbis("track.ogg", {"metadata_block_picture": ["base64-blob"]})
        assert handler.has_artwork() is True

    def test_ogg_has_artwork_false_without_picture_field(self) -> None:
        handler = _bare_vorbis("track.ogg", {"tempo": ["Allegro"]})
        assert handler.has_artwork() is False

    def test_replaygain_reads_vorbis_fields(self) -> None:
        handler = _bare_vorbis(
            "track.flac",
            {
                "replaygain_track_gain": ["+0.50 dB"],
                "replaygain_album_gain": ["-1.20 dB"],
            },
        )
        assert handler.read_replaygain() == ("+0.50 dB", "-1.20 dB")

    def test_replaygain_partial_fields(self) -> None:
        handler = _bare_vorbis("track.ogg", {"replaygain_track_gain": ["+0.10 dB"]})
        assert handler.read_replaygain() == ("+0.10 dB", None)

    def test_replaygain_absent_returns_none_tuple(self) -> None:
        assert _bare_vorbis("track.flac", {}).read_replaygain() == (None, None)

    def test_extract_artwork_flac_pictures(self) -> None:
        handler = _bare_vorbis(
            "track.flac", SimpleNamespace(pictures=[SimpleNamespace(data=b"jpeg")])
        )
        assert handler.extract_artwork() == b"jpeg"

    def test_extract_artwork_ogg_metadata_block(self) -> None:
        import base64

        from mutagen.flac import Picture

        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.data = b"jpeg"
        encoded = base64.b64encode(pic.write()).decode("ascii")
        handler = _bare_vorbis("track.ogg", {"metadata_block_picture": [encoded]})
        assert handler.extract_artwork() == b"jpeg"

    def test_extract_artwork_absent_returns_none(self) -> None:
        assert _bare_vorbis("track.flac", {}).extract_artwork() is None


# ── MP4 / M4A ─────────────────────────────────────────────────────────────────


class TestMP4Completeness:
    def test_has_artwork_true_with_covr(self) -> None:
        assert _bare_mp4({"covr": [object()]}).has_artwork() is True

    def test_has_artwork_false_without_covr(self) -> None:
        assert _bare_mp4({"\xa9gen": ["Rock"]}).has_artwork() is False

    def test_has_artwork_false_without_tags(self) -> None:
        assert _bare_mp4(None).has_artwork() is False

    def test_replaygain_reads_freeform_atoms(self) -> None:
        tags = {
            "----:com.apple.iTunes:replaygain_track_gain": [b"+1.20 dB"],
            "----:com.apple.iTunes:replaygain_album_gain": [b"-0.40 dB"],
        }
        assert _bare_mp4(tags).read_replaygain() == ("+1.20 dB", "-0.40 dB")

    def test_replaygain_undecodeable_atom_yields_none(self) -> None:
        tags = {"----:com.apple.iTunes:replaygain_track_gain": [object()]}
        assert _bare_mp4(tags).read_replaygain() == (None, None)

    def test_replaygain_absent_returns_none_tuple(self) -> None:
        assert _bare_mp4({}).read_replaygain() == (None, None)

    def test_extract_artwork_returns_covr_bytes(self) -> None:
        assert _bare_mp4({"covr": [b"jpeg"]}).extract_artwork() == b"jpeg"

    def test_extract_artwork_none_without_covr(self) -> None:
        assert _bare_mp4({"\xa9gen": ["Rock"]}).extract_artwork() is None


# ── Reader facades ────────────────────────────────────────────────────────────


class TestCompletenessFacades:
    def test_has_artwork_delegates_to_handler(self) -> None:
        handler = MagicMock()
        handler.has_artwork.return_value = True
        with patch(
            "audio_suite_shared.tag_helper_reader.TagHandlerFactory.get_handler",
            return_value=handler,
        ) as mock_factory:
            assert has_artwork("song.mp3") is True
        mock_factory.assert_called_once_with("song.mp3")

    def test_has_artwork_returns_false_on_read_error(self) -> None:
        with patch(
            "audio_suite_shared.tag_helper_reader.TagHandlerFactory.get_handler",
            side_effect=OSError("locked"),
        ):
            assert has_artwork("song.mp3") is False

    def test_read_replaygain_delegates_to_handler(self) -> None:
        handler = MagicMock()
        handler.read_replaygain.return_value = ("+0.50 dB", "-0.10 dB")
        with patch(
            "audio_suite_shared.tag_helper_reader.TagHandlerFactory.get_handler",
            return_value=handler,
        ) as mock_factory:
            assert read_replaygain("song.flac") == ("+0.50 dB", "-0.10 dB")
        mock_factory.assert_called_once_with("song.flac")

    def test_read_replaygain_returns_none_tuple_on_error(self) -> None:
        with patch(
            "audio_suite_shared.tag_helper_reader.TagHandlerFactory.get_handler",
            side_effect=OSError("locked"),
        ):
            assert read_replaygain("song.mp3") == (None, None)

    def test_read_artist_title_delegates_to_handler(self) -> None:
        handler = MagicMock()
        handler.read_artist_title.return_value = ("10cc", "Johnny")
        with patch(
            "audio_suite_shared.tag_helper_reader.TagHandlerFactory.get_handler",
            return_value=handler,
        ) as mock_factory:
            assert read_artist_title("song.mp3") == ("10cc", "Johnny")
        mock_factory.assert_called_once_with("song.mp3")

    def test_read_artist_title_returns_unknown_on_error(self) -> None:
        with patch(
            "audio_suite_shared.tag_helper_reader.TagHandlerFactory.get_handler",
            side_effect=OSError("locked"),
        ):
            assert read_artist_title("song.mp3") == ("Unknown", "Unknown")

    def test_handlers_registered_for_all_supported_formats(self) -> None:
        from audio_suite_shared.tag_helper_base import TagHandlerFactory

        for ext in (".mp3", ".flac", ".ogg", ".opus", ".m4a", ".mp4", ".wav", ".aiff"):
            handler_cls = TagHandlerFactory._handlers[ext]
            assert hasattr(handler_cls, "has_artwork")
            assert hasattr(handler_cls, "read_replaygain")
            assert hasattr(handler_cls, "read_artist_title")
            assert hasattr(handler_cls, "extract_artwork")
            assert hasattr(handler_cls, "write_album_genre_result")
