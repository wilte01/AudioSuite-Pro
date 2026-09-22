"""
Tests for music_format_converter.utils.cli_args
Covers: parse(), validate_args(), ConverterArgs dataclass
"""

import sys

import pytest

from music_format_converter.utils.cli_args import ConverterArgs, parse, validate_args

# ═════════════════════════════════════════════════════════════════════════════
# validate_args
# ═════════════════════════════════════════════════════════════════════════════


class TestValidateArgs:
    def test_empty_args_returns_no_errors(self):
        assert validate_args(ConverterArgs()) == []

    def test_valid_existing_folder_no_error(self, tmp_path):
        args = ConverterArgs(folder_path=str(tmp_path))
        assert validate_args(args) == []

    def test_nonexistent_folder_returns_error(self):
        args = ConverterArgs(folder_path="/no/such/path/xyz")
        errors = validate_args(args)
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_file_path_as_folder_returns_error(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"x")
        args = ConverterArgs(folder_path=str(f))
        errors = validate_args(args)
        assert any("not a directory" in e for e in errors)

    def test_valid_output_format_no_error(self):
        args = ConverterArgs(output_format="mp3")
        assert validate_args(args) == []

    def test_invalid_output_format_returns_error(self):
        args = ConverterArgs(output_format="xyz")
        errors = validate_args(args)
        assert any("Invalid output format" in e for e in errors)

    def test_valid_quality_values_accepted(self):
        for q in ("highest", "high", "medium", "low"):
            args = ConverterArgs(quality=q)
            assert validate_args(args) == [], f"Quality '{q}' should be valid"

    def test_invalid_quality_returns_error(self):
        args = ConverterArgs(quality="ultra")
        errors = validate_args(args)
        assert any("Invalid quality" in e for e in errors)

    def test_valid_output_dir_no_error(self, tmp_path):
        args = ConverterArgs(output_dir=str(tmp_path))
        assert validate_args(args) == []

    def test_valid_sample_rate_values_accepted(self):
        for sr in ("source", "44100", "48000", "88200", "96000", "176400", "192000"):
            args = ConverterArgs(sample_rate=sr)
            assert validate_args(args) == [], f"Sample rate '{sr}' should be valid"

    def test_invalid_sample_rate_returns_error(self):
        args = ConverterArgs(sample_rate="12345")
        errors = validate_args(args)
        assert any("Invalid sample rate" in e for e in errors)

    def test_valid_bit_depth_values_accepted(self):
        for bd in ("auto", "16", "24", "32", "float"):
            args = ConverterArgs(bit_depth=bd)
            assert validate_args(args) == [], f"Bit depth '{bd}' should be valid"

    def test_invalid_bit_depth_returns_error(self):
        args = ConverterArgs(bit_depth="64")
        errors = validate_args(args)
        assert any("Invalid bit depth" in e for e in errors)

    def test_nonexistent_output_dir_returns_error(self):
        args = ConverterArgs(output_dir="/no/such/output")
        errors = validate_args(args)
        assert any("does not exist" in e for e in errors)

    def test_file_as_output_dir_returns_error(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_bytes(b"x")
        args = ConverterArgs(output_dir=str(f))
        errors = validate_args(args)
        assert any("not a directory" in e for e in errors)

    def test_delete_originals_with_output_dir_no_error(self, tmp_path):
        """
        Regression: delete_originals + output_dir together used to be
        rejected here (cli_args.py) even though file_processor.py's delete
        step removes the source file independent of where the converted
        output lands -- the restriction had no basis in the processing
        code. It has been removed; this combination is a legitimate
        "convert elsewhere, clean up source" workflow.
        """
        args = ConverterArgs(delete_originals=True, output_dir=str(tmp_path))
        assert validate_args(args) == []

    def test_delete_originals_without_output_dir_no_error(self):
        args = ConverterArgs(delete_originals=True)
        assert validate_args(args) == []

    def test_returns_list(self):
        assert isinstance(validate_args(ConverterArgs()), list)

    def test_multiple_errors_returned_together(self):
        args = ConverterArgs(
            folder_path="/no/such/path",
            output_format="xyz",
        )
        errors = validate_args(args)
        assert len(errors) >= 2


# ═════════════════════════════════════════════════════════════════════════════
# parse()
# ═════════════════════════════════════════════════════════════════════════════


class TestParse:
    def test_no_args_returns_empty_converter_args(self):
        result = parse(["prog"])
        assert isinstance(result, ConverterArgs)
        # BaseCLIArgs.folder_path defaults to "" (empty string), not None â€”
        # this is the shared convention used across all AudioSuite-Pro
        # tools built on BaseCLIArgs (see audio_suite_shared.cli_dataclasses).
        assert result.folder_path == ""

    def test_positional_folder_path(self, tmp_path):
        result = parse(["prog", str(tmp_path)])
        assert result.folder_path == str(tmp_path)

    def test_positional_output_format_valid(self, tmp_path):
        result = parse(["prog", str(tmp_path), "mp3"])
        assert result.output_format == "mp3"

    def test_positional_output_format_with_dot(self, tmp_path):
        result = parse(["prog", str(tmp_path), ".flac"])
        assert result.output_format == "flac"

    def test_positional_output_format_invalid_ignored(self, tmp_path):
        result = parse(["prog", str(tmp_path), "xyz"])
        assert result.output_format is None

    def test_start_flag_sets_auto_start(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--start"])
        assert result.auto_start is True

    def test_dry_flag_sets_live_mode_false(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--dry"])
        assert result.live_mode is False

    def test_live_flag_sets_live_mode_true(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--live"])
        assert result.live_mode is True

    def test_quality_flag_highest(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--quality", "highest"])
        assert result.quality == "highest"

    def test_quality_flag_invalid_ignored(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--quality", "ultra"])
        assert result.quality is None

    def test_sample_rate_flag_parsed(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--sample-rate", "48000"])
        assert result.sample_rate == "48000"

    def test_sample_rate_flag_invalid_ignored(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--sample-rate", "12345"])
        assert result.sample_rate is None

    def test_bit_depth_flag_parsed(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--bit-depth", "24"])
        assert result.bit_depth == "24"

    def test_bit_depth_flag_invalid_ignored(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--bit-depth", "64"])
        assert result.bit_depth is None

    def test_sample_rate_and_bit_depth_flags_combined(self, tmp_path):
        result = parse(
            [
                "prog",
                str(tmp_path),
                "--sample-rate",
                "96000",
                "--bit-depth",
                "float",
                "--quality",
                "high",
            ]
        )
        assert result.sample_rate == "96000"
        assert result.bit_depth == "float"
        assert result.quality == "high"

    def test_flags_default_to_source_and_auto(self, tmp_path):
        result = parse(["prog", str(tmp_path)])
        assert result.sample_rate is None
        assert result.bit_depth is None

    def test_delete_originals_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--delete-originals"])
        assert result.delete_originals is True

    def test_output_dir_flag(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        result = parse(["prog", str(tmp_path), "--output-dir", str(out)])
        assert result.output_dir == str(out)

    def test_unknown_flag_ignored(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--unknown-flag"])
        assert result.folder_path == str(tmp_path)

    def test_invalid_args_raises_system_exit(self):
        with pytest.raises(SystemExit):
            parse(["prog", "/no/such/path/xyz"])

    def test_delete_originals_with_output_dir_parses_without_error(self, tmp_path):
        """Regression: this combination previously hit validate_args()'s
        removed mutual-exclusion rule and raised SystemExit(1)."""
        out = tmp_path / "out"
        out.mkdir()
        result = parse(
            [
                "prog",
                str(tmp_path),
                "--delete-originals",
                "--output-dir",
                str(out),
            ]
        )
        assert result.delete_originals is True
        assert result.output_dir == str(out)

    # ── Regression: flag immediately after folder path (no output-format
    # positional given) must still be recognized, not silently dropped. ──

    def test_start_flag_at_position_two_recognized(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--start"])
        assert result.auto_start is True
        assert result.output_format is None

    def test_live_flag_at_position_two_recognized(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--live"])
        assert result.live_mode is True

    def test_quality_flag_at_position_two_recognized(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--quality", "high"])
        assert result.quality == "high"

    def test_delete_originals_flag_at_position_two_recognized(self, tmp_path):
        result = parse(["prog", str(tmp_path), "--delete-originals"])
        assert result.delete_originals is True

    def test_output_dir_flag_at_position_two_recognized(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        result = parse(["prog", str(tmp_path), "--output-dir", str(out)])
        assert result.output_dir == str(out)

    def test_multiple_flags_with_no_format_all_recognized(self, tmp_path):
        """All flags should be recognized together when no output-format
        positional is supplied — none should be skipped due to position."""
        result = parse(["prog", str(tmp_path), "--start", "--live"])
        assert result.auto_start is True
        assert result.live_mode is True
        assert result.output_format is None

    def test_no_argv_uses_sys_argv(self, tmp_path, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog", str(tmp_path)])
        result = parse()
        assert result.folder_path == str(tmp_path)


class TestParseInvalidFolderPath:
    """Regression: parse() used to discard validation errors and exit
    silently with SystemExit(1). Errors must now reach stderr."""

    def test_nonexistent_folder_raises_systemexit(self):
        with pytest.raises(SystemExit):
            parse(["prog", "/no/such/path/xyz"])

    def test_nonexistent_folder_prints_error_to_stderr(self, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", "/no/such/path/xyz"])
        captured = capsys.readouterr()
        assert "does not exist" in captured.err
        assert "/no/such/path/xyz" in captured.err

    def test_file_instead_of_directory_prints_error_to_stderr(self, tmp_path, capsys):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        with pytest.raises(SystemExit):
            parse(["prog", str(file_path)])
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_invalid_output_dir_prints_error_to_stderr(self, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", "--output-dir", "/no/such/output/dir"])
        captured = capsys.readouterr()
        assert "does not exist" in captured.err

    def test_error_message_prefixed_with_tool_name(self, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", "/no/such/path/xyz"])
        captured = capsys.readouterr()
        assert "Music Format Converter:" in captured.err

    def test_nothing_printed_to_stdout_on_invalid_path(self, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", "/no/such/path/xyz"])
        captured = capsys.readouterr()
        assert captured.out == ""


class TestDriverDisplayFlags:
    def test_flags_default_false(self):
        args = ConverterArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "--dry",
                "--start",
                "--quality",
                "high",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.clear_logs is True
        assert args.parallel_run is True
        assert args.quality == "high"

    def test_negative_flags_parsed(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "--live",
                "--no-clear-logs",
                "--no-parallel-run",
            ]
        )
        assert args.clear_logs is False
        assert args.parallel_run is False


class TestAutoEndFlag:
    def test_end_flag_sets_auto_end(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--start", "--end"])
        assert args.auto_end is True

    def test_no_end_flag_clears_auto_end(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--start", "--end", "--no-end"])
        assert args.auto_end is False


class TestNormalizeMp3Flag:
    def test_flags_default_false(self):
        args = ConverterArgs()
        assert args.normalize_mp3 is False
        assert args.target_lufs == -16.0

    def test_normalize_flag_parsed(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--normalize-mp3"])
        assert args.normalize_mp3 is True

    def test_target_lufs_parsed(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--normalize-mp3", "--target-lufs", "-14"])
        assert args.normalize_mp3 is True
        assert args.target_lufs == -14.0

    def test_target_lufs_flag_alone(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--target-lufs", "-12.5"])
        assert args.target_lufs == -12.5

    def test_invalid_target_lufs_keeps_default(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--target-lufs", "not-a-number"])
        assert args.target_lufs == -16.0

    def test_position_two_flags_recognized(self, tmp_path):
        """--normalize-mp3 immediately after the folder is a valid layout."""
        args = parse(["prog", str(tmp_path), "--normalize-mp3"])
        assert args.normalize_mp3 is True
