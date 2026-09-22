"""
Tests for music_format_converter.core.formats
Gap G-05: format_info, is_lossy, detect_format, can_convert,
          available_output_formats, scan_input_directory, ScanResult
"""

import pytest

from music_format_converter.core.formats import (
    ALL_FORMATS,
    ALL_OUTPUT_FORMATS,
    LOSSLESS_FORMATS,
    LOSSY_FORMATS,
    UNSUPPORTED_OUTPUT_FORMATS,
    ScanResult,
    available_output_formats,
    can_convert,
    detect_format,
    format_info,
    is_lossy,
    scan_input_directory,
)

# ── Constants ─────────────────────────────────────────────────────────────────


class TestConstants:
    def test_all_formats_is_lossy_plus_lossless(self):
        assert set(ALL_FORMATS) == set(LOSSY_FORMATS) | set(LOSSLESS_FORMATS)

    def test_no_overlap_between_lossy_and_lossless(self):
        assert not set(LOSSY_FORMATS) & set(LOSSLESS_FORMATS)

    def test_known_lossy_formats_present(self):
        for fmt in ("mp3", "aac", "m4a", "ogg", "opus", "mp4", "wma"):
            assert fmt in LOSSY_FORMATS

    def test_known_lossless_formats_present(self):
        for fmt in ("flac", "wav", "alac", "aiff", "aif", "ape", "wv"):
            assert fmt in LOSSLESS_FORMATS

    def test_all_output_formats_excludes_unsupported(self):
        for fmt in UNSUPPORTED_OUTPUT_FORMATS:
            assert fmt not in ALL_OUTPUT_FORMATS
        for fmt in ALL_FORMATS:
            if fmt not in UNSUPPORTED_OUTPUT_FORMATS:
                assert fmt in ALL_OUTPUT_FORMATS


# ── format_info ───────────────────────────────────────────────────────────────


class TestFormatInfo:
    def test_lossless_description_mentions_lossless(self):
        info = format_info("flac")
        assert "lossless" in info.lower()

    def test_lossy_description_mentions_lossy(self):
        info = format_info("mp3")
        assert "lossy" in info.lower()

    def test_lossless_warns_about_conversion_restriction(self):
        info = format_info("flac")
        assert "lossless" in info.lower() and "source" in info.lower()

    def test_mp3_mentions_id3(self):
        assert "ID3" in format_info("mp3")

    def test_m4a_mentions_metadata(self):
        assert "metadata" in format_info("m4a").lower()

    def test_aac_warns_about_metadata(self):
        info = format_info("aac")
        assert "metadata" in info.lower() or "M4A" in info

    def test_flac_mentions_vorbis(self):
        assert (
            "Vorbis" in format_info("flac") or "vorbis" in format_info("flac").lower()
        )

    def test_returns_string(self):
        assert isinstance(format_info("mp3"), str)

    def test_format_name_appears_in_output(self):
        for fmt in ("mp3", "flac", "m4a", "ogg"):
            assert fmt.upper() in format_info(fmt)

    @pytest.mark.parametrize(
        "fmt",
        [
            "mp3",
            "flac",
            "m4a",
            "ogg",
            "opus",
            "wma",
            "aac",
            "wv",
            "alac",
            "ape",
            "mp4",
            "aiff",
            "aif",
        ],
    )
    def test_format_name_appears_in_output_all(self, fmt):
        assert fmt.upper() in format_info(fmt)


# ── is_lossy ──────────────────────────────────────────────────────────────────


class TestIsLossy:
    @pytest.mark.parametrize("fmt", ["mp3", "aac", "m4a", "ogg", "opus", "mp4", "wma"])
    def test_lossy_formats_return_true(self, fmt):
        assert is_lossy(fmt) is True

    @pytest.mark.parametrize("fmt", ["flac", "wav", "alac", "aiff", "aif", "ape", "wv"])
    def test_lossless_formats_return_false(self, fmt):
        assert is_lossy(fmt) is False

    def test_case_insensitive(self):
        assert is_lossy("MP3") is True
        assert is_lossy("FLAC") is False

    def test_unknown_format_returns_false(self):
        assert is_lossy("xyz") is False


# ── detect_format ─────────────────────────────────────────────────────────────


class TestDetectFormat:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            ("track.mp3", "mp3"),
            ("song.flac", "flac"),
            ("audio.ogg", "ogg"),
            ("music.m4a", "m4a"),
            ("pod.opus", "opus"),
            ("clip.wav", "wav"),
            ("hi.alac", "alac"),
            ("movie.mp4", "mp4"),
            ("notes.aiff", "aiff"),
            ("clip.aif", "aif"),
        ],
    )
    def test_known_formats_detected(self, filename, expected):
        assert detect_format(filename) == expected

    @pytest.mark.parametrize(
        "filename", ["doc.pdf", "image.jpg", "archive.zip", "notes.txt"]
    )
    def test_unknown_formats_return_none(self, filename):
        assert detect_format(filename) is None

    def test_case_insensitive(self):
        assert detect_format("Track.MP3") == "mp3"
        assert detect_format("Song.FLAC") == "flac"

    def test_no_extension_returns_none(self):
        assert detect_format("trackwithnoextension") is None

    def test_empty_string_returns_none(self):
        assert detect_format("") is None

    def test_path_with_directory(self):
        assert detect_format("/home/user/music/track.mp3") == "mp3"


# ── can_convert ───────────────────────────────────────────────────────────────


class TestCanConvert:
    @pytest.mark.parametrize(
        "src,dst",
        [
            ("mp3", "ogg"),
            ("mp3", "aac"),
            ("flac", "mp3"),
            ("flac", "ogg"),
            ("wav", "flac"),
            ("ogg", "m4a"),
            ("wav", "aiff"),
            ("flac", "aif"),
            ("aiff", "mp3"),
            ("flac", "mp4"),
            ("mp4", "ogg"),
        ],
    )
    def test_valid_conversions_return_true(self, src, dst):
        ok, msg = can_convert(src, dst)
        assert ok is True
        assert msg == "OK"

    @pytest.mark.parametrize(
        "src,dst",
        [
            ("mp3", "flac"),
            ("mp3", "wav"),
            ("mp3", "alac"),
            ("ogg", "flac"),
            ("aac", "wav"),
            ("mp4", "flac"),
            ("mp4", "aiff"),
        ],
    )
    def test_lossy_to_lossless_returns_false(self, src, dst):
        ok, msg = can_convert(src, dst)
        assert ok is False
        assert "lossy" in msg.lower()

    def test_returns_tuple(self):
        result = can_convert("mp3", "ogg")
        assert isinstance(result, tuple) and len(result) == 2

    def test_reason_is_string(self):
        _, reason = can_convert("mp3", "flac")
        assert isinstance(reason, str)

    @pytest.mark.parametrize(
        "fmt",
        [
            "mp3",
            "aac",
            "m4a",
            "ogg",
            "opus",
            "wma",
            "flac",
            "wav",
            "alac",
            "wv",
            "ape",
            "mp4",
            "aiff",
            "aif",
        ],
    )
    def test_same_format_always_rejected(self, fmt):
        """Converting a format to itself must be rejected — it's a no-op
        that also triggers FFmpeg's "Output same as Input" failure when
        output_dir defaults to input_dir (the common case with no output
        folder selected)."""
        ok, msg = can_convert(fmt, fmt)
        assert ok is False
        assert "same" in msg.lower()

    def test_same_format_rejected_case_insensitively(self):
        ok, _ = can_convert("MP3", "mp3")
        assert ok is False

    @pytest.mark.parametrize("src", ["flac", "wav", "alac", "wv"])
    def test_ape_output_always_rejected(self, src):
        """FFmpeg has no APE encoder; ape must never be a valid output,
        even from another lossless source where lossy/lossless rules
        would otherwise allow it."""
        ok, msg = can_convert(src, "ape")
        assert ok is False
        assert "ape" in msg.lower()

    def test_unsupported_output_formats_contains_ape(self):
        assert "ape" in UNSUPPORTED_OUTPUT_FORMATS

    def test_lossy_to_ape_rejected(self):
        ok, msg = can_convert("mp3", "ape")
        assert ok is False
        assert "ape" in msg.lower()


# ── available_output_formats ──────────────────────────────────────────────────


class TestAvailableOutputFormats:
    def test_lossy_input_excludes_lossless(self):
        outputs = available_output_formats("mp3")
        for fmt in LOSSLESS_FORMATS:
            assert fmt not in outputs, f"{fmt} should not appear for mp3 input"

    def test_lossy_input_excludes_self(self):
        assert "mp3" not in available_output_formats("mp3")

    def test_lossless_input_includes_all_except_self(self):
        outputs = available_output_formats("flac")
        assert "flac" not in outputs
        for fmt in ALL_FORMATS:
            if fmt in ("flac", "ape"):
                continue
            assert fmt in outputs

    def test_lossless_input_excludes_ape_output(self):
        """APE has no FFmpeg encoder; must never be offered as an output."""
        assert "ape" not in available_output_formats("flac")

    def test_lossy_input_returns_only_lossy(self):
        outputs = available_output_formats("ogg")
        for fmt in outputs:
            assert fmt in LOSSY_FORMATS

    def test_returns_list(self):
        assert isinstance(available_output_formats("mp3"), list)

    def test_nonempty_for_all_known_inputs(self):
        for fmt in ALL_FORMATS:
            assert len(available_output_formats(fmt)) > 0

    def test_ape_input_does_not_offer_ape_output(self):
        """APE input should still offer other lossless targets, never APE itself."""
        outputs = available_output_formats("ape")
        assert "ape" not in outputs
        assert len(outputs) > 0


# ── scan_input_directory ──────────────────────────────────────────────────────


class TestScanInputDirectory:
    def test_empty_string_returns_ok_with_all_formats(self):
        result = scan_input_directory("")
        assert result.ok is True
        assert set(result.output_formats) == set(ALL_OUTPUT_FORMATS)

    def test_nonexistent_dir_returns_ok_with_all_formats(self):
        result = scan_input_directory("/no/such/path/xyz")
        assert result.ok is True
        assert set(result.output_formats) == set(ALL_OUTPUT_FORMATS)

    def test_empty_directory_returns_ok_with_all_formats(self, tmp_path):
        result = scan_input_directory(str(tmp_path))
        assert result.ok is True
        assert set(result.output_formats) == set(ALL_OUTPUT_FORMATS)

    def test_fallback_output_formats_exclude_ape(self):
        """The 'no input scanned yet' fallback must never offer APE."""
        result = scan_input_directory("")
        assert "ape" not in result.output_formats

    def test_single_format_detected(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.mp3").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert result.ok is True
        assert result.input_format == "mp3"
        assert result.file_count == 2

    def test_lossless_input_offers_all_output_formats(self, tmp_path):
        (tmp_path / "a.flac").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert result.ok is True
        assert set(result.output_formats) == set(ALL_OUTPUT_FORMATS) - {"flac"}

    def test_flac_directory_never_offers_ape_output(self, tmp_path):
        (tmp_path / "a.flac").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert "ape" not in result.output_formats

    def test_lossy_input_offers_only_lossy_outputs(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        for fmt in result.output_formats:
            assert fmt in LOSSY_FORMATS

    def test_mixed_formats_returns_not_ok(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.flac").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert result.ok is False
        assert "mp3" in result.mixed_formats
        assert "flac" in result.mixed_formats

    def test_mixed_formats_returns_empty_output_formats(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.ogg").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert result.output_formats == []

    def test_non_audio_files_ignored(self, tmp_path):
        (tmp_path / "cover.jpg").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")
        (tmp_path / "track.mp3").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert result.ok is True
        assert result.file_count == 1

    def test_scan_error_returns_not_ok(self, tmp_path):
        from unittest.mock import patch

        with patch(
            "music_format_converter.core.formats.os.scandir",
            side_effect=PermissionError("denied"),
        ):
            result = scan_input_directory(str(tmp_path))
        assert result.ok is False
        assert result.error_message is not None

    def test_returns_scan_result_instance(self, tmp_path):
        result = scan_input_directory(str(tmp_path))
        assert isinstance(result, ScanResult)


# ── ScanResult.status_text ────────────────────────────────────────────────────


class TestScanResultStatusText:
    def test_ok_with_format_shows_count(self):
        r = ScanResult(
            ok=True, input_format="mp3", file_count=5, output_formats=["ogg"]
        )
        assert "5" in r.status_text
        assert "MP3" in r.status_text

    def test_ok_no_format_shows_no_audio_found(self):
        r = ScanResult(ok=True, output_formats=[])
        assert "No audio" in r.status_text

    def test_not_ok_with_mixed_shows_formats(self):
        r = ScanResult(ok=False, mixed_formats=["mp3", "flac"], output_formats=[])
        assert "mp3" in r.status_text or "flac" in r.status_text

    def test_not_ok_with_error_shows_message(self):
        r = ScanResult(ok=False, error_message="Permission denied", output_formats=[])
        assert "Permission denied" in r.status_text
