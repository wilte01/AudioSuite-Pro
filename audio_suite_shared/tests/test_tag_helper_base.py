"""
tests/test_tag_helper_base.py
Unit tests for audio_suite_shared/tag_helper_base.py handler internals.

Unlike test_tag_helper.py (real-file round-trips via pydub/ffmpeg), these
tests exercise the in-memory error/fallback branches of each handler with
real mutagen containers or small fakes — no ffmpeg required:

* BaseTagHandler default method implementations
* MP3Handler: unparseable/empty ID3 frames, load() ID3 fallback,
  set_raw_tags save/reload/reraise paths
* IFFID3Handler: load() ID3 fallback for WAV
* VorbisHandler: opus/oggvorbis loads, _ensure_tags, bad bpm text, mood
  fields, set_raw_tags failure
* MP4Handler: _ensure_tags, unparseable atoms, freeform custom fields,
  artist/album/album-artist atoms, set_raw_tags paths

Run with:
    pytest tests/test_tag_helper_base.py -v

Changed in 1.1.0: updated the factory registry and public-name locks for the new tag
handlers.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from mutagen.id3 import (
    APIC,
    ID3,
    TALB,
    TBPM,
    TCON,
    TIT2,
    TKEY,
    TMOO,
    TPE1,
    TPE2,
    TXXX,
)

from audio_suite_shared.exceptions import AudioTagError
from audio_suite_shared.tag_helper_base import (
    BaseTagHandler,
    IFFID3Handler,
    MP3Handler,
    MP4Handler,
    VorbisHandler,
)

# The tag-helper subsystem logger, as named by the four format modules and by
# tag_helper_base itself (iteration-8 C8 re-parented it under "audio_suite").
_MODULE_LOGGER = "audio_suite.audio_suite_shared.tag_helper_base"


# ── Helpers ──────────────────────────────────────────────────────────────────


class _FakeVorbisAudio(dict):
    """Dict-backed stand-in for a mutagen Vorbis file (no ``tags`` attr)."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1


class _FakeMP4Audio:
    """Stand-in for a mutagen MP4 file with a creatable tags container."""

    def __init__(self) -> None:
        self.tags: dict[str, Any] = {}
        self.save_calls = 0

    def add_tags(self) -> None:
        self.tags = {}

    def save(self) -> None:
        self.save_calls += 1


def _mp3(tags: ID3 | None = None, audio: Any = None) -> MP3Handler:
    handler = MP3Handler("/fake/track.mp3")
    handler._tags = tags
    handler._audio = audio
    return handler


# ── BaseTagHandler defaults ──────────────────────────────────────────────────


class _StubHandler(BaseTagHandler):
    """Minimal concrete subclass so the ABC default methods can run."""

    def load(self) -> None:
        return None

    def save(self) -> None:
        return None

    def read_bpm(self) -> int | None:
        return None

    def write_bpm(self, bpm: int) -> None:
        return None

    def read_key(self) -> str | None:
        return None

    def write_key(self, key: str) -> None:
        return None

    def read_tempo_marking(self) -> str | None:
        return None

    def write_tempo_marking(self, marking: str) -> None:
        return None

    def read_genre(self) -> str | None:
        return None

    def write_genre(self, genre: str) -> None:
        return None

    def embed_artwork(self, jpeg_bytes: bytes) -> None:
        return None

    def extract_artwork(self) -> bytes | None:
        return None

    def read_custom_genre_fields(self) -> dict[str, str | None]:
        return {}

    def write_genre_sync_result(self, genre: str, derived_value: str) -> None:
        return None


class TestBaseTagHandlerDefaults:
    def test_read_artist_album_defaults_to_unknown(self) -> None:
        assert _StubHandler("/fake/x.mp3").read_artist_album() == (
            "Unknown",
            "Unknown",
        )

    def test_read_artist_title_defaults_to_unknown(self) -> None:
        assert _StubHandler("/fake/x.mp3").read_artist_title() == (
            "Unknown",
            "Unknown",
        )

    def test_read_album_artist_defaults_to_none(self) -> None:
        assert _StubHandler("/fake/x.mp3").read_album_artist() is None

    def test_read_mood_defaults_to_none(self) -> None:
        assert _StubHandler("/fake/x.mp3").read_mood() is None

    def test_read_energy_defaults_to_none(self) -> None:
        assert _StubHandler("/fake/x.mp3").read_energy() is None

    def test_write_energy_raises_not_supported(self) -> None:
        with pytest.raises(AudioTagError, match="write_energy is not supported"):
            _StubHandler("/fake/x.mp3").write_energy("5")

    def test_extract_artwork_defaults_to_none(self) -> None:
        assert _StubHandler("/fake/x.mp3").extract_artwork() is None

    def test_write_album_genre_result_raises_not_supported(self) -> None:
        with pytest.raises(
            AudioTagError, match="write_album_genre_result is not supported"
        ):
            _StubHandler("/fake/x.mp3").write_album_genre_result("Rock")

    def test_set_raw_tags_replaces_tags_without_saving(self) -> None:
        handler = _StubHandler("/fake/x.mp3")
        handler.set_raw_tags("SENTINEL")
        assert handler.get_raw_tags() == "SENTINEL"


# ── MP3Handler ───────────────────────────────────────────────────────────────


class TestMP3HandlerReads:
    def test_read_bpm_unparseable_text_returns_none(self) -> None:
        tags = ID3()
        tags.add(TBPM(encoding=3, text=["not-a-number"]))
        assert _mp3(tags).read_bpm() is None

    def test_read_key_empty_text_returns_none(self) -> None:
        tags = ID3()
        tags.add(TKEY(encoding=3, text=[]))
        assert _mp3(tags).read_key() is None

    def test_read_tempo_marking_other_txxx_returns_none(self) -> None:
        tags = ID3()
        tags.add(TXXX(encoding=3, desc="OTHER", text=["x"]))
        assert _mp3(tags).read_tempo_marking() is None

    def test_read_genre_empty_text_returns_none(self) -> None:
        tags = ID3()
        tags.add(TCON(encoding=3, text=[]))
        assert _mp3(tags).read_genre() is None

    def test_read_mood_present(self) -> None:
        tags = ID3()
        tags.add(TMOO(encoding=3, text=["Uplifting"]))
        assert _mp3(tags).read_mood() == "Uplifting"

    def test_read_mood_absent_returns_none(self) -> None:
        assert _mp3(ID3()).read_mood() is None

    def test_read_mood_empty_text_returns_none(self) -> None:
        tags = ID3()
        tags.add(TMOO(encoding=3, text=[]))
        assert _mp3(tags).read_mood() is None

    def test_read_energy_present(self) -> None:
        tags = ID3()
        tags.add(TXXX(encoding=3, desc="ENERGYLEVEL", text=["5"]))
        assert _mp3(tags).read_energy() == "5"

    def test_read_energy_fallback_energy(self) -> None:
        tags = ID3()
        tags.add(TXXX(encoding=3, desc="ENERGY", text=["4"]))
        assert _mp3(tags).read_energy() == "4"

    def test_read_energy_absent_returns_none(self) -> None:
        assert _mp3(ID3()).read_energy() is None

    def test_write_energy(self) -> None:
        tags = ID3()
        handler = _mp3(tags)
        handler.save = MagicMock()
        handler.write_energy("5")
        assert "TXXX:ENERGYLEVEL" in tags
        assert tags["TXXX:ENERGYLEVEL"].text == ["5"]
        handler.save.assert_called_once()

    def test_read_artist_album_from_frames(self) -> None:
        tags = ID3()
        tags.add(TPE1(encoding=3, text=["Artist"]))
        tags.add(TALB(encoding=3, text=["Album"]))
        assert _mp3(tags).read_artist_album() == ("Artist", "Album")

    def test_read_artist_album_empty_text_falls_back(self) -> None:
        tags = ID3()
        tags.add(TPE1(encoding=3, text=[]))
        tags.add(TALB(encoding=3, text=[]))
        assert _mp3(tags).read_artist_album() == ("Unknown", "Unknown")

    def test_read_artist_title_from_frames(self) -> None:
        tags = ID3()
        tags.add(TPE1(encoding=3, text=["Artist"]))
        tags.add(TIT2(encoding=3, text=["Title"]))
        assert _mp3(tags).read_artist_title() == ("Artist", "Title")

    def test_read_artist_title_missing_title_uses_unknown(self) -> None:
        tags = ID3()
        tags.add(TPE1(encoding=3, text=["Artist"]))
        assert _mp3(tags).read_artist_title() == ("Artist", "Unknown")

    def test_read_artist_title_empty_text_falls_back(self) -> None:
        tags = ID3()
        tags.add(TPE1(encoding=3, text=[]))
        tags.add(TIT2(encoding=3, text=[]))
        assert _mp3(tags).read_artist_title() == ("Unknown", "Unknown")

    def test_read_album_artist_present(self) -> None:
        tags = ID3()
        tags.add(TPE2(encoding=3, text=["Album Artist"]))
        assert _mp3(tags).read_album_artist() == "Album Artist"

    def test_read_album_artist_empty_text_returns_none(self) -> None:
        tags = ID3()
        tags.add(TPE2(encoding=3, text=[]))
        assert _mp3(tags).read_album_artist() is None

    def test_extract_artwork_returns_apic_data(self) -> None:
        tags = ID3()
        tags.add(
            APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=b"jpeg")
        )
        assert _mp3(tags).extract_artwork() == b"jpeg"

    def test_extract_artwork_none_without_apic(self) -> None:
        assert _mp3(ID3()).extract_artwork() is None

    def test_extract_artwork_none_without_tags(self) -> None:
        assert _mp3(None).extract_artwork() is None


class TestMP3HandlerLoadAndRaw:
    def test_load_falls_back_to_tagless_mp3(self) -> None:
        fake = SimpleNamespace(tags=ID3())
        with patch(
            "mutagen.mp3.MP3", side_effect=[Exception("bad ID3"), fake]
        ) as mock_mp3:
            handler = MP3Handler("/fake/track.mp3")
            handler.load()
        assert mock_mp3.call_count == 2
        assert handler._audio is fake
        assert handler._tags is fake.tags

    def test_set_raw_tags_none_is_noop(self) -> None:
        handler = _mp3(ID3())
        handler.set_raw_tags(None)
        assert isinstance(handler._tags, ID3)

    def test_set_raw_tags_saves_and_reloads(self) -> None:
        handler = _mp3(ID3())
        raw = MagicMock()
        with patch.object(MP3Handler, "load") as load_mock:
            handler.set_raw_tags(raw)
        raw.save.assert_called_once_with("/fake/track.mp3")
        load_mock.assert_called_once_with()

    def test_set_raw_tags_failure_logs_debug_and_reraises(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        handler = _mp3(ID3())
        raw = MagicMock()
        raw.save.side_effect = ValueError("boom")
        with caplog.at_level(logging.DEBUG, logger=_MODULE_LOGGER):
            with pytest.raises(ValueError, match="boom"):
                handler.set_raw_tags(raw)
        assert "Failed to save raw MP3 tags" in caplog.text


# ── IFFID3Handler ────────────────────────────────────────────────────────────


class TestIFFID3HandlerLoad:
    def test_load_wav_falls_back_when_id3_fails(self) -> None:
        fake = SimpleNamespace(tags=ID3())
        with patch(
            "mutagen.wave.WAVE", side_effect=[Exception("bad ID3"), fake]
        ) as mock_wave:
            handler = IFFID3Handler("/fake/track.wav")
            handler.load()
        assert mock_wave.call_count == 2
        assert handler._audio is fake
        assert handler._tags is fake.tags


# ── VorbisHandler ────────────────────────────────────────────────────────────


class TestVorbisHandlerLoad:
    def test_load_opus(self) -> None:
        fake = SimpleNamespace(tags={"genre": ["Rock"]})
        with patch("mutagen.oggopus.OggOpus", return_value=fake):
            handler = VorbisHandler("/fake/track.opus")
            handler.load()
        assert handler._audio is fake
        assert handler._tags == {"genre": ["Rock"]}

    def test_load_ogg_vorbis(self) -> None:
        fake = SimpleNamespace(tags={"genre": ["Rock"]})
        with patch("mutagen.oggvorbis.OggVorbis", return_value=fake):
            handler = VorbisHandler("/fake/track.ogg")
            handler.load()
        assert handler._audio is fake


class TestVorbisHandlerReadWrite:
    def test_ensure_tags_uses_audio_itself(self) -> None:
        audio = _FakeVorbisAudio()
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = audio
        handler._tags = None
        handler.write_bpm(128)
        assert audio["bpm"] == ["128"]
        assert audio.save_calls == 1

    def test_read_bpm_unparseable_returns_none(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"bpm": ["not-a-number"]})
        assert handler.read_bpm() is None

    def test_read_key_absent_returns_none(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"genre": ["Rock"]})
        assert handler.read_key() is None

    def test_read_artist_title_from_vorbis_fields(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"artist": ["10cc"], "title": ["Johnny"]})
        assert handler.read_artist_title() == ("10cc", "Johnny")

    def test_read_artist_title_absent_vorbis_fields(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"genre": ["Rock"]})
        assert handler.read_artist_title() == ("Unknown", "Unknown")

    def test_read_tempo_marking_absent_returns_none(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"genre": ["Rock"]})
        assert handler.read_tempo_marking() is None

    def test_read_genre_absent_returns_none(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"bpm": ["120"]})
        assert handler.read_genre() is None

    def test_read_album_artist_present(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"albumartist": ["Someone"]})
        assert handler.read_album_artist() == "Someone"

    def test_read_tempo_marking_present(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"tempo": ["Allegro"]})
        assert handler.read_tempo_marking() == "Allegro"

    def test_read_mood_from_mood_field(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"mood": ["Uplifting"]})
        assert handler.read_mood() == "Uplifting"

    def test_read_mood_falls_back_to_tmoo_field(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"TMOO": ["Calm"]})
        assert handler.read_mood() == "Calm"

    def test_read_energy_from_energylevel_field(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"ENERGYLEVEL": ["5"]})
        assert handler.read_energy() == "5"

    def test_read_energy_from_energy_field(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio({"energy": ["3"]})
        assert handler.read_energy() == "3"

    def test_read_energy_absent_returns_none(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio()
        assert handler.read_energy() is None

    def test_write_energy(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio()
        handler.write_energy("5")
        assert handler._audio["ENERGYLEVEL"] == ["5"]
        assert handler._audio.save_calls == 1

    def test_extract_artwork_flac_pictures(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = SimpleNamespace(pictures=[SimpleNamespace(data=b"jpeg")])
        assert handler.extract_artwork() == b"jpeg"

    def test_extract_artwork_flac_no_pictures_returns_none(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = SimpleNamespace(pictures=[])
        assert handler.extract_artwork() is None

    def test_extract_artwork_ogg_metadata_block(self) -> None:
        import base64

        from mutagen.flac import Picture

        pic = Picture()
        pic.type = 3
        pic.mime = "image/jpeg"
        pic.data = b"jpeg"
        encoded = base64.b64encode(pic.write()).decode("ascii")
        handler = VorbisHandler("/fake/track.ogg")
        handler._audio = _FakeVorbisAudio({"metadata_block_picture": [encoded]})
        assert handler.extract_artwork() == b"jpeg"

    def test_extract_artwork_ogg_malformed_returns_none(self) -> None:
        handler = VorbisHandler("/fake/track.ogg")
        handler._audio = _FakeVorbisAudio(
            {"metadata_block_picture": ["!!!not-base64!!!"]}
        )
        assert handler.extract_artwork() is None

    def test_extract_artwork_ogg_absent_returns_none(self) -> None:
        handler = VorbisHandler("/fake/track.ogg")
        handler._audio = _FakeVorbisAudio({"genre": ["Rock"]})
        assert handler.extract_artwork() is None

    def test_write_album_genre_result(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio()
        handler.write_album_genre_result("Jazz; Rock")
        assert handler._audio["ALBUMGENRE"] == ["Jazz; Rock"]
        assert handler._audio["ALBUMDERIVED"] == ["Y"]
        assert handler._audio.save_calls == 1

    def test_write_album_genre_result_custom_marker(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio()
        handler.write_album_genre_result("Pop", derived_marker="N")
        assert handler._audio["ALBUMDERIVED"] == ["N"]


class TestVorbisHandlerRaw:
    def test_set_raw_tags_none_is_noop(self) -> None:
        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _FakeVorbisAudio()
        handler.set_raw_tags(None)
        assert handler._audio.save_calls == 0

    def test_set_raw_tags_failure_reraises(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        class _Boom:
            tags: Any = None

            def save(self) -> None:
                raise ValueError("boom")

        handler = VorbisHandler("/fake/track.flac")
        handler._audio = _Boom()
        with caplog.at_level(logging.DEBUG, logger=_MODULE_LOGGER):
            with pytest.raises(ValueError, match="boom"):
                handler.set_raw_tags(SimpleNamespace())
        assert "Failed to save raw Vorbis tags" in caplog.text


# ── MP4Handler ───────────────────────────────────────────────────────────────


class TestMP4HandlerReadWrite:
    def test_write_bpm_creates_tags_container(self) -> None:
        audio = _FakeMP4Audio()
        handler = MP4Handler("/fake/track.m4a")
        handler._audio = audio
        handler._tags = None
        handler.write_bpm(120)
        assert audio.tags["tmpo"] == [120]
        assert audio.save_calls == 1

    def test_read_bpm_unparseable_returns_none(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"tmpo": ["not-a-number"]}
        assert handler.read_bpm() is None

    def test_read_key_undecodable_returns_none(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"----:com.apple.iTunes:initialkey": [object()]}
        assert handler.read_key() is None

    def test_read_key_empty_list_returns_none(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"----:com.apple.iTunes:initialkey": []}
        assert handler.read_key() is None

    def test_read_tempo_marking_undecodable_returns_none(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"----:com.apple.iTunes:TEMPO": [object()]}
        assert handler.read_tempo_marking() is None

    def test_read_genre_present(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"\xa9gen": ["Rock"]}
        assert handler.read_genre() == "Rock"

    def test_read_genre_absent_returns_none(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"tmpo": [120]}
        assert handler.read_genre() is None

    def test_read_mood_from_moo_atom(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"\xa9moo": ["Happy"]}
        assert handler.read_mood() == "Happy"

    def test_read_mood_from_mood_atom(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"mood": ["Calm"]}
        assert handler.read_mood() == "Calm"

    def test_read_energy_from_energylevel_atom(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"----:com.apple.iTunes:ENERGYLEVEL": [b"5"]}
        assert handler.read_energy() == "5"

    def test_read_energy_from_energy_atom(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"----:com.apple.iTunes:ENERGY": ["4"]}
        assert handler.read_energy() == "4"

    def test_read_energy_absent_returns_none(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {}
        assert handler.read_energy() is None

    def test_write_energy(self) -> None:
        audio = _FakeMP4Audio()
        handler = MP4Handler("/fake/track.m4a")
        handler._audio = audio
        handler._tags = audio.tags
        handler.write_energy("5")
        assert b"5" in bytes(handler._tags["----:com.apple.iTunes:ENERGYLEVEL"][0])
        assert audio.save_calls == 1

    def test_extract_artwork_returns_covr_bytes(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"covr": [b"jpeg"]}
        assert handler.extract_artwork() == b"jpeg"

    def test_extract_artwork_none_without_covr(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"tmpo": [120]}
        assert handler.extract_artwork() is None

    def test_extract_artwork_none_without_tags(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = None
        assert handler.extract_artwork() is None

    def test_extract_artwork_empty_covr_returns_none(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"covr": []}
        assert handler.extract_artwork() is None

    def test_write_album_genre_result(self) -> None:
        audio = _FakeMP4Audio()
        handler = MP4Handler("/fake/track.m4a")
        handler._audio = audio
        handler._tags = audio.tags
        handler.write_album_genre_result("Jazz; Rock")
        assert (
            bytes(handler._tags["----:com.apple.iTunes:ALBUMGENRE"][0]) == b"Jazz; Rock"
        )
        assert bytes(handler._tags["----:com.apple.iTunes:ALBUMDERIVED"][0]) == b"Y"
        assert audio.save_calls == 1

    def test_read_custom_genre_fields_decodes_freeform(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {
            "----:com.apple.iTunes:TITLEGENRE": [b"Rock"],
            "----:com.apple.iTunes:GENREDERIVED": [object()],
        }
        result = handler.read_custom_genre_fields()
        assert result["TITLEGENRE"] == "Rock"
        assert result["GENREDERIVED"] is None
        assert set(result) == {
            "TITLEGENRE",
            "ARTISTGENRE",
            "ALBUMGENRE",
            "ALBUMARTISTGENRE",
            "GENREDERIVED",
        }

    def test_read_artist_album_from_atoms(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"\xa9ART": ["Artist"], "\xa9alb": ["Album"]}
        assert handler.read_artist_album() == ("Artist", "Album")

    def test_read_artist_title_from_atoms(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"\xa9ART": ["10cc"], "\xa9nam": ["Johnny"]}
        assert handler.read_artist_title() == ("10cc", "Johnny")

    def test_read_artist_title_missing_title_atom(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"\xa9ART": ["10cc"]}
        assert handler.read_artist_title() == ("10cc", "Unknown")

    def test_read_album_artist_present(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._tags = {"aART": ["Album Artist"]}
        assert handler.read_album_artist() == "Album Artist"


class TestMP4HandlerRaw:
    def test_set_raw_tags_none_is_noop(self) -> None:
        handler = MP4Handler("/fake/track.m4a")
        handler._audio = _FakeMP4Audio()
        handler.set_raw_tags(None)
        assert handler._audio.save_calls == 0

    def test_set_raw_tags_assigns_and_saves(self) -> None:
        audio = _FakeMP4Audio()
        handler = MP4Handler("/fake/track.m4a")
        handler._audio = audio
        raw = SimpleNamespace()
        handler.set_raw_tags(raw)
        assert audio.tags is raw
        assert audio.save_calls == 1

    def test_set_raw_tags_failure_logs_debug_and_reraises(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        class _Boom:
            tags: Any = None

            def save(self) -> None:
                raise ValueError("boom")

        handler = MP4Handler("/fake/track.m4a")
        handler._audio = _Boom()
        with caplog.at_level(logging.DEBUG, logger=_MODULE_LOGGER):
            with pytest.raises(ValueError, match="boom"):
                handler.set_raw_tags(SimpleNamespace())
        assert "Failed to save raw MP4 tags" in caplog.text


# ── Facade surface (iteration-7 C2) ──────────────────────────────────────────


class TestFacadeSurface:
    """The facade re-exports the full public handler/factory surface."""

    _PRE_SPLIT_PUBLIC_NAMES: frozenset[str] = frozenset(
        {
            "APEv2Handler",
            "Any",
            "AudioFormatError",
            "AudioTagError",
            "BaseTagHandler",
            "Callable",
            "DSFID3Handler",
            "EDITABLE_FIELDS",
            "IFFID3Handler",
            "LyricsTags",
            "MP3Handler",
            "MP4Handler",
            "TYPE_CHECKING",
            "TagHandlerFactory",
            "Union",
            "VorbisHandler",
            "abc",
            "dataclass",
            "logger",
            "logging",
            "os",
        }
    )

    def test_public_name_set_is_preserved(self) -> None:
        """Every public name (pre-split + Sprint-1 handlers) is importable."""
        import audio_suite_shared.tag_helper_base as facade

        names = {n for n in dir(facade) if not n.startswith("_")}

        assert names == self._PRE_SPLIT_PUBLIC_NAMES

    def test_handler_reexports_are_the_real_classes(self) -> None:
        """The facade names bind to the per-format modules' real classes."""
        import audio_suite_shared.tag_helper_base as facade
        from audio_suite_shared import (
            tag_helper_iffid3,
            tag_helper_mp3,
            tag_helper_mp4,
            tag_helper_vorbis,
        )

        assert facade.MP3Handler is tag_helper_mp3.MP3Handler
        assert facade.IFFID3Handler is tag_helper_iffid3.IFFID3Handler
        assert facade.VorbisHandler is tag_helper_vorbis.VorbisHandler
        assert facade.MP4Handler is tag_helper_mp4.MP4Handler

        for handler_cls in (
            facade.MP3Handler,
            facade.IFFID3Handler,
            facade.VorbisHandler,
            facade.MP4Handler,
        ):
            assert issubclass(handler_cls, facade.BaseTagHandler)

    def test_factory_registry_maps_every_supported_extension(self) -> None:
        """The factory registers every extension in SUPPORTED_EXTENSIONS."""
        from audio_suite_shared.tag_helper_base import TagHandlerFactory

        assert set(TagHandlerFactory._handlers) == {
            ".mp3",
            ".flac",
            ".ogg",
            ".opus",
            ".m4a",
            ".mp4",
            ".wav",
            ".aiff",
            ".aif",
            ".spx",
            ".wv",
            ".ape",
            ".mpc",
            ".dsf",
        }
