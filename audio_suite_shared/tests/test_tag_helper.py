"""
Tests for audio_suite_shared.tag_helper
Gap G-23: MP3Handler, VorbisHandler, MP4Handler, TagHandlerFactory,
          and all module-level facade functions.

Fixtures: real minimal audio files created via pydub (requires ffmpeg).
Marked with 'integration' so they can be skipped in environments without ffmpeg.
"""

import os

import pytest

from audio_suite_shared.exceptions import AudioFormatError

try:
    from pydub import AudioSegment

    PYDUB_AVAILABLE = True
except ImportError:
    PYDUB_AVAILABLE = False

from mutagen.flac import FLAC

from audio_suite_shared.tag_helper import (
    IFFID3Handler,
    MP3Handler,
    MP4Handler,
    TagHandlerFactory,
    VorbisHandler,
    is_supported,
    read_album_artist,
    read_artist_album,
    read_bpm,
    read_custom_genre_fields,
    read_genre,
    read_key,
    read_tags_raw,
    read_tempo_marking,
    write_album_genre_result,
    write_bpm,
    write_genre,
    write_genre_sync_result,
    write_key,
    write_tempo_marking,
)

pytestmark = pytest.mark.integration


def _silent(duration_ms: int = 100) -> "AudioSegment":
    return AudioSegment.silent(duration=duration_ms)


@pytest.fixture
def mp3_file(tmp_path):
    path = tmp_path / "test.mp3"
    _silent().export(str(path), format="mp3")
    return str(path)


@pytest.fixture
def flac_file(tmp_path):
    path = tmp_path / "test.flac"
    _silent().export(str(path), format="flac")
    return str(path)


@pytest.fixture
def ogg_file(tmp_path):
    path = tmp_path / "test.ogg"
    _silent().export(str(path), format="ogg")
    return str(path)


@pytest.fixture
def m4a_file(tmp_path):
    path = tmp_path / "test.m4a"
    _silent().export(str(path), format="mp4")
    return str(path)


@pytest.fixture
def mp4_file(tmp_path):
    path = tmp_path / "test.mp4"
    _silent().export(str(path), format="mp4")
    return str(path)


@pytest.fixture
def opus_file(tmp_path):
    path = tmp_path / "test.opus"
    _silent().export(str(path), format="opus")
    return str(path)


@pytest.fixture
def wav_file(tmp_path):
    path = tmp_path / "test.wav"
    _silent().export(str(path), format="wav")
    return str(path)


@pytest.fixture
def aiff_file(tmp_path):
    path = tmp_path / "test.aiff"
    _silent().export(str(path), format="aiff")
    return str(path)


# ── is_supported ──────────────────────────────────────────────────────────────


class TestIsSupported:
    @pytest.mark.parametrize(
        "filename",
        [
            "track.mp3",
            "song.flac",
            "audio.ogg",
            "music.m4a",
            "podcast.opus",
            "sample.wav",
            "recording.aiff",
            "recording.aif",
        ],
    )
    def test_supported_formats(self, filename):
        assert is_supported(filename) is True

    @pytest.mark.parametrize("filename", ["doc.pdf", "image.jpg", ""])
    def test_unsupported_formats(self, filename):
        assert is_supported(filename) is False


# ── TagHandlerFactory ─────────────────────────────────────────────────────────


class TestTagHandlerFactory:
    def test_mp3_returns_mp3handler(self, mp3_file):
        h = TagHandlerFactory.get_handler(mp3_file)
        assert isinstance(h, MP3Handler)

    def test_flac_returns_vorbis_handler(self, flac_file):
        h = TagHandlerFactory.get_handler(flac_file)
        assert isinstance(h, VorbisHandler)

    def test_ogg_returns_vorbis_handler(self, ogg_file):
        h = TagHandlerFactory.get_handler(ogg_file)
        assert isinstance(h, VorbisHandler)

    def test_m4a_returns_mp4handler(self, m4a_file):
        h = TagHandlerFactory.get_handler(m4a_file)
        assert isinstance(h, MP4Handler)

    def test_wav_returns_iffid3handler(self, wav_file):
        h = TagHandlerFactory.get_handler(wav_file)
        assert isinstance(h, IFFID3Handler)

    def test_aiff_returns_iffid3handler(self, aiff_file):
        h = TagHandlerFactory.get_handler(aiff_file)
        assert isinstance(h, IFFID3Handler)

    def test_aif_short_extension_returns_iffid3handler(self, aiff_file, tmp_path):
        # Rename to the short .aif extension and confirm dispatch still works
        short_path = tmp_path / "test.aif"
        os.replace(aiff_file, short_path)
        h = TagHandlerFactory.get_handler(str(short_path))
        assert isinstance(h, IFFID3Handler)

    def test_unsupported_extension_raises(self, tmp_path):
        bad = tmp_path / "file.xyz"
        bad.write_bytes(b"x")
        with pytest.raises(AudioFormatError, match="[Uu]nsupported"):
            TagHandlerFactory.get_handler(str(bad))

    def test_handler_is_loaded_after_get(self, mp3_file):
        h = TagHandlerFactory.get_handler(mp3_file)
        # If load() was called, _audio should not be None
        assert h._audio is not None


# ── MP3Handler ────────────────────────────────────────────────────────────────


class TestMP3Handler:
    def test_bpm_round_trip(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_bpm(128)
        h2 = MP3Handler(mp3_file)
        h2.load()
        assert h2.read_bpm() == 128

    def test_bpm_returns_none_when_absent(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        assert h.read_bpm() is None

    def test_key_round_trip(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_key("Am")
        h2 = MP3Handler(mp3_file)
        h2.load()
        assert h2.read_key() == "Am"

    def test_key_returns_none_when_absent(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        assert h.read_key() is None

    def test_tempo_marking_round_trip(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_tempo_marking("Allegro")
        h2 = MP3Handler(mp3_file)
        h2.load()
        assert h2.read_tempo_marking() == "Allegro"

    def test_genre_round_trip(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_genre("Electronic")
        h2 = MP3Handler(mp3_file)
        h2.load()
        assert h2.read_genre() == "Electronic"

    def test_genre_returns_none_when_absent(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        assert h.read_genre() is None

    def test_multiple_tags_independent(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_bpm(140)
        h.write_key("C#m")
        h.write_genre("House")
        h2 = MP3Handler(mp3_file)
        h2.load()
        assert h2.read_bpm() == 140
        assert h2.read_key() == "C#m"
        assert h2.read_genre() == "House"

    def test_overwrite_bpm(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_bpm(120)
        h.write_bpm(160)
        h2 = MP3Handler(mp3_file)
        h2.load()
        assert h2.read_bpm() == 160

    def test_custom_genre_fields_returns_dict(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        fields = h.read_custom_genre_fields()
        assert isinstance(fields, dict)
        assert "TITLEGENRE" in fields
        assert "GENREDERIVED" in fields

    def test_custom_genre_fields_all_none_initially(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        fields = h.read_custom_genre_fields()
        assert all(v is None for v in fields.values())

    def test_write_genre_sync_result(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_genre_sync_result("Rock", "derived_rock")
        h2 = MP3Handler(mp3_file)
        h2.load()
        assert h2.read_genre() == "Rock"

    def test_write_album_genre_result_default_marker(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_album_genre_result("Jazz; Rock")
        h2 = MP3Handler(mp3_file)
        h2.load()
        fields = h2.read_custom_genre_fields()
        assert fields["ALBUMGENRE"] == "Jazz; Rock"

    def test_write_album_genre_result_custom_marker(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_album_genre_result("Pop", derived_marker="N")
        h2 = MP3Handler(mp3_file)
        h2.load()
        # ALBUMDERIVED isn't one of read_custom_genre_fields' tracked keys,
        # so read the raw TXXX frame directly.
        frame = h2.get_raw_tags().get("TXXX:ALBUMDERIVED")
        assert frame is not None
        assert frame.text[0] == "N"

    def test_write_album_genre_result_overwrites_existing(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_album_genre_result("Old Genre")
        h.write_album_genre_result("New Genre")
        h2 = MP3Handler(mp3_file)
        h2.load()
        fields = h2.read_custom_genre_fields()
        assert fields["ALBUMGENRE"] == "New Genre"
        frame = h2.get_raw_tags().getall("TXXX:ALBUMGENRE")
        assert len(frame) == 1  # delall ran before add — no duplicate frames

    def test_embed_artwork(self, mp3_file, tmp_path):
        # Minimal 1x1 JPEG (valid JFIF header)
        jpeg = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
            b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
            b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e\xd0"
            b"\xff\xd9"
        )
        h = MP3Handler(mp3_file)
        h.load()
        h.embed_artwork(jpeg)  # must not raise

    def test_read_artist_album_defaults(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        artist, album = h.read_artist_album()
        # May return "Unknown" or empty string for a blank file
        assert isinstance(artist, str)
        assert isinstance(album, str)

    def test_get_raw_tags_returns_tags_after_write(self, mp3_file):
        h = MP3Handler(mp3_file)
        h.load()
        h.write_bpm(99)
        raw = h.get_raw_tags()
        assert raw is not None


# ── IFFID3Handler (WAV, AIFF) ─────────────────────────────────────────────────
# WAV and AIFF both embed mutagen.id3.ID3 tags, so IFFID3Handler inherits all
# read/write logic from MP3Handler. These tests mirror TestMP3Handler exactly,
# parametrized over both formats via the iff_file fixture below.


@pytest.fixture(params=["wav", "aiff"])
def iff_file(request, wav_file, aiff_file):
    """Yields wav_file for one test run and aiff_file for another."""
    return wav_file if request.param == "wav" else aiff_file


class TestIFFID3Handler:
    def test_bpm_round_trip(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        h.write_bpm(128)
        h2 = IFFID3Handler(iff_file)
        h2.load()
        assert h2.read_bpm() == 128

    def test_bpm_returns_none_when_absent(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        assert h.read_bpm() is None

    def test_key_round_trip(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        h.write_key("Am")
        h2 = IFFID3Handler(iff_file)
        h2.load()
        assert h2.read_key() == "Am"

    def test_key_returns_none_when_absent(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        assert h.read_key() is None

    def test_tempo_marking_round_trip(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        h.write_tempo_marking("Allegro")
        h2 = IFFID3Handler(iff_file)
        h2.load()
        assert h2.read_tempo_marking() == "Allegro"

    def test_genre_round_trip(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        h.write_genre("Electronic")
        h2 = IFFID3Handler(iff_file)
        h2.load()
        assert h2.read_genre() == "Electronic"

    def test_genre_returns_none_when_absent(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        assert h.read_genre() is None

    def test_multiple_tags_independent(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        h.write_bpm(140)
        h.write_key("C#m")
        h.write_genre("House")
        h2 = IFFID3Handler(iff_file)
        h2.load()
        assert h2.read_bpm() == 140
        assert h2.read_key() == "C#m"
        assert h2.read_genre() == "House"

    def test_overwrite_bpm(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        h.write_bpm(120)
        h.write_bpm(160)
        h2 = IFFID3Handler(iff_file)
        h2.load()
        assert h2.read_bpm() == 160

    def test_custom_genre_fields_returns_dict(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        fields = h.read_custom_genre_fields()
        assert isinstance(fields, dict)
        assert "TITLEGENRE" in fields
        assert "GENREDERIVED" in fields

    def test_custom_genre_fields_all_none_initially(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        fields = h.read_custom_genre_fields()
        assert all(v is None for v in fields.values())

    def test_write_genre_sync_result(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        h.write_genre_sync_result("Rock", "derived_rock")
        h2 = IFFID3Handler(iff_file)
        h2.load()
        assert h2.read_genre() == "Rock"

    def test_genre_sync_result_writes_genrederived_field(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        h.write_genre_sync_result("Rock", "Album")
        h2 = IFFID3Handler(iff_file)
        h2.load()
        fields = h2.read_custom_genre_fields()
        assert fields["GENREDERIVED"] == "Album"

    def test_embed_artwork(self, iff_file):
        jpeg = (
            b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
            b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
            b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
            b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e\xd0"
            b"\xff\xd9"
        )
        h = IFFID3Handler(iff_file)
        h.load()
        h.embed_artwork(jpeg)  # must not raise

    def test_read_artist_album_defaults(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        artist, album = h.read_artist_album()
        assert isinstance(artist, str)
        assert isinstance(album, str)

    def test_get_raw_tags_returns_tags_after_write(self, iff_file):
        h = IFFID3Handler(iff_file)
        h.load()
        h.write_bpm(99)
        raw = h.get_raw_tags()
        assert raw is not None

    def test_wav_and_aiff_produce_distinct_audio_types(self, wav_file, aiff_file):
        """Confirm load() actually picks WAVE vs AIFF based on extension,
        not just that both happen to work."""
        import mutagen.aiff
        import mutagen.wave

        h_wav = IFFID3Handler(wav_file)
        h_wav.load()
        h_aiff = IFFID3Handler(aiff_file)
        h_aiff.load()

        assert isinstance(h_wav._audio, mutagen.wave.WAVE)
        assert isinstance(h_aiff._audio, mutagen.aiff.AIFF)

    def test_unrecognized_extension_raises_value_error(self, tmp_path):
        bad = tmp_path / "test.xyz"
        bad.write_bytes(b"x")
        h = IFFID3Handler(str(bad))
        with pytest.raises(AudioFormatError, match="cannot load extension"):
            h.load()


# ── VorbisHandler (FLAC) ──────────────────────────────────────────────────────


class TestVorbisHandlerFLAC:
    def test_bpm_round_trip(self, flac_file):
        h = VorbisHandler(flac_file)
        h.load()
        h.write_bpm(120)
        h2 = VorbisHandler(flac_file)
        h2.load()
        assert h2.read_bpm() == 120

    def test_bpm_none_when_absent(self, flac_file):
        h = VorbisHandler(flac_file)
        h.load()
        assert h.read_bpm() is None

    def test_key_round_trip(self, flac_file):
        h = VorbisHandler(flac_file)
        h.load()
        h.write_key("G")
        h2 = VorbisHandler(flac_file)
        h2.load()
        assert h2.read_key() == "G"

    def test_genre_round_trip(self, flac_file):
        h = VorbisHandler(flac_file)
        h.load()
        h.write_genre("Jazz")
        h2 = VorbisHandler(flac_file)
        h2.load()
        assert h2.read_genre() == "Jazz"

    def test_tempo_marking_round_trip(self, flac_file):
        h = VorbisHandler(flac_file)
        h.load()
        h.write_tempo_marking("Andante")
        h2 = VorbisHandler(flac_file)
        h2.load()
        assert h2.read_tempo_marking() == "Andante"

    def test_custom_genre_fields_dict(self, flac_file):
        h = VorbisHandler(flac_file)
        h.load()
        fields = h.read_custom_genre_fields()
        assert isinstance(fields, dict)
        assert "TITLEGENRE" in fields

    def test_write_genre_sync_result(self, flac_file):
        h = VorbisHandler(flac_file)
        h.load()
        h.write_genre_sync_result("Folk", "derived_folk")
        h2 = VorbisHandler(flac_file)
        h2.load()
        assert h2.read_genre() == "Folk"

    def test_set_raw_tags_foreign_dict_persists(self, flac_file):
        h = VorbisHandler(flac_file)
        h.load()
        h.set_raw_tags({"artist": ["Foreign"], "album": ["Swap"]})
        h2 = VorbisHandler(flac_file)
        h2.load()
        assert h2.get_raw_tags()["artist"] == ["Foreign"]
        assert h2.get_raw_tags()["album"] == ["Swap"]

    def test_set_raw_tags_persists_after_wipe(self, flac_file):
        wiped = FLAC(flac_file)
        wiped.delete()
        wiped.save()
        h = VorbisHandler(flac_file)
        h.load()
        h.set_raw_tags({"artist": ["Restored"]})
        h2 = VorbisHandler(flac_file)
        h2.load()
        assert h2.get_raw_tags()["artist"] == ["Restored"]


# ── VorbisHandler (OGG) ───────────────────────────────────────────────────────


class TestVorbisHandlerOGG:
    def test_bpm_round_trip(self, ogg_file):
        h = VorbisHandler(ogg_file)
        h.load()
        h.write_bpm(174)
        h2 = VorbisHandler(ogg_file)
        h2.load()
        assert h2.read_bpm() == 174

    def test_genre_round_trip(self, ogg_file):
        h = VorbisHandler(ogg_file)
        h.load()
        h.write_genre("Drum and Bass")
        h2 = VorbisHandler(ogg_file)
        h2.load()
        assert h2.read_genre() == "Drum and Bass"


# ── MP4Handler ────────────────────────────────────────────────────────────────


class TestMP4Handler:
    def test_bpm_round_trip(self, m4a_file):
        h = MP4Handler(m4a_file)
        h.load()
        h.write_bpm(95)
        h2 = MP4Handler(m4a_file)
        h2.load()
        assert h2.read_bpm() == 95

    def test_bpm_none_when_absent(self, m4a_file):
        h = MP4Handler(m4a_file)
        h.load()
        assert h.read_bpm() is None

    def test_key_round_trip(self, m4a_file):
        h = MP4Handler(m4a_file)
        h.load()
        h.write_key("Bb")
        h2 = MP4Handler(m4a_file)
        h2.load()
        assert h2.read_key() == "Bb"

    def test_genre_round_trip(self, m4a_file):
        h = MP4Handler(m4a_file)
        h.load()
        h.write_genre("Classical")
        h2 = MP4Handler(m4a_file)
        h2.load()
        assert h2.read_genre() == "Classical"

    def test_tempo_marking_round_trip(self, m4a_file):
        h = MP4Handler(m4a_file)
        h.load()
        h.write_tempo_marking("Presto")
        h2 = MP4Handler(m4a_file)
        h2.load()
        assert h2.read_tempo_marking() == "Presto"

    def test_custom_genre_fields_all_none_initially(self, m4a_file):
        h = MP4Handler(m4a_file)
        h.load()
        fields = h.read_custom_genre_fields()
        assert all(v is None for v in fields.values())


# ── Facade / module-level functions ───────────────────────────────────────────


class TestFacadeFunctions:
    def test_read_write_bpm_mp3(self, mp3_file):
        write_bpm(mp3_file, 133)
        assert read_bpm(mp3_file) == 133

    def test_read_write_bpm_flac(self, flac_file):
        write_bpm(flac_file, 105)
        assert read_bpm(flac_file) == 105

    def test_read_write_bpm_ogg(self, ogg_file):
        write_bpm(ogg_file, 87)
        assert read_bpm(ogg_file) == 87

    def test_read_write_bpm_m4a(self, m4a_file):
        write_bpm(m4a_file, 112)
        assert read_bpm(m4a_file) == 112

    def test_read_write_bpm_wav(self, wav_file):
        write_bpm(wav_file, 124)
        assert read_bpm(wav_file) == 124

    def test_read_write_bpm_aiff(self, aiff_file):
        write_bpm(aiff_file, 90)
        assert read_bpm(aiff_file) == 90

    def test_read_write_genre_wav(self, wav_file):
        write_genre(wav_file, "Folk")
        assert read_genre(wav_file) == "Folk"

    def test_read_write_genre_aiff(self, aiff_file):
        write_genre(aiff_file, "Soundtrack")
        assert read_genre(aiff_file) == "Soundtrack"

    def test_write_genre_sync_result_facade_wav(self, wav_file):
        write_genre_sync_result(wav_file, "Jazz", "Album")
        assert read_genre(wav_file) == "Jazz"
        assert read_custom_genre_fields(wav_file)["GENREDERIVED"] == "Album"

    def test_write_genre_sync_result_facade_aiff(self, aiff_file):
        write_genre_sync_result(aiff_file, "Blues", "Artist")
        assert read_genre(aiff_file) == "Blues"
        assert read_custom_genre_fields(aiff_file)["GENREDERIVED"] == "Artist"

    def test_is_supported_wav(self, wav_file):
        assert is_supported(wav_file) is True

    def test_is_supported_aiff(self, aiff_file):
        assert is_supported(aiff_file) is True

    def test_read_write_key(self, mp3_file):
        write_key(mp3_file, "F#m")
        assert read_key(mp3_file) == "F#m"

    def test_read_write_genre(self, mp3_file):
        write_genre(mp3_file, "Ambient")
        assert read_genre(mp3_file) == "Ambient"

    def test_read_write_tempo_marking(self, mp3_file):
        write_tempo_marking(mp3_file, "Largo")
        assert read_tempo_marking(mp3_file) == "Largo"

    def test_read_bpm_returns_none_for_absent(self, mp3_file):
        assert read_bpm(mp3_file) is None

    def test_read_bpm_returns_none_for_unsupported_file(self, tmp_path):
        f = tmp_path / "notes.txt"
        f.write_text("x")
        assert read_bpm(str(f)) is None

    def test_read_custom_genre_fields_returns_dict(self, mp3_file):
        fields = read_custom_genre_fields(mp3_file)
        assert isinstance(fields, dict)

    def test_read_custom_genre_fields_unsupported_file_returns_none_dict(
        self, tmp_path
    ):
        f = tmp_path / "notes.txt"
        f.write_text("x")
        fields = read_custom_genre_fields(str(f))
        assert all(v is None for v in fields.values())

    def test_write_genre_sync_result_facade(self, mp3_file):
        write_genre_sync_result(mp3_file, "Pop", "derived_pop")
        assert read_genre(mp3_file) == "Pop"

    def test_write_album_genre_result_facade(self, mp3_file):
        write_album_genre_result(mp3_file, "Classical; Jazz")
        assert read_custom_genre_fields(mp3_file)["ALBUMGENRE"] == "Classical; Jazz"

    def test_read_artist_album_defaults(self, mp3_file):
        artist, album = read_artist_album(mp3_file)
        assert isinstance(artist, str)
        assert isinstance(album, str)

    def test_read_artist_album_unsupported_returns_unknown(self, tmp_path):
        f = tmp_path / "bad.xyz"
        f.write_bytes(b"x")
        artist, album = read_artist_album(str(f))
        assert artist == "Unknown"
        assert album == "Unknown"

    def test_read_album_artist_absent_returns_none(self, mp3_file):
        assert read_album_artist(mp3_file) is None

    def test_read_tags_raw_returns_object_after_write(self, mp3_file):
        write_bpm(mp3_file, 99)
        raw = read_tags_raw(mp3_file)
        assert raw is not None

    def test_read_tags_raw_unsupported_returns_none(self, tmp_path):
        f = tmp_path / "bad.xyz"
        f.write_bytes(b"x")
        assert read_tags_raw(str(f)) is None

    def test_is_supported_mp3(self, mp3_file):
        assert is_supported(mp3_file) is True

    def test_is_supported_flac(self, flac_file):
        assert is_supported(flac_file) is True


# ── Cross-format coverage for remaining handler branches ────────────────────


_TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"
)


class TestHandlerResidualBranches:
    """Exercise mood/artist-album/raw-tags/artwork paths on every handler."""

    def test_read_mood_absent_returns_none(self, flac_file, ogg_file, m4a_file):
        for path in (flac_file, ogg_file, m4a_file):
            h = TagHandlerFactory.get_handler(path)
            assert h.read_mood() is None

    @pytest.mark.parametrize(
        "fixture_name", ["flac_file", "ogg_file", "m4a_file", "wav_file"]
    )
    def test_artist_album_and_album_artist(self, fixture_name, request):
        path = request.getfixturevalue(fixture_name)
        h = TagHandlerFactory.get_handler(path)
        artist, album = h.read_artist_album()
        assert isinstance(artist, str)
        assert isinstance(album, str)
        assert h.read_album_artist() is None

    def test_vorbis_embed_artwork_round_trip(self, flac_file, tmp_path):
        jpeg_path = tmp_path / "art.jpg"
        jpeg_path.write_bytes(_TINY_JPEG)
        h = VorbisHandler(flac_file)
        h.load()
        h.embed_artwork(jpeg_path.read_bytes())
        h2 = VorbisHandler(flac_file)
        h2.load()
        assert len(h2._audio.pictures) == 1

    def test_ogg_embed_artwork_round_trip(self, ogg_file, tmp_path):
        jpeg_path = tmp_path / "art.jpg"
        jpeg_path.write_bytes(_TINY_JPEG)
        h = VorbisHandler(ogg_file)
        h.load()
        h.embed_artwork(jpeg_path.read_bytes())
        h2 = VorbisHandler(ogg_file)
        h2.load()
        assert "metadata_block_picture" in h2.get_raw_tags()

    def test_mp4_embed_artwork_round_trip(self, m4a_file, tmp_path):
        jpeg_path = tmp_path / "art.jpg"
        jpeg_path.write_bytes(_TINY_JPEG)
        h = MP4Handler(m4a_file)
        h.load()
        h.embed_artwork(jpeg_path.read_bytes())
        h2 = MP4Handler(m4a_file)
        h2.load()
        assert "covr" in h2.get_raw_tags()

    def test_mp4_genre_sync_result_round_trip(self, m4a_file):
        h = MP4Handler(m4a_file)
        h.load()
        h.write_genre_sync_result("Soul", "Album")
        h2 = MP4Handler(m4a_file)
        h2.load()
        assert h2.read_genre() == "Soul"

    def test_set_raw_tags_persists(self, flac_file):
        h = VorbisHandler(flac_file)
        h.load()
        raw = h.get_raw_tags()
        h.set_raw_tags(raw)
        h2 = VorbisHandler(flac_file)
        h2.load()
        assert h2.get_raw_tags() is not None

    def test_base_default_get_raw_tags_none_until_loaded(self, mp3_file):
        h = MP3Handler(mp3_file)
        assert h.get_raw_tags() is None


# ── Auto-snapshot integration with batch_undo ────────────────────────────────


class TestAutoSnapshotIntegration:
    """When an active undo batch exists, write_* functions should snapshot
    the file's tags before modification."""

    def test_write_bpm_with_active_batch_snapshots(self, mp3_file):
        from unittest.mock import MagicMock, patch

        from audio_suite_shared import batch_undo

        batch_undo._thread_local.batch_id = "test_batch_xyz"
        batch_undo._thread_local.enabled = True
        batch_undo._thread_local.log = None

        with patch.object(batch_undo, "BatchUndoLog") as mock_log_cls:
            mock_log = mock_log_cls.return_value
            mock_log.record_tag_edit = MagicMock()

            batch_undo._thread_local.log = mock_log
            write_bpm(mp3_file, 133)

            mock_log.record_tag_edit.assert_called_once()
            call_args = mock_log.record_tag_edit.call_args[0]
            assert call_args[0] == "test_batch_xyz"
            assert call_args[1] == mp3_file
            assert call_args[2] == "write_bpm"

        batch_undo._thread_local.batch_id = None
        batch_undo._thread_local.log = None
        batch_undo._thread_local.enabled = False

    def test_write_bpm_no_active_batch_no_snapshot(self):
        """Without an active undo batch, snapshot is a no-op (no error)."""
        from unittest.mock import patch

        from audio_suite_shared import batch_undo

        batch_undo._thread_local.batch_id = None
        batch_undo._thread_local.log = None
        batch_undo._thread_local.enabled = False

        with patch(
            "audio_suite_shared.tag_helper_writer.record_tag_edit_snapshot"
        ) as mock_snap:
            with patch(
                "audio_suite_shared.tag_helper_writer.TagHandlerFactory.get_handler"
            ):
                write_bpm("/fake/song.mp3", 120)
            mock_snap.assert_called_once_with("/fake/song.mp3", "write_bpm")

    def test_write_tags_raw_snapshot_suppressed_by_flag(self, mp3_file):
        """record_snapshot=False must skip the auto-undo snapshot so temp-file
        writes never leave dead undo records."""
        from unittest.mock import MagicMock, patch

        from audio_suite_shared import batch_undo
        from audio_suite_shared.tag_helper_writer import write_tags_raw

        batch_undo._thread_local.batch_id = "test_batch_raw_flag"
        batch_undo._thread_local.enabled = True
        batch_undo._thread_local.log = None

        handler = MagicMock()
        shared_factory = MagicMock()
        shared_factory.get_handler.return_value = handler

        try:
            mock_log = MagicMock()
            batch_undo._thread_local.log = mock_log

            with (
                patch(
                    "audio_suite_shared.tag_helper_writer.TagHandlerFactory",
                    shared_factory,
                ),
                patch(
                    "audio_suite_shared.tag_helper_base.TagHandlerFactory",
                    shared_factory,
                ),
            ):
                write_tags_raw(mp3_file, {"TPE1": "Artist"})
                write_tags_raw(mp3_file, {"TPE1": "Artist"}, record_snapshot=False)

            assert mock_log.record_tag_edit.call_count == 1
            assert mock_log.record_tag_edit.call_args[0][1] == mp3_file
        finally:
            batch_undo._thread_local.batch_id = None
            batch_undo._thread_local.log = None
            batch_undo._thread_local.enabled = False


# ── write_replaygain facade ────────────────────────────────────────────────────


class TestWriteReplaygain:
    """write_replaygain writes the four canonical fields per format family."""

    def test_mp3_persisted_as_txxx_frames(self, mp3_file):
        from mutagen.id3 import TXXX

        from audio_suite_shared.tag_helper import write_replaygain

        write_replaygain(
            mp3_file,
            {
                "REPLAYGAIN_TRACK_GAIN": "+2.34 dB",
                "REPLAYGAIN_ALBUM_GAIN": "+1.80 dB",
                "REPLAYGAIN_TRACK_PEAK": "0.912345",
                "REPLAYGAIN_ALBUM_PEAK": "0.956789",
            },
        )
        import mutagen

        audio = mutagen.File(mp3_file)
        tags = {f.desc: f.text[0] for f in audio.tags.values() if isinstance(f, TXXX)}
        assert tags.get("REPLAYGAIN_TRACK_GAIN") == "+2.34 dB"
        assert tags.get("REPLAYGAIN_ALBUM_PEAK") == "0.956789"

    def test_wav_persisted_as_txxx_frames(self, wav_file):
        from mutagen.id3 import TXXX

        from audio_suite_shared.tag_helper import write_replaygain

        write_replaygain(
            wav_file,
            {
                "REPLAYGAIN_TRACK_GAIN": "+2.00 dB",
                "REPLAYGAIN_TRACK_PEAK": "0.900000",
            },
        )
        import mutagen

        audio = mutagen.File(wav_file)
        tags = {f.desc: f.text[0] for f in audio.tags.values() if isinstance(f, TXXX)}
        assert tags.get("REPLAYGAIN_TRACK_GAIN") == "+2.00 dB"

    def test_m4a_persisted_as_freeform_atoms(self, m4a_file):
        from audio_suite_shared.tag_helper import write_replaygain

        write_replaygain(
            m4a_file,
            {
                "REPLAYGAIN_TRACK_GAIN": "+2.34 dB",
                "REPLAYGAIN_ALBUM_GAIN": "+1.80 dB",
            },
        )
        import mutagen

        audio = mutagen.File(m4a_file)
        atom = "----:com.apple.iTunes:REPLAYGAIN_TRACK_GAIN"
        assert audio.tags[atom][0].decode("utf-8") == "+2.34 dB"
        assert "REPLAYGAIN_TRACK_GAIN" not in audio.tags

    def test_flac_persisted_as_vorbis_fields(self, flac_file):
        from audio_suite_shared.tag_helper import write_replaygain

        write_replaygain(
            flac_file,
            {
                "REPLAYGAIN_TRACK_GAIN": "+1.00 dB",
                "REPLAYGAIN_ALBUM_PEAK": "0.750000",
            },
        )
        import mutagen

        audio = mutagen.File(flac_file)
        assert audio["REPLAYGAIN_TRACK_GAIN"][0] == "+1.00 dB"
        assert audio["REPLAYGAIN_ALBUM_PEAK"][0] == "0.750000"

    def test_ogg_persisted_as_vorbis_fields(self, ogg_file):
        from audio_suite_shared.tag_helper import write_replaygain

        write_replaygain(
            ogg_file,
            {
                "REPLAYGAIN_TRACK_GAIN": "+0.50 dB",
                "REPLAYGAIN_TRACK_PEAK": "0.800000",
            },
        )
        import mutagen

        audio = mutagen.File(ogg_file)
        assert audio["REPLAYGAIN_TRACK_GAIN"][0] == "+0.50 dB"
        assert audio["REPLAYGAIN_TRACK_PEAK"][0] == "0.800000"

    def test_nonexistent_file_raises_audio_tag_error(self, tmp_path):
        from audio_suite_shared.exceptions import AudioSuiteError
        from audio_suite_shared.tag_helper import write_replaygain

        with pytest.raises(AudioSuiteError):
            write_replaygain(
                str(tmp_path / "ghost.mp3"),
                {"REPLAYGAIN_TRACK_GAIN": "+1.00 dB"},
            )

    def test_snapshots_with_active_batch(self, mp3_file):
        """write_replaygain snapshots prior tags before writing."""
        from unittest.mock import MagicMock, patch

        from audio_suite_shared import batch_undo
        from audio_suite_shared.tag_helper import write_replaygain

        batch_undo._thread_local.batch_id = "test_batch_rg"
        batch_undo._thread_local.enabled = True
        batch_undo._thread_local.log = None

        try:
            with patch.object(batch_undo, "BatchUndoLog") as mock_log_cls:
                mock_log = mock_log_cls.return_value
                mock_log.record_tag_edit = MagicMock()
                batch_undo._thread_local.log = mock_log

                write_replaygain(
                    mp3_file,
                    {"REPLAYGAIN_TRACK_GAIN": "+2.34 dB"},
                )

                mock_log.record_tag_edit.assert_called_once()
                call_args = mock_log.record_tag_edit.call_args[0]
                assert call_args[0] == "test_batch_rg"
                assert call_args[1] == mp3_file
                assert call_args[2] == "write_replaygain"
        finally:
            batch_undo._thread_local.batch_id = None
            batch_undo._thread_local.log = None
            batch_undo._thread_local.enabled = False


# ── Format expansion: artwork extraction + album-genre writes ────────────────
# Phase 1 of PLAN_format_support_expansion.md: every canonical format must
# support extract_artwork() and write_album_genre_result() through the shared
# TagHandlerFactory, not merely MP3/ID3-backed files.

_ALL_FORMAT_FIXTURES = [
    "mp3_file",
    "flac_file",
    "ogg_file",
    "opus_file",
    "m4a_file",
    "mp4_file",
    "wav_file",
    "aiff_file",
]


def _album_derived_marker(handler) -> str | None:
    """Read the ALBUMDERIVED marker in the handler's native convention."""
    if isinstance(handler, MP3Handler):  # IFFID3Handler subclasses MP3Handler
        frame = handler.get_raw_tags().get("TXXX:ALBUMDERIVED")
        return str(frame.text[0]) if frame else None
    if isinstance(handler, VorbisHandler):
        tags = handler.get_raw_tags()
        return str(tags["ALBUMDERIVED"][0]) if "ALBUMDERIVED" in tags else None
    atom = handler.get_raw_tags()["----:com.apple.iTunes:ALBUMDERIVED"][0]
    return str(atom.decode())


class TestFormatExpansionArtwork:
    @pytest.mark.parametrize("fixture_name", _ALL_FORMAT_FIXTURES)
    def test_extract_artwork_absent_returns_none(self, fixture_name, request):
        path = request.getfixturevalue(fixture_name)
        assert TagHandlerFactory.get_handler(path).extract_artwork() is None

    @pytest.mark.parametrize("fixture_name", _ALL_FORMAT_FIXTURES)
    def test_extract_artwork_round_trip(self, fixture_name, request):
        path = request.getfixturevalue(fixture_name)
        TagHandlerFactory.get_handler(path).embed_artwork(_TINY_JPEG)
        reloaded = TagHandlerFactory.get_handler(path)
        assert reloaded.extract_artwork() == _TINY_JPEG

    def test_extract_artwork_aif_short_extension(self, aiff_file, tmp_path):
        short_path = tmp_path / "test.aif"
        os.replace(aiff_file, short_path)
        TagHandlerFactory.get_handler(str(short_path)).embed_artwork(_TINY_JPEG)
        handler = TagHandlerFactory.get_handler(str(short_path))
        assert handler.extract_artwork() == _TINY_JPEG


class TestFormatExpansionAlbumGenre:
    @pytest.mark.parametrize("fixture_name", _ALL_FORMAT_FIXTURES)
    def test_write_album_genre_result_round_trip(self, fixture_name, request):
        path = request.getfixturevalue(fixture_name)
        write_album_genre_result(path, "Jazz; Rock")
        assert read_custom_genre_fields(path)["ALBUMGENRE"] == "Jazz; Rock"
        handler = TagHandlerFactory.get_handler(path)
        assert _album_derived_marker(handler) == "Y"

    @pytest.mark.parametrize("fixture_name", _ALL_FORMAT_FIXTURES)
    def test_write_album_genre_result_custom_marker(self, fixture_name, request):
        path = request.getfixturevalue(fixture_name)
        write_album_genre_result(path, "Pop", derived_marker="N")
        handler = TagHandlerFactory.get_handler(path)
        assert _album_derived_marker(handler) == "N"

    def test_write_album_genre_result_aif_short_extension(self, aiff_file, tmp_path):
        short_path = tmp_path / "test.aif"
        os.replace(aiff_file, short_path)
        write_album_genre_result(str(short_path), "Blues")
        assert read_custom_genre_fields(str(short_path))["ALBUMGENRE"] == "Blues"
        handler = TagHandlerFactory.get_handler(str(short_path))
        assert _album_derived_marker(handler) == "Y"
