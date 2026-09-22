"""
Tests for replaygain_analyzer.utils.cli_args

Covers:
    - validate_args: shared folder path and target LUFS checks
    - parse: happy path argument assignment (unique layout — argv[2]
      carries the target LUFS value)
    - parse: invalid folder path exits with errors printed to stderr
      (regression — previously exited silently with no message anywhere)
"""

import pytest

from replaygain_analyzer.utils.cli_args import (
    ReplayGainArgs,
    parse,
    validate_args,
)

# ── validate_args ─────────────────────────────────────────────────────────────


class TestValidateArgs:
    def test_default_args_return_no_errors(self):
        assert validate_args(ReplayGainArgs()) == []

    def test_valid_directory_returns_no_errors(self, tmp_path):
        args = ReplayGainArgs(folder_path=str(tmp_path))
        assert validate_args(args) == []

    def test_nonexistent_folder_path_returns_error(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        args = ReplayGainArgs(folder_path=str(missing))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_file_path_instead_of_directory_returns_error(self, tmp_path):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        args = ReplayGainArgs(folder_path=str(file_path))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "not a directory" in errors[0]

    @pytest.mark.parametrize("lufs", [-30.0, -5.0, 0.0])
    def test_invalid_target_lufs_returns_error(self, lufs):
        args = ReplayGainArgs(target_lufs=lufs)
        errors = validate_args(args)
        assert any("LUFS" in e for e in errors)


# ── parse — happy path ────────────────────────────────────────────────────────


class TestParseHappyPath:
    def test_no_args_returns_defaults(self):
        args = parse([])
        assert args.folder_path == ""
        assert args.target_lufs == -16.0
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False

    def test_folder_path_set_from_argv_1(self, tmp_path):
        args = parse(["prog", str(tmp_path)])
        assert args.folder_path == str(tmp_path)

    def test_target_lufs_set_from_argv_2(self, tmp_path):
        args = parse(["prog", str(tmp_path), "-14.0"])
        assert args.target_lufs == -14.0

    def test_non_numeric_lufs_keeps_default(self, tmp_path):
        args = parse(["prog", str(tmp_path), "abc"])
        assert args.target_lufs == -16.0

    def test_live_flag_at_argv_3(self, tmp_path):
        args = parse(["prog", str(tmp_path), "-16.0", "--live"])
        assert args.live_mode is True

    def test_dry_flag_at_argv_3(self, tmp_path):
        args = parse(["prog", str(tmp_path), "-16.0", "--dry"])
        assert args.live_mode is False

    def test_start_flag_at_argv_4(self, tmp_path):
        args = parse(["prog", str(tmp_path), "-16.0", "--live", "--start"])
        assert args.auto_start is True

    def test_end_flag_at_argv_5(self, tmp_path):
        args = parse(["prog", str(tmp_path), "-16.0", "--live", "--start", "--end"])
        assert args.auto_end is True


# ── parse — invalid folder path (regression) ─────────────────────────────────


class TestParseInvalidFolderPath:
    def test_nonexistent_folder_raises_systemexit(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])

    def test_nonexistent_folder_prints_error_to_stderr(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert "does not exist" in captured.err
        assert str(missing) in captured.err

    def test_file_instead_of_directory_prints_error_to_stderr(self, tmp_path, capsys):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        with pytest.raises(SystemExit):
            parse(["prog", str(file_path)])
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_error_message_prefixed_with_tool_name(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert "ReplayGain Analyzer:" in captured.err

    def test_nothing_printed_to_stdout_on_invalid_path(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert captured.out == ""


class TestDriverDisplayFlags:
    """Clear Logs / Parallel handshake flags (argv[6]/argv[7])."""

    def test_flags_default_false(self):
        args = ReplayGainArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_parse_defaults_when_flags_absent(self, tmp_path):
        args = parse(["prog", str(tmp_path), "-16.0", "--dry"])
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_at_positions_6_and_7(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "-16.0",
                "--dry",
                "--no-start",
                "--end",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_negative_flags_parsed(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "-16.0",
                "--live",
                "--start",
                "--no-end",
                "--no-clear-logs",
                "--no-parallel-run",
            ]
        )
        assert args.clear_logs is False
        assert args.parallel_run is False


class TestApplyGainFlag:
    """--apply-gain / --no-apply-gain parsing (standalone-only flag)."""

    def test_default_is_false(self):
        args = ReplayGainArgs()
        assert args.apply_lossless_gain is False

    def test_apply_gain_flag_sets_true(self, tmp_path):
        args = parse(["prog", str(tmp_path), "-16.0", "--apply-gain"])
        assert args.apply_lossless_gain is True

    def test_no_apply_gain_flag_sets_false(self, tmp_path):
        args = parse(
            ["prog", str(tmp_path), "-16.0", "--apply-gain", "--no-apply-gain"]
        )
        assert args.apply_lossless_gain is False

    def test_apply_gain_at_any_position(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--apply-gain", "-16.0", "--live"])
        assert args.apply_lossless_gain is True

    def test_absent_flag_keeps_default(self, tmp_path):
        args = parse(["prog", str(tmp_path), "-16.0", "--live", "--start"])
        assert args.apply_lossless_gain is False

    def test_multiple_flags_last_wins(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "-16.0",
                "--apply-gain",
                "--no-apply-gain",
                "--apply-gain",
            ]
        )
        assert args.apply_lossless_gain is True
