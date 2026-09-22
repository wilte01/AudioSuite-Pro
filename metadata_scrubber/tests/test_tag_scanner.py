"""
Tests for metadata_scrubber.core.tag_scanner
Gap G-07: is_ignored(), scan_custom_tags()

Uses pydub + mutagen to create real minimal audio test fixtures for all formats.
"""

import pytest
from mutagen.aiff import AIFF
from mutagen.flac import FLAC
from mutagen.id3 import ID3, TXXX
from mutagen.mp4 import MP4
from mutagen.oggvorbis import OggVorbis
from mutagen.wave import WAVE
from pydub import AudioSegment

from metadata_scrubber.core.tag_scanner import (
    _IGNORED_KEYWORDS,
    is_ignored,
    scan_custom_tags,
)

# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_mp3_with_txxx(tmp_path, filename: str, txxx_tags: dict) -> str:
    """Create a minimal MP3 with specified TXXX tags and return its path."""
    path = tmp_path / filename
    AudioSegment.silent(duration=100).export(str(path), format="mp3")
    tags = ID3(str(path))
    for desc, value in txxx_tags.items():
        tags.add(TXXX(encoding=3, desc=desc, text=value))
    tags.save()
    return str(path)


def _make_flac_with_vorbis(tmp_path, filename: str, vorbis_tags: dict) -> str:
    """Create a minimal FLAC with specified Vorbis comment tags.

    Note: mutagen stores Vorbis comment keys as-is; lowercase is conventional.
    """
    path = tmp_path / filename
    AudioSegment.silent(duration=100).export(str(path), format="flac")
    audio = FLAC(str(path))
    for key, value in vorbis_tags.items():
        audio[key] = value
    audio.save()
    return str(path)


def _make_ogg_with_vorbis(tmp_path, filename: str, vorbis_tags: dict) -> str:
    """Create a minimal OGG with specified Vorbis comment tags."""
    path = tmp_path / filename
    AudioSegment.silent(duration=100).export(str(path), format="ogg")
    audio = OggVorbis(str(path))
    for key, value in vorbis_tags.items():
        audio[key] = value
    audio.save()
    return str(path)


def _make_m4a_with_freeform(tmp_path, filename: str, freeform_tags: dict) -> str:
    """Create a minimal M4A with specified freeform iTunes tags."""
    path = tmp_path / filename
    AudioSegment.silent(duration=100).export(str(path), format="ipod", bitrate="128k")
    audio = MP4(str(path))
    for key, value in freeform_tags.items():
        atom = f"----:com.apple.iTunes:{key}"
        audio[atom] = [value.encode()]
    audio.save()
    return str(path)


def _make_wav_with_txxx(tmp_path, filename: str, txxx_tags: dict) -> str:
    """Create a minimal WAV with specified TXXX ID3 tags."""
    path = tmp_path / filename
    AudioSegment.silent(duration=100).export(str(path), format="wav")
    audio = WAVE(str(path))
    audio.add_tags()
    for desc, value in txxx_tags.items():
        audio.tags.add(TXXX(encoding=3, desc=desc, text=value))
    audio.save()
    return str(path)


def _make_aiff_with_txxx(tmp_path, filename: str, txxx_tags: dict) -> str:
    """Create a minimal AIFF with specified TXXX ID3 tags."""
    path = tmp_path / filename
    AudioSegment.silent(duration=100).export(str(path), format="aiff")
    audio = AIFF(str(path))
    audio.add_tags()
    for desc, value in txxx_tags.items():
        audio.tags.add(TXXX(encoding=3, desc=desc, text=value))
    audio.save()
    return str(path)


# ── is_ignored ────────────────────────────────────────────────────────────────


class TestIsIgnored:
    @pytest.mark.parametrize(
        "desc",
        [
            "REPLAYGAIN_TRACK_GAIN",
            "replaygain_album_peak",
            "BPM",
            "Tempo Marking",
            "Initial Key",
            "MusicBrainz Track Id",
            "AcousticID Fingerprint",
            "BARCODE",
            "MediaType",
            "OriginalDate",
        ],
    )
    def test_system_tags_are_ignored(self, desc):
        assert is_ignored(desc) is True

    @pytest.mark.parametrize(
        "desc",
        [
            "TITLEGENRE",
            "ALBUMGENRE",
            "ARTISTGENRE",
            "ALBUMARTISTGENRE",
            "GENREDERIVED",
            "ALBUMDERIVED",
            "MOOD",
            "CustomLabel",
            "MyProject",
        ],
    )
    def test_user_tags_are_not_ignored(self, desc):
        assert is_ignored(desc) is False

    def test_case_insensitive_matching(self):
        assert is_ignored("ReplayGain_Track_Gain") is True
        assert is_ignored("MUSICBRAINZ_TRACKID") is True

    def test_partial_match_triggers_ignore(self):
        assert is_ignored("my_replaygain_tag") is True
        assert is_ignored("bpm_adjusted") is True

    def test_empty_string_is_not_ignored(self):
        assert is_ignored("") is False

    def test_all_ignored_keywords_trigger_ignore(self):
        for kw in _IGNORED_KEYWORDS:
            assert is_ignored(kw) is True, f"Keyword '{kw}' should be ignored"

    def test_returns_bool(self):
        assert isinstance(is_ignored("anything"), bool)


# ── scan_custom_tags ──────────────────────────────────────────────────────────


class TestScanCustomTags:
    def test_finds_user_txxx_tags(self, tmp_path):
        _make_mp3_with_txxx(
            tmp_path, "a.mp3", {"TITLEGENRE": "Rock", "ALBUMGENRE": "Jazz"}
        )
        result = scan_custom_tags(str(tmp_path))
        assert "TITLEGENRE" in result
        assert "ALBUMGENRE" in result

    def test_excludes_system_txxx_tags(self, tmp_path):
        _make_mp3_with_txxx(
            tmp_path,
            "a.mp3",
            {
                "REPLAYGAIN_TRACK_GAIN": "+2.0 dB",
                "BPM": "128",
                "TITLEGENRE": "Pop",
            },
        )
        result = scan_custom_tags(str(tmp_path))
        assert "REPLAYGAIN_TRACK_GAIN" not in result
        assert "BPM" not in result
        assert "TITLEGENRE" in result

    def test_returns_set(self, tmp_path):
        _make_mp3_with_txxx(tmp_path, "a.mp3", {"TITLEGENRE": "Rock"})
        result = scan_custom_tags(str(tmp_path))
        assert isinstance(result, set)

    def test_empty_directory_returns_empty_set(self, tmp_path):
        result = scan_custom_tags(str(tmp_path))
        assert result == set()

    def test_nonexistent_directory_returns_empty_set(self):
        errors = []
        result = scan_custom_tags("/no/such/dir", on_error=errors.append)
        assert result == set()
        assert len(errors) == 1

    def test_on_error_callback_called_for_bad_dir(self):
        errors = []
        scan_custom_tags("/no/such/dir", on_error=errors.append)
        assert len(errors) == 1
        assert isinstance(errors[0], str)
        assert len(errors[0]) > 0

    def test_on_error_is_optional(self):
        result = scan_custom_tags("/no/such/dir")
        assert result == set()

    def test_ignores_non_audio_files(self, tmp_path):
        (tmp_path / "notes.txt").write_text("not audio")
        result = scan_custom_tags(str(tmp_path))
        assert result == set()

    def test_deduplicates_tags_across_files(self, tmp_path):
        _make_mp3_with_txxx(tmp_path, "a.mp3", {"TITLEGENRE": "Rock"})
        _make_mp3_with_txxx(tmp_path, "b.mp3", {"TITLEGENRE": "Jazz"})
        result = scan_custom_tags(str(tmp_path))
        assert len([t for t in result if t == "TITLEGENRE"]) == 1

    def test_sample_size_limits_files_scanned(self, tmp_path):
        for i in range(5):
            _make_mp3_with_txxx(tmp_path, f"f{i}.mp3", {f"UNIQUE_TAG_{i}": f"val{i}"})
        result = scan_custom_tags(str(tmp_path), sample_size=2)
        assert len(result) <= 2

    def test_corrupt_file_skipped_gracefully(self, tmp_path):
        (tmp_path / "bad.mp3").write_bytes(b"this is not an mp3")
        _make_mp3_with_txxx(tmp_path, "good.mp3", {"TITLEGENRE": "Soul"})
        result = scan_custom_tags(str(tmp_path))
        assert "TITLEGENRE" in result

    def test_multiple_tags_from_single_file(self, tmp_path):
        _make_mp3_with_txxx(
            tmp_path,
            "a.mp3",
            {
                "TITLEGENRE": "Rock",
                "ALBUMGENRE": "Jazz",
                "MOOD": "Energetic",
            },
        )
        result = scan_custom_tags(str(tmp_path))
        assert {"TITLEGENRE", "ALBUMGENRE", "MOOD"}.issubset(result)


# ═════════════════════════════════════════════════════════════════════════════
# Additional edge cases
# ═════════════════════════════════════════════════════════════════════════════


class TestIsIgnoredEdgeCases:
    def test_whitespace_string_not_ignored(self):
        assert is_ignored("   ") is False

    def test_numeric_string_not_ignored(self):
        assert is_ignored("123456") is False

    def test_special_characters_not_ignored(self):
        assert is_ignored("!@#$%^") is False


class TestScanCustomTagsEdgeCases:
    def test_sample_size_zero_returns_empty_set(self, tmp_path):
        _make_mp3_with_txxx(tmp_path, "a.mp3", {"TITLEGENRE": "Rock"})
        result = scan_custom_tags(str(tmp_path), sample_size=0)
        assert result == set()

    def test_sample_size_exceeding_file_count(self, tmp_path):
        _make_mp3_with_txxx(tmp_path, "a.mp3", {"TITLEGENRE": "Rock"})
        result = scan_custom_tags(str(tmp_path), sample_size=9999)
        assert "TITLEGENRE" in result

    def test_valid_mp3_without_id3_tags_skipped(self, tmp_path):
        AudioSegment.silent(duration=100).export(
            str(tmp_path / "no_tags.mp3"), format="mp3"
        )
        _make_mp3_with_txxx(tmp_path, "with_tags.mp3", {"TITLEGENRE": "Rock"})
        result = scan_custom_tags(str(tmp_path))
        assert "TITLEGENRE" in result


# ═════════════════════════════════════════════════════════════════════════════
# Multi-format scanning tests
# ═════════════════════════════════════════════════════════════════════════════


class TestScanCustomTagsVorbis:
    def test_flac_vorbis_tags_discovered(self, tmp_path):
        _make_flac_with_vorbis(tmp_path, "a.flac", {"titlegenre": "Rock"})
        result = scan_custom_tags(str(tmp_path))
        assert "titlegenre" in result

    def test_ogg_vorbis_tags_discovered(self, tmp_path):
        _make_ogg_with_vorbis(tmp_path, "a.ogg", {"albumgenre": "Jazz"})
        result = scan_custom_tags(str(tmp_path))
        assert "albumgenre" in result

    def test_vorbis_system_tags_excluded(self, tmp_path):
        _make_flac_with_vorbis(
            tmp_path,
            "a.flac",
            {"replaygain_track_gain": "+2.0 dB", "mood": "Chill"},
        )
        result = scan_custom_tags(str(tmp_path))
        assert "replaygain_track_gain" not in result
        assert "mood" in result


class TestScanCustomTagsMP4:
    def test_m4a_freeform_tags_discovered(self, tmp_path):
        _make_m4a_with_freeform(tmp_path, "a.m4a", {"TITLEGENRE": "Pop"})
        result = scan_custom_tags(str(tmp_path))
        assert "TITLEGENRE" in result

    def test_m4a_system_freeform_excluded(self, tmp_path):
        _make_m4a_with_freeform(
            tmp_path,
            "a.m4a",
            {"BPM": "128", "MOOD": "Happy"},
        )
        result = scan_custom_tags(str(tmp_path))
        assert "BPM" not in result
        assert "MOOD" in result


class TestScanCustomTagsWAVAIFF:
    def test_wav_txxx_tags_discovered(self, tmp_path):
        _make_wav_with_txxx(tmp_path, "a.wav", {"TITLEGENRE": "Classical"})
        result = scan_custom_tags(str(tmp_path))
        assert "TITLEGENRE" in result

    def test_aiff_txxx_tags_discovered(self, tmp_path):
        _make_aiff_with_txxx(tmp_path, "a.aiff", {"ALBUMGENRE": "Electronic"})
        result = scan_custom_tags(str(tmp_path))
        assert "ALBUMGENRE" in result

    def test_aif_txxx_tags_discovered(self, tmp_path):
        _make_aiff_with_txxx(tmp_path, "a.aif", {"MOOD": "Dark"})
        result = scan_custom_tags(str(tmp_path))
        assert "MOOD" in result


class TestScanCustomTagsMixedFormats:
    def test_all_formats_scanned_together(self, tmp_path):
        _make_mp3_with_txxx(tmp_path, "a.mp3", {"TITLEGENRE": "Rock"})
        _make_flac_with_vorbis(tmp_path, "b.flac", {"albumgenre": "Jazz"})
        _make_ogg_with_vorbis(tmp_path, "c.ogg", {"mood": "Chill"})
        _make_m4a_with_freeform(tmp_path, "d.m4a", {"GENREDERIVED": "auto"})
        _make_wav_with_txxx(tmp_path, "e.wav", {"CUSTOMTAG": "val"})
        _make_aiff_with_txxx(tmp_path, "f.aiff", {"ANOTHER": "val2"})
        result = scan_custom_tags(str(tmp_path))
        assert {
            "TITLEGENRE",
            "albumgenre",
            "mood",
            "GENREDERIVED",
            "CUSTOMTAG",
            "ANOTHER",
        }.issubset(result)
