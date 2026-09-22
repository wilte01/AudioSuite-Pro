"""
tests/test_cli_args.py
Unit tests for tempo_analyzer.utils.cli_args.

audio_suite_shared is stubbed via conftest.py.
"""

import pytest

from tempo_analyzer.utils.cli_args import (
    CLIValidationError,
    TempoAnalyzerArgs,
    parse,
)

# parse — argument mapping


class TestParse:
    def test_returns_empty_args_when_no_argv(self):
        result = parse(["script.py"])
        assert isinstance(result, TempoAnalyzerArgs)

    def test_folder_path_mapped_from_argv1(self, tmp_path):
        music_dir = str(tmp_path)
        result = parse(["script.py", music_dir])
        assert result.folder_path == music_dir

    def test_live_flag_sets_live_mode_true(self, tmp_path):
        result = parse(["script.py", str(tmp_path), "--live"])
        assert result.live_mode is True

    def test_dry_flag_sets_live_mode_false(self, tmp_path):
        result = parse(["script.py", str(tmp_path), "--dry"])
        assert result.live_mode is False

    def test_start_flag_sets_auto_start_true(self, tmp_path):
        result = parse(["script.py", str(tmp_path), "--start"])
        assert result.auto_start is True

    def test_no_start_flag_sets_auto_start_false(self, tmp_path):
        result = parse(["script.py", str(tmp_path), "--no-start"])
        assert result.auto_start is False

    def test_end_flag_sets_auto_end_true(self, tmp_path):
        result = parse(["script.py", str(tmp_path), "--end"])
        assert result.auto_end is True

    def test_no_end_flag_sets_auto_end_false(self, tmp_path):
        result = parse(["script.py", str(tmp_path), "--no-end"])
        assert result.auto_end is False

    def test_scheme_flag_captured(self, tmp_path):
        result = parse(["script.py", str(tmp_path), "--scheme", "English"])
        assert result.scheme == "English"

    def test_scheme_defaults_to_none_when_absent(self, tmp_path):
        result = parse(["script.py", str(tmp_path)])
        assert result.scheme is None

    def test_unknown_flags_ignored_without_raising(self, tmp_path):
        music_dir = str(tmp_path)
        result = parse(["script.py", music_dir, "--unknown-flag"])
        assert result.folder_path == music_dir

    def test_scheme_flag_without_value_ignored(self, tmp_path):
        """--scheme as final arg with no following value must not crash."""
        result = parse(["script.py", str(tmp_path), "--scheme"])
        assert result.scheme is None


# parse — validation failures raise CLIValidationError (not SystemExit)


class TestParseRaisesOnInvalidArgs:
    def test_invalid_folder_raises_cli_validation_error(self, tmp_path):
        bad = str(tmp_path / "nonexistent_folder")
        with pytest.raises(CLIValidationError):
            parse(["script.py", bad])

    def test_does_not_raise_system_exit(self, tmp_path):
        bad = str(tmp_path / "nonexistent_folder")
        with pytest.raises(CLIValidationError):
            parse(["script.py", bad])
        # If SystemExit bubbled up pytest would report an error, not a pass


# CLIValidationError type


class TestCLIValidationError:
    def test_is_subclass_of_value_error(self):
        assert issubclass(CLIValidationError, ValueError)

    def test_is_the_shared_exception_type(self):
        """The local name must be a re-export of the shared class so the
        launcher's single except-clause catches tempo_analyzer failures."""
        from audio_suite_shared.cli_dataclasses import (
            CLIValidationError as SharedCLIValidationError,
        )

        assert CLIValidationError is SharedCLIValidationError

    def test_carries_message(self):
        exc = CLIValidationError("folder not found")
        assert "folder not found" in str(exc)


class TestDriverDisplayFlags:
    def test_flags_default_false(self):
        args = TempoAnalyzerArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed(self, tmp_path):
        result = parse(
            [
                "script.py",
                str(tmp_path),
                "--dry",
                "--start",
                "--end",
                "--scheme",
                "English",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert result.clear_logs is True
        assert result.parallel_run is True
        assert result.scheme == "English"

    def test_negative_flags_parsed(self, tmp_path):
        result = parse(
            [
                "script.py",
                str(tmp_path),
                "--live",
                "--no-start",
                "--no-end",
                "--no-clear-logs",
                "--no-parallel-run",
            ]
        )
        assert result.clear_logs is False
        assert result.parallel_run is False
