"""
test_cli_args.py
Pytest suite for pop_click_remover.utils.cli_args.

No real filesystem access or Tk display is required.  All tests exercise
argument parsing via sys.argv patching.

Coverage
--------
* Default values when no arguments are supplied
* folder_path positional argument
* --live / --dry mode flags (mutually exclusive)
* --start / --end automation flags
* --sensitivity and --width DSP parameters
* Post-parse validation: out-of-range sensitivity raises SystemExit
* Post-parse validation: width < 1 raises SystemExit
* Folder path validation: nonexistent path exits via parser.error (exit 2)
* parse_known_args: unknown extra arguments are silently ignored
* was_launched_from_driver(): True when argv has > 1 entry
* Display-only handshake flags: --clear-logs, --no-clear-logs, etc.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from pop_click_remover.utils.cli_args import parse, was_launched_from_driver


def _parse(*args: str):
    """Run parse() with the given sys.argv tokens (no program name needed)."""
    with patch.object(sys, "argv", ["app.py", *args]):
        return parse()


class TestDefaults:
    def test_no_args_returns_defaults(self):
        ns = _parse()
        assert ns.folder_path is None
        assert ns.live_mode is False
        assert ns.auto_start is False
        assert ns.auto_end is False
        assert ns.sensitivity == pytest.approx(0.31)
        assert ns.width == 2
        assert ns.clear_logs is False
        assert ns.parallel_run is False

    def test_folder_path_positional(self, tmp_path):
        ns = _parse(str(tmp_path))
        assert ns.folder_path == str(tmp_path)


class TestModeFlags:
    def test_live_flag_sets_live_mode(self):
        ns = _parse("--live")
        assert ns.live_mode is True

    def test_dry_flag_sets_dry_mode(self):
        ns = _parse("--dry")
        assert ns.live_mode is False

    def test_live_and_dry_are_mutually_exclusive(self):
        with pytest.raises(SystemExit):
            _parse("--live", "--dry")


class TestAutomationFlags:
    def test_start_flag(self):
        ns = _parse("--start")
        assert ns.auto_start is True

    def test_end_flag(self):
        ns = _parse("--end")
        assert ns.auto_end is True

    def test_start_and_end_together(self):
        ns = _parse("--start", "--end")
        assert ns.auto_start is True
        assert ns.auto_end is True


class TestDSPParameters:
    def test_sensitivity_valid(self):
        ns = _parse("--sensitivity", "0.05")
        assert ns.sensitivity == pytest.approx(0.05)

    def test_sensitivity_maximum(self):
        ns = _parse("--sensitivity", "0.40")
        assert ns.sensitivity == pytest.approx(0.40)

    def test_sensitivity_minimum(self):
        ns = _parse("--sensitivity", "0.01")
        assert ns.sensitivity == pytest.approx(0.01)

    def test_width_valid(self):
        ns = _parse("--width", "5")
        assert ns.width == 5

    def test_width_minimum(self):
        ns = _parse("--width", "1")
        assert ns.width == 1


class TestValidation:
    @pytest.mark.parametrize("bad", ["0.0", "-0.1", "0.41", "1.0", "2.0"])
    def test_invalid_sensitivity_exits(self, bad: str):
        with pytest.raises(SystemExit):
            _parse("--sensitivity", bad)

    @pytest.mark.parametrize("bad", ["0", "-1", "-100"])
    def test_invalid_width_exits(self, bad: str):
        with pytest.raises(SystemExit):
            _parse("--width", bad)


class TestUnknownArguments:
    def test_unknown_args_silently_discarded(self, tmp_path):
        """parse_known_args must not raise on extra/unknown tokens."""
        ns = _parse(str(tmp_path), "--unknown-flag", "--foo=bar")
        assert ns.folder_path == str(tmp_path)

    def test_combined_valid_and_unknown(self, tmp_path):
        """Unknown valueless flags are discarded; note argparse would
        capture a trailing bare token (e.g. an injected flag's VALUE) as
        folder_path, which folder validation then correctly rejects."""
        ns = _parse(str(tmp_path), "--live", "--start", "--tk-geometry")
        assert ns.folder_path == str(tmp_path)
        assert ns.live_mode is True
        assert ns.auto_start is True


class TestFolderValidation:
    """Regression: folder_path was never validated — a bad Master Driver
    handshake reached the GUI unchallenged. Errors now flow through the
    existing post-parse errors list into parser.error() (exit code 2)."""

    def test_nonexistent_folder_raises_systemexit(self):
        with pytest.raises(SystemExit) as exc_info:
            _parse("/totally/nonexistent/path/xyz")
        assert exc_info.value.code == 2

    def test_nonexistent_folder_prints_error_to_stderr(self, capsys):
        with pytest.raises(SystemExit):
            _parse("/totally/nonexistent/path/xyz")
        captured = capsys.readouterr()
        assert "does not exist" in captured.err
        assert "/totally/nonexistent/path/xyz" in captured.err

    def test_file_instead_of_directory_exits(self, tmp_path):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        with pytest.raises(SystemExit):
            _parse(str(file_path))

    def test_valid_folder_parses_without_stderr(self, tmp_path, capsys):
        ns = _parse(str(tmp_path))
        captured = capsys.readouterr()
        assert ns.folder_path == str(tmp_path)
        assert captured.err == ""

    def test_no_folder_stays_legal(self, capsys):
        """Double-click / GUI-only launches pass no folder — must not exit."""
        ns = _parse()
        captured = capsys.readouterr()
        assert ns.folder_path is None
        assert "does not exist" not in captured.err

    def test_folder_error_combined_with_bad_sensitivity(self, capsys):
        with pytest.raises(SystemExit):
            _parse("/totally/nonexistent/path/xyz", "--sensitivity", "2.0")
        captured = capsys.readouterr()
        assert "does not exist" in captured.err
        assert "--sensitivity" in captured.err


class TestWasLaunchedFromDriver:
    def test_empty_argv_returns_false(self):
        assert was_launched_from_driver([]) is False

    def test_single_arg_returns_false(self):
        assert was_launched_from_driver(["app.py"]) is False

    def test_two_args_returns_true(self):
        assert was_launched_from_driver(["app.py", "/music"]) is True

    def test_driver_flags_returns_true(self):
        assert was_launched_from_driver(["app.py", "/music", "--live"]) is True

    def test_default_uses_sys_argv(self):
        with patch.object(sys, "argv", ["app.py"]):
            assert was_launched_from_driver() is False
        with patch.object(sys, "argv", ["app.py", "/music"]):
            assert was_launched_from_driver() is True


class TestDisplayFlags:
    def test_clear_logs_default(self):
        ns = _parse()
        assert ns.clear_logs is False

    def test_clear_logs_flag(self):
        ns = _parse("--clear-logs")
        assert ns.clear_logs is True

    def test_no_clear_logs_flag(self):
        ns = _parse("--no-clear-logs")
        assert ns.clear_logs is False

    def test_parallel_run_default(self):
        ns = _parse()
        assert ns.parallel_run is False

    def test_parallel_run_flag(self):
        ns = _parse("--parallel-run")
        assert ns.parallel_run is True

    def test_no_parallel_run_flag(self):
        ns = _parse("--no-parallel-run")
        assert ns.parallel_run is False

    def test_all_display_flags_combined(self):
        ns = _parse("--clear-logs", "--parallel-run")
        assert ns.clear_logs is True
        assert ns.parallel_run is True
