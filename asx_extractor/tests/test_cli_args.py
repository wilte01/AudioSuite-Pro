"""
Tests for asx_extractor.utils.cli_args
Gap: this module had zero test coverage — parse() and validate_args()
carry real branching logic (directory existence, mode whitelist,
argparse defaults/overrides) that was previously unverified.
"""

import pytest

from asx_extractor.utils.cli_args import ASXExtractorArgs, parse, validate_args

VALID_MODE_DRY = "Dry Run (Simulated)"
VALID_MODE_LIVE = "Execute Extraction (Permanent)"


# ── validate_args ────────────────────────────────────────────────────────


class TestValidateArgs:
    def test_no_errors_when_directory_and_mode_valid(self, tmp_path):
        args = ASXExtractorArgs(directory=str(tmp_path), mode=VALID_MODE_DRY)
        assert validate_args(args) == []

    def test_no_errors_when_directory_and_mode_none(self):
        args = ASXExtractorArgs(directory=None, mode=None)
        assert validate_args(args) == []

    def test_error_when_directory_does_not_exist(self, tmp_path):
        missing = tmp_path / "ghost"
        args = ASXExtractorArgs(directory=str(missing), mode=None)
        errors = validate_args(args)
        assert len(errors) == 1
        assert "does not exist" in errors[0]
        assert str(missing) in errors[0]

    def test_error_when_directory_is_a_file(self, tmp_path):
        f = tmp_path / "not_a_dir.txt"
        f.write_text("x")
        args = ASXExtractorArgs(directory=str(f), mode=None)
        errors = validate_args(args)
        assert len(errors) == 1
        assert "not a directory" in errors[0]

    def test_error_when_mode_invalid(self, tmp_path):
        args = ASXExtractorArgs(directory=str(tmp_path), mode="Bogus Mode")
        errors = validate_args(args)
        assert len(errors) == 1
        assert "Bogus Mode" in errors[0]

    def test_both_directory_and_mode_invalid_reports_both(self, tmp_path):
        missing = tmp_path / "ghost"
        args = ASXExtractorArgs(directory=str(missing), mode="Bogus Mode")
        errors = validate_args(args)
        assert len(errors) == 2

    def test_valid_dry_run_mode_accepted(self, tmp_path):
        args = ASXExtractorArgs(directory=str(tmp_path), mode=VALID_MODE_DRY)
        assert validate_args(args) == []

    def test_valid_live_mode_accepted(self, tmp_path):
        args = ASXExtractorArgs(directory=str(tmp_path), mode=VALID_MODE_LIVE)
        assert validate_args(args) == []

    def test_empty_string_directory_is_not_validated(self):
        # Falsy directory ("") must not trigger the existence check —
        # mirrors the `if args.directory:` guard in validate_args.
        args = ASXExtractorArgs(directory="", mode=None)
        assert validate_args(args) == []


# ── parse ─────────────────────────────────────────────────────────────────


class TestParse:
    def test_no_arguments_returns_defaults(self):
        args = parse([])
        assert args.directory is None
        assert args.mode is None
        assert args.auto_start is False
        assert args.auto_end is False

    def test_directory_positional_is_captured(self, tmp_path):
        args = parse([str(tmp_path)])
        assert args.directory == str(tmp_path)

    def test_mode_flag_is_captured(self, tmp_path):
        args = parse([str(tmp_path), "--mode", VALID_MODE_LIVE])
        assert args.mode == VALID_MODE_LIVE

    def test_start_flag_sets_auto_start_true(self):
        args = parse(["--start"])
        assert args.auto_start is True

    def test_no_start_flag_sets_auto_start_false(self):
        args = parse(["--start", "--no-start"])
        assert args.auto_start is False

    def test_end_flag_sets_auto_end_true(self):
        args = parse(["--end"])
        assert args.auto_end is True

    def test_no_end_flag_sets_auto_end_false(self):
        args = parse(["--end", "--no-end"])
        assert args.auto_end is False

    def test_all_flags_combined(self, tmp_path):
        args = parse([str(tmp_path), "--mode", VALID_MODE_DRY, "--start", "--end"])
        assert args.directory == str(tmp_path)
        assert args.mode == VALID_MODE_DRY
        assert args.auto_start is True
        assert args.auto_end is True

    def test_nonexistent_directory_raises_systemexit(self):
        with pytest.raises(SystemExit) as exc_info:
            parse(["/definitely/not/a/real/path/xyz123"])
        assert exc_info.value.code == 1

    def test_directory_that_is_a_file_raises_systemexit(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        with pytest.raises(SystemExit) as exc_info:
            parse([str(f)])
        assert exc_info.value.code == 1

    def test_invalid_mode_choice_rejected_by_argparse(self):
        # argparse's `choices=` enforcement fires before validate_args
        # ever runs, and exits with code 2 (its own usage-error code).
        with pytest.raises(SystemExit) as exc_info:
            parse(["--mode", "Not A Real Mode"])
        assert exc_info.value.code == 2

    def test_returns_asx_extractor_args_instance(self):
        assert isinstance(parse([]), ASXExtractorArgs)


class TestParseInvalidFolderPath:
    """Regression: parse() used to discard validation errors and exit
    silently with SystemExit(1). Errors must now reach stderr."""

    def test_nonexistent_folder_raises_systemexit(self):
        with pytest.raises(SystemExit) as exc_info:
            parse(["/definitely/not/a/real/path/xyz123"])
        assert exc_info.value.code == 1

    def test_nonexistent_folder_prints_error_to_stderr(self, capsys):
        missing = "/definitely/not/a/real/path/xyz123"
        with pytest.raises(SystemExit):
            parse([missing])
        captured = capsys.readouterr()
        assert "does not exist" in captured.err
        assert missing in captured.err

    def test_file_instead_of_directory_prints_error_to_stderr(self, tmp_path, capsys):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        with pytest.raises(SystemExit):
            parse([str(file_path)])
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_error_message_prefixed_with_tool_name(self, capsys):
        with pytest.raises(SystemExit):
            parse(["/definitely/not/a/real/path/xyz123"])
        captured = capsys.readouterr()
        assert "ASX Playlist Extractor:" in captured.err

    def test_nothing_printed_to_stdout_on_invalid_path(self, capsys):
        with pytest.raises(SystemExit):
            parse(["/definitely/not/a/real/path/xyz123"])
        captured = capsys.readouterr()
        assert captured.out == ""


# ── was_launched_from_driver + display-only driver flags ─────────────────────


class TestWasLaunchedFromDriver:
    def test_true_when_argv_has_arguments(self):
        from asx_extractor.utils.cli_args import was_launched_from_driver

        assert was_launched_from_driver(["script.py", "C:/music"]) is True

    def test_false_for_bare_argv(self):
        from asx_extractor.utils.cli_args import was_launched_from_driver

        assert was_launched_from_driver(["script.py"]) is False

    def test_false_for_empty_argv(self):
        from asx_extractor.utils.cli_args import was_launched_from_driver

        assert was_launched_from_driver([]) is False


class TestDriverDisplayFlags:
    def test_flags_default_false(self):
        args = ASXExtractorArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed(self, tmp_path):
        args = parse(
            [
                str(tmp_path),
                "--mode",
                VALID_MODE_DRY,
                "--start",
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
                str(tmp_path),
                "--mode",
                VALID_MODE_LIVE,
                "--no-start",
                "--no-end",
                "--no-clear-logs",
                "--no-parallel-run",
            ]
        )
        assert args.clear_logs is False
        assert args.parallel_run is False
