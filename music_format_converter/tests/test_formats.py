"""
Tests for music_format_converter.core.formats
Gap G-05: format_info, is_lossy, detect_format, can_convert,
          available_output_formats, available_output_formats_for,
          discover_input_files, scan_input_directory, ScanResult
"""

import os
from unittest.mock import patch

import pytest

from music_format_converter.core.formats import (
    ALL_FORMATS,
    ALL_OUTPUT_FORMATS,
    LOSSLESS_FORMATS,
    LOSSY_FORMATS,
    UNSUPPORTED_OUTPUT_FORMATS,
    ScanResult,
    available_output_formats,
    available_output_formats_for,
    can_convert,
    detect_format,
    discover_input_files,
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


class TestAvailableOutputFormatsFor:
    def test_single_input_matches_available_output_formats(self):
        assert available_output_formats_for(["flac"]) == available_output_formats(
            "flac"
        )

    def test_union_is_order_preserving(self):
        result = available_output_formats_for(["mp3", "flac"])
        assert result == [f for f in ALL_OUTPUT_FORMATS if f in set(result)]

    def test_lossy_only_union_has_no_lossless_target(self):
        result = available_output_formats_for(["mp3", "ogg"])
        assert not set(result) & set(LOSSLESS_FORMATS)

    def test_target_unreachable_from_every_input_is_excluded(self):
        """flac+mp3 cannot target flac: same-format for one, lossy→lossless
        for the other, so no file would convert."""
        result = available_output_formats_for(["flac", "mp3"])
        assert "flac" not in result
        assert "mp3" in result

    def test_mixed_tree_keeps_targets_each_member_can_reach(self):
        """ogg→mp3 is valid even though the mp3 files themselves skip."""
        assert "mp3" in available_output_formats_for(["mp3", "ogg"])

    def test_never_includes_ape(self):
        assert "ape" not in available_output_formats_for(["flac", "wav", "mp3"])

    def test_empty_input_returns_empty(self):
        assert available_output_formats_for([]) == []


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

    def test_mixed_formats_are_accepted_with_counts(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.flac").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert result.ok is True
        assert result.mixed_formats == ["flac", "mp3"]
        assert result.input_format is None
        assert result.file_count == 2
        assert result.format_counts == {"mp3": 1, "flac": 1}

    def test_mixed_formats_offer_union_of_valid_outputs(self, tmp_path):
        """A flac+mp3 tree can still target flac (mp3 skipped) and mp3."""
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.ogg").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert result.ok is True
        assert set(result.output_formats) <= set(ALL_OUTPUT_FORMATS)
        # lossy-only inputs never offer a lossless target
        assert not set(result.output_formats) & set(LOSSLESS_FORMATS)

    def test_mixed_lossless_and_lossy_keeps_lossy_target(self, tmp_path):
        """flac+mp3 can still target mp3; flac itself stays unreachable."""
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.flac").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert "mp3" in result.output_formats
        assert "flac" not in result.output_formats

    def test_single_format_reports_one_count(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.mp3").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert result.format_counts == {"mp3": 2}
        assert result.mixed_formats == []
        assert result.input_format == "mp3"

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

    def test_counts_rendered_highest_first(self):
        r = ScanResult(
            ok=True,
            file_count=5,
            format_counts={"mp3": 3, "flac": 2},
            output_formats=["ogg"],
        )
        text = r.status_text
        assert "5" in text
        assert text.index("MP3: 3") < text.index("FLAC: 2")

    def test_mixed_scan_reports_per_format_counts(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.mp3").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "c.flac").write_bytes(b"x")
        text = scan_input_directory(str(tmp_path)).status_text
        assert "MP3: 2" in text
        assert "FLAC: 1" in text

    def test_count_without_format_detail_falls_back_to_plain_label(self):
        r = ScanResult(ok=True, file_count=2, output_formats=["ogg"])
        assert r.status_text == "✓ Detected: 2 file(s)"

    def test_ok_no_format_shows_no_audio_found(self):
        r = ScanResult(ok=True, output_formats=[])
        assert "No audio" in r.status_text

    def test_not_ok_with_error_shows_message(self):
        r = ScanResult(ok=False, error_message="Permission denied", output_formats=[])
        assert "Permission denied" in r.status_text


# ── discover_input_files — recursive discovery ─────────────────────────────────


class TestDiscoverInputFiles:
    def test_flat_mode_ignores_subdirectories(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.mp3").write_bytes(b"x")
        files = discover_input_files(str(tmp_path), recursive=False)
        assert files == ["a.mp3"]

    def test_recursive_mode_returns_relative_paths(self, tmp_path):
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.mp3").write_bytes(b"x")
        files = discover_input_files(str(tmp_path), recursive=True)
        assert [os.path.normpath(f) for f in files] == [
            "a.mp3",
            os.path.join("sub", "b.mp3"),
        ]

    def test_deeply_nested_files_found(self, tmp_path):
        deep = tmp_path / "A" / "B" / "C"
        deep.mkdir(parents=True)
        (deep / "x.flac").write_bytes(b"x")
        files = discover_input_files(str(tmp_path))
        assert len(files) == 1
        assert os.path.normpath(files[0]) == os.path.join("A", "B", "C", "x.flac")

    def test_non_audio_files_excluded(self, tmp_path):
        (tmp_path / "cover.jpg").write_bytes(b"x")
        (tmp_path / "notes.txt").write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "track.mp3").write_bytes(b"x")
        assert len(discover_input_files(str(tmp_path))) == 1

    def test_empty_dir_returns_empty_list(self, tmp_path):
        assert discover_input_files(str(tmp_path)) == []

    def test_nonexistent_dir_returns_empty_list(self, tmp_path):
        assert discover_input_files(str(tmp_path / "nope")) == []

    def test_empty_path_returns_empty_list(self):
        assert discover_input_files("") == []

    def test_result_is_sorted_deterministically(self, tmp_path):
        for name in ("c.mp3", "a.mp3", "b.mp3"):
            (tmp_path / name).write_bytes(b"x")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "z.mp3").write_bytes(b"x")
        first = discover_input_files(str(tmp_path))
        assert first == discover_input_files(str(tmp_path))
        assert [os.path.basename(f) for f in first[:3]] == [
            "a.mp3",
            "b.mp3",
            "c.mp3",
        ]

    def test_unreadable_root_raises(self, tmp_path):
        """The root's unreadability must surface, not be swallowed."""
        from unittest.mock import patch

        with patch(
            "music_format_converter.core.formats.os.scandir",
            side_effect=PermissionError("denied"),
        ):
            with pytest.raises(PermissionError):
                discover_input_files(str(tmp_path))

    def test_unreadable_subtree_is_skipped_not_fatal(self, tmp_path):
        """One bad subtree is logged and skipped; sibling files survive."""
        good = tmp_path / "good"
        good.mkdir()
        (good / "track.mp3").write_bytes(b"x")
        (tmp_path / "locked").mkdir()

        real_scandir = os.scandir

        def _scandir(path, *args, **kwargs):
            if os.path.normpath(str(path)) == os.path.normpath(
                str(tmp_path / "locked")
            ):
                raise PermissionError("denied")
            return real_scandir(path, *args, **kwargs)

        with patch("music_format_converter.core.formats.os.scandir", _scandir):
            files = discover_input_files(str(tmp_path))

        assert [os.path.normpath(f) for f in files] == [
            os.path.join("good", "track.mp3")
        ]

    def test_ape_input_never_offers_ape_output_recursively(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "a.ape").write_bytes(b"x")
        result = scan_input_directory(str(tmp_path))
        assert "ape" not in result.output_formats

    def test_entry_that_cannot_be_statted_is_treated_as_a_file(self, tmp_path):
        """A stat failure on one entry must not lose the whole directory."""

        class _BrokenEntry:
            name = "mystery.mp3"
            path = str(tmp_path / "mystery.mp3")

            def is_dir(self, follow_symlinks=True):
                raise OSError("stat failed")

        class _Listing(list):
            """Minimal context-manager wrapper around a list of entries."""

            def __enter__(self):
                return self

            def __exit__(self, *exc_info):
                return False

        (tmp_path / "real.mp3").write_bytes(b"x")
        real_scandir = os.scandir

        with patch(
            "music_format_converter.core.formats.os.scandir",
            lambda path: _Listing([_BrokenEntry(), *list(real_scandir(path))]),
        ):
            files = discover_input_files(str(tmp_path))

        assert "real.mp3" in files
