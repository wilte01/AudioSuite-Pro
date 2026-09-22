"""
Tests for key_detector.utils.cli_args

Covers:
    - validate_args: folder path and analysis duration range checks
    - parse: happy path argument assignment
    - parse: invalid folder path exits with errors printed to stderr
      (regression — previously exited silently with no message anywhere)
"""

import pytest

from key_detector.utils.cli_args import KeyDetectorArgs, parse, validate_args

# ── validate_args ─────────────────────────────────────────────────────────────


class TestValidateArgs:
    def test_no_folder_path_returns_no_errors(self):
        assert validate_args(KeyDetectorArgs()) == []

    def test_valid_directory_returns_no_errors(self, tmp_path):
        args = KeyDetectorArgs(folder_path=str(tmp_path))
        assert validate_args(args) == []

    def test_nonexistent_folder_path_returns_error(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        args = KeyDetectorArgs(folder_path=str(missing))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_file_path_instead_of_directory_returns_error(self, tmp_path):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        args = KeyDetectorArgs(folder_path=str(file_path))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "not a directory" in errors[0]

    @pytest.mark.parametrize("duration", [5, 9, 601, 1000])
    def test_duration_out_of_range_returns_error(self, duration):
        args = KeyDetectorArgs(analysis_duration=duration)
        errors = validate_args(args)
        assert any("duration" in e.lower() for e in errors)

    @pytest.mark.parametrize("duration", [10, 600])
    def test_duration_at_boundaries_passes(self, duration):
        args = KeyDetectorArgs(analysis_duration=duration)
        assert validate_args(args) == []


# ── parse — happy path ────────────────────────────────────────────────────────


class TestParseHappyPath:
    def test_no_args_returns_defaults(self):
        args = parse([])
        assert args.folder_path == ""
        assert args.analysis_duration == 90
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False

    def test_folder_path_set_from_argv_1(self, tmp_path):
        args = parse(["prog", str(tmp_path)])
        assert args.folder_path == str(tmp_path)

    def test_duration_named_pair_captured(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "ignored",
                "--live",
                "--start",
                "--end",
                "--duration",
                "120",
            ]
        )
        assert args.analysis_duration == 120

    def test_non_numeric_duration_keeps_default(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "ignored",
                "--live",
                "--start",
                "--end",
                "--duration",
                "abc",
            ]
        )
        assert args.analysis_duration == 90

    def test_live_flag_at_argv_3(self, tmp_path):
        args = parse(["prog", str(tmp_path), "ignored", "--live"])
        assert args.live_mode is True

    def test_dry_flag_at_argv_3(self, tmp_path):
        args = parse(["prog", str(tmp_path), "ignored", "--dry"])
        assert args.live_mode is False

    def test_start_flag_at_argv_4(self, tmp_path):
        args = parse(["prog", str(tmp_path), "ignored", "--live", "--start"])
        assert args.auto_start is True

    def test_end_flag_at_argv_5(self, tmp_path):
        args = parse(["prog", str(tmp_path), "ignored", "--live", "--start", "--end"])
        assert args.auto_end is True

    def test_parallel_and_workers_named_pairs(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "ignored",
                "--live",
                "--start",
                "--end",
                "--parallel",
                "--workers",
                "8",
            ]
        )
        assert args.parallel_mode is True
        assert args.max_workers == 8


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
        assert "Key Detector:" in captured.err

    def test_nothing_printed_to_stdout_on_invalid_path(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert captured.out == ""


class TestDriverDisplayFlags:
    def test_flags_default_false(self):
        args = KeyDetectorArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed_after_named_pairs(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "ignored",
                "--dry",
                "--start",
                "--end",
                "--duration",
                "45",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.clear_logs is True
        assert args.parallel_run is True
        assert args.analysis_duration == 45

    def test_negative_flags_parsed(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "ignored",
                "--live",
                "--no-start",
                "--no-end",
                "--no-clear-logs",
                "--no-parallel-run",
            ]
        )
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_worker_parallel_flag_still_distinct_from_parallel_run(self, tmp_path):
        """Key Detector's tool-specific --parallel must keep its own meaning."""
        args = parse(
            [
                "prog",
                str(tmp_path),
                "ignored",
                "--dry",
                "--start",
                "--end",
                "--parallel",
                "--workers",
                "8",
                "--parallel-run",
            ]
        )
        assert args.parallel_mode is True
        assert args.max_workers == 8
        assert args.parallel_run is True
