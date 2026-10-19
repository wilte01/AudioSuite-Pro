"""
Tests for silence_trimmer.utils.cli_args

Covers:
    - validate_args: folder path, threshold range, and fade range checks
    - parse: happy path argument assignment (threshold arrives as a
      bare negative-number token, e.g. "-50")
    - parse: invalid folder path exits with errors printed to stderr
      (regression — previously exited silently with no message anywhere)
Changed in 1.4.0: the worker default is read from default_max_workers().
"""

import pytest

from silence_trimmer.utils.cli_args import SilenceTrimmerArgs, parse, validate_args

# ── validate_args ─────────────────────────────────────────────────────────────


class TestValidateArgs:
    def test_default_args_return_no_errors(self):
        assert validate_args(SilenceTrimmerArgs()) == []

    def test_valid_directory_returns_no_errors(self, tmp_path):
        args = SilenceTrimmerArgs(folder_path=str(tmp_path))
        assert validate_args(args) == []

    def test_nonexistent_folder_path_returns_error(self, tmp_path):
        missing = tmp_path / "does_not_exist"
        args = SilenceTrimmerArgs(folder_path=str(missing))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "does not exist" in errors[0]

    def test_file_path_instead_of_directory_returns_error(self, tmp_path):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        args = SilenceTrimmerArgs(folder_path=str(file_path))
        errors = validate_args(args)
        assert len(errors) == 1
        assert "not a directory" in errors[0]

    @pytest.mark.parametrize("threshold", [-81, -100, -19, 0])
    def test_threshold_out_of_range_returns_error(self, threshold):
        args = SilenceTrimmerArgs(threshold=threshold)
        errors = validate_args(args)
        assert any("Silence threshold must be -80 to -20" in e for e in errors)

    @pytest.mark.parametrize("threshold", [-80, -50, -20])
    def test_threshold_at_boundaries_passes(self, threshold):
        args = SilenceTrimmerArgs(threshold=threshold)
        assert validate_args(args) == []

    def test_fade_in_out_of_range_returns_error(self):
        args = SilenceTrimmerArgs(fade_in_ms=50)
        errors = validate_args(args)
        assert any("Fade-in must be 100-3000ms" in e for e in errors)

    def test_fade_out_out_of_range_returns_error(self):
        args = SilenceTrimmerArgs(fade_out_ms=6000)
        errors = validate_args(args)
        assert any("Fade-out must be 100-5000ms" in e for e in errors)

    def test_none_fades_are_not_validated(self):
        args = SilenceTrimmerArgs(fade_in_ms=None, fade_out_ms=None)
        assert validate_args(args) == []


# ── parse — happy path ────────────────────────────────────────────────────────


class TestParseHappyPath:
    def test_no_args_returns_defaults(self):
        args = parse([])
        assert args.folder_path == ""
        assert args.threshold == -50
        assert args.apply_fade is False
        assert args.fade_in_ms is None
        assert args.fade_out_ms is None
        assert args.parallel_mode is False
        from audio_suite_shared.constants import default_max_workers

        assert args.max_workers == default_max_workers()

    def test_folder_path_set_from_argv_1(self, tmp_path):
        args = parse(["prog", str(tmp_path)])
        assert args.folder_path == str(tmp_path)

    def test_negative_number_token_sets_threshold(self, tmp_path):
        args = parse(["prog", str(tmp_path), "-40"])
        assert args.threshold == -40

    def test_non_numeric_dash_token_ignored(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--bogus"])
        assert args.threshold == -50

    def test_live_flag_sets_live_mode_true(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--live"])
        assert args.live_mode is True

    def test_dry_flag_sets_live_mode_false(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--dry"])
        assert args.live_mode is False

    def test_start_and_end_flags(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--start", "--end"])
        assert args.auto_start is True
        assert args.auto_end is True

    def test_fade_flag_sets_apply_fade_true(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--fade"])
        assert args.apply_fade is True

    def test_no_fade_flag_sets_apply_fade_false(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--no-fade"])
        assert args.apply_fade is False

    def test_fade_in_and_fade_out_pairs_captured(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--fade-in", "250", "--fade-out", "400"])
        assert args.fade_in_ms == 250
        assert args.fade_out_ms == 400

    def test_non_numeric_fade_values_keep_defaults(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--fade-in", "abc", "--fade-out", "xyz"])
        assert args.fade_in_ms is None
        assert args.fade_out_ms is None

    def test_parallel_flags_and_workers(self, tmp_path):
        args = parse(["prog", str(tmp_path), "--parallel", "--workers", "8"])
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
        assert "Silence Trimmer:" in captured.err

    def test_nothing_printed_to_stdout_on_invalid_path(self, tmp_path, capsys):
        missing = tmp_path / "does_not_exist"
        with pytest.raises(SystemExit):
            parse(["prog", str(missing)])
        captured = capsys.readouterr()
        assert captured.out == ""
