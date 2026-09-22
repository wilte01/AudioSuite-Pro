"""
test_cli_args.py
Tests for mood_analysis_batch_tagger.utils.cli_args: parse(), validate_args(),
MoodAnalysisBatchTaggerArgs and was_launched_from_driver().
"""

import pytest

from mood_analysis_batch_tagger.utils.cli_args import (
    MoodAnalysisBatchTaggerArgs,
    parse,
    validate_args,
    was_launched_from_driver,
)


class TestDefaults:
    def test_dataclass_defaults(self) -> None:
        args = MoodAnalysisBatchTaggerArgs()
        assert args.folder_path == ""
        assert args.analysis_duration == 90
        assert args.parallel_mode is False
        assert args.max_workers == 4
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_bare_argv_returns_defaults(self) -> None:
        args = parse(["prog"])
        assert args.folder_path == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False

    def test_empty_argv_returns_defaults(self) -> None:
        args = parse([])
        assert args.folder_path == ""


class TestParsePositional:
    def test_folder_path_from_argv1(self, tmp_path) -> None:
        args = parse(["prog", str(tmp_path)])
        assert args.folder_path == str(tmp_path)


class TestParseModeFlags:
    def test_dry_flag(self, tmp_path) -> None:
        assert parse(["prog", str(tmp_path), "--dry"]).live_mode is False

    def test_live_flag(self, tmp_path) -> None:
        assert parse(["prog", str(tmp_path), "--live"]).live_mode is True

    def test_dry_overrides_live(self, tmp_path) -> None:
        args = parse(["prog", str(tmp_path), "--live", "--dry"])
        assert args.live_mode is False


class TestParseDurationWorkers:
    def test_duration(self, tmp_path) -> None:
        args = parse(["prog", str(tmp_path), "--duration", "45"])
        assert args.analysis_duration == 45

    def test_duration_invalid_int_keeps_default(self, tmp_path) -> None:
        args = parse(["prog", str(tmp_path), "--duration", "abc"])
        assert args.analysis_duration == 90

    def test_parallel_flag(self, tmp_path) -> None:
        assert parse(["prog", str(tmp_path), "--parallel"]).parallel_mode is True

    def test_no_parallel_flag(self, tmp_path) -> None:
        args = parse(["prog", str(tmp_path), "--parallel", "--no-parallel"])
        assert args.parallel_mode is False

    def test_workers(self, tmp_path) -> None:
        assert parse(["prog", str(tmp_path), "--workers", "8"]).max_workers == 8


class TestParseStartEndFlags:
    def test_start_and_end(self, tmp_path) -> None:
        args = parse(["prog", str(tmp_path), "--start", "--end"])
        assert args.auto_start is True
        assert args.auto_end is True

    def test_no_start_no_end(self, tmp_path) -> None:
        args = parse(
            ["prog", str(tmp_path), "--start", "--end", "--no-start", "--no-end"]
        )
        assert args.auto_start is False
        assert args.auto_end is False


class TestDriverDisplayFlags:
    def test_positive_flags_parsed(self, tmp_path) -> None:
        args = parse(["prog", str(tmp_path), "--clear-logs", "--parallel-run"])
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_negative_flags_parsed(self, tmp_path) -> None:
        args = parse(["prog", str(tmp_path), "--no-clear-logs", "--no-parallel-run"])
        assert args.clear_logs is False
        assert args.parallel_run is False


class TestValidateArgs:
    def test_valid_directory(self, tmp_path) -> None:
        assert (
            validate_args(MoodAnalysisBatchTaggerArgs(folder_path=str(tmp_path))) == []
        )

    def test_nonexistent_directory(self) -> None:
        errors = validate_args(MoodAnalysisBatchTaggerArgs(folder_path="Z:/no/such"))
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_file_not_directory(self, tmp_path) -> None:
        f = tmp_path / "a.txt"
        f.write_text("x")
        errors = validate_args(MoodAnalysisBatchTaggerArgs(folder_path=str(f)))
        assert len(errors) == 1
        assert "not a directory" in errors[0]

    def test_duration_too_short(self, tmp_path) -> None:
        errors = validate_args(
            MoodAnalysisBatchTaggerArgs(folder_path=str(tmp_path), analysis_duration=5)
        )
        assert len(errors) == 1
        assert "10-600" in errors[0]

    def test_duration_too_long(self, tmp_path) -> None:
        errors = validate_args(
            MoodAnalysisBatchTaggerArgs(
                folder_path=str(tmp_path), analysis_duration=900
            )
        )
        assert len(errors) == 1

    def test_parse_exits_on_invalid_folder(self) -> None:
        with pytest.raises(SystemExit):
            parse(["prog", "Z:/no/such"])

    def test_parse_exits_on_invalid_duration(self, tmp_path) -> None:
        with pytest.raises(SystemExit):
            parse(["prog", str(tmp_path), "--duration", "5"])


class TestWasLaunchedFromDriver:
    def test_true_when_argv_has_arguments(self) -> None:
        assert was_launched_from_driver(["script.py", "C:/music"]) is True

    def test_false_for_bare_argv(self) -> None:
        assert was_launched_from_driver(["script.py"]) is False

    def test_false_for_empty_argv(self) -> None:
        assert was_launched_from_driver([]) is False
