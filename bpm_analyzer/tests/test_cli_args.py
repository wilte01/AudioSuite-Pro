"""
tests/test_cli_args.py
pytest suite for bpm_analyzer.utils.cli_args

Covers:
  • Default values when no args supplied
  • All positional slots parsed correctly
  • Named flag pairs (--bpm-min, --bpm-max, --duration)
  • Invalid integer value for named flag → logged warning, default retained
  • Unknown tokens skipped without error
  • argv=None falls back to sys.argv
  • Folder path validation: nonexistent path exits with error on stderr
    (regression — previously the path was never validated at all)
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from audio_suite_shared.cli_dataclasses import BPMArgs
from bpm_analyzer.utils.cli_args import parse, was_launched_from_driver


class TestParseDefaults:
    def test_no_args_returns_defaults(self):
        result = parse(["prog"])
        assert result.folder_path == ""
        assert result.bpm_min == 75
        assert result.bpm_max == 175
        assert result.duration == 90
        assert result.live_mode is False
        assert result.auto_start is False
        assert result.auto_end is False

    def test_returns_bpm_args_instance(self):
        assert isinstance(parse(["prog"]), BPMArgs)


class TestParsePositional:
    def test_folder_path_set(self, tmp_path):
        result = parse(["prog", str(tmp_path)])
        assert result.folder_path == str(tmp_path)

    def test_live_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "", "--live"])
        assert result.live_mode is True

    def test_dry_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "", "--dry"])
        assert result.live_mode is False

    def test_auto_start_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "", "--live", "--start"])
        assert result.auto_start is True

    def test_no_start_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "", "--live", "--no-start"])
        assert result.auto_start is False

    def test_auto_end_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "", "--live", "--start", "--end"])
        assert result.auto_end is True

    def test_no_end_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "", "--live", "--start", "--no-end"])
        assert result.auto_end is False


class TestParseNamedOptions:
    def test_bpm_min_parsed(self, tmp_path):
        result = parse(
            [
                "prog",
                str(tmp_path),
                "",
                "--dry",
                "--no-start",
                "--no-end",
                "--bpm-min",
                "80",
            ]
        )
        assert result.bpm_min == 80

    def test_bpm_max_parsed(self, tmp_path):
        result = parse(
            [
                "prog",
                str(tmp_path),
                "",
                "--dry",
                "--no-start",
                "--no-end",
                "--bpm-max",
                "160",
            ]
        )
        assert result.bpm_max == 160

    def test_duration_parsed(self, tmp_path):
        result = parse(
            [
                "prog",
                str(tmp_path),
                "",
                "--dry",
                "--no-start",
                "--no-end",
                "--duration",
                "45",
            ]
        )
        assert result.duration == 45

    def test_multiple_named_options(self, tmp_path):
        result = parse(
            [
                "prog",
                str(tmp_path),
                "",
                "--dry",
                "--no-start",
                "--no-end",
                "--bpm-min",
                "85",
                "--bpm-max",
                "155",
                "--duration",
                "30",
            ]
        )
        assert result.bpm_min == 85
        assert result.bpm_max == 155
        assert result.duration == 30


class TestParseEdgeCases:
    def test_invalid_integer_retains_default(self, caplog, tmp_path):
        """Bad integer value must log a warning and keep the default."""
        import logging

        with caplog.at_level(logging.WARNING, logger="bpm_analyzer.utils.cli_args"):
            result = parse(
                [
                    "prog",
                    str(tmp_path),
                    "",
                    "--dry",
                    "--no-start",
                    "--no-end",
                    "--bpm-min",
                    "notanumber",
                ]
            )
        assert result.bpm_min == 75  # default retained
        assert any("notanumber" in r.message for r in caplog.records)

    def test_unknown_token_skipped(self, tmp_path):
        """Unrecognised flags must not raise; known flags that follow still parsed."""
        result = parse(
            [
                "prog",
                str(tmp_path),
                "",
                "--dry",
                "--no-start",
                "--no-end",
                "--unknown-flag",
                "--bpm-max",
                "150",
            ]
        )
        assert result.bpm_max == 150

    def test_none_argv_uses_sysargv(self, tmp_path):
        fake_argv = ["prog", str(tmp_path)]
        with patch.object(sys, "argv", fake_argv):
            result = parse(None)
        assert result.folder_path == str(tmp_path)

    def test_empty_argv_list_returns_defaults(self):
        result = parse([])
        assert result.folder_path == ""


class TestFolderValidation:
    """Regression: folder_path was never validated before this change —
    a bad Master Driver handshake reached the GUI unchallenged."""

    def test_nonexistent_folder_raises_systemexit(self):
        with pytest.raises(SystemExit) as exc_info:
            parse(["prog", "/totally/nonexistent/path/xyz"])
        assert exc_info.value.code == 1

    def test_nonexistent_folder_prints_error_to_stderr(self, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", "/totally/nonexistent/path/xyz"])
        captured = capsys.readouterr()
        assert "does not exist" in captured.err
        assert "/totally/nonexistent/path/xyz" in captured.err

    def test_error_message_prefixed_with_tool_name(self, capsys):
        with pytest.raises(SystemExit):
            parse(["prog", "/totally/nonexistent/path/xyz"])
        captured = capsys.readouterr()
        assert "BPM Analyzer:" in captured.err

    def test_file_instead_of_directory_raises_systemexit(self, tmp_path, capsys):
        file_path = tmp_path / "not_a_dir.txt"
        file_path.write_text("hello")
        with pytest.raises(SystemExit):
            parse(["prog", str(file_path)])
        captured = capsys.readouterr()
        assert "not a directory" in captured.err

    def test_valid_folder_parses_without_output(self, tmp_path, capsys):
        result = parse(["prog", str(tmp_path)])
        captured = capsys.readouterr()
        assert result.folder_path == str(tmp_path)
        assert captured.out == ""
        assert captured.err == ""

    def test_empty_folder_stays_legal(self, capsys):
        """Double-click / GUI-only launches pass no folder — must not exit."""
        result = parse(["prog"])
        captured = capsys.readouterr()
        assert result.folder_path == ""
        assert captured.err == ""


# ═════════════════════════════════════════════════════════════════════════════
# was_launched_from_driver
# ═════════════════════════════════════════════════════════════════════════════


class TestWasLaunchedFromDriver:
    def test_no_args_means_standalone(self):
        assert was_launched_from_driver(["prog"]) is False

    def test_any_argument_means_driven(self, tmp_path):
        assert was_launched_from_driver(["prog", str(tmp_path)]) is True

    def test_flag_only_argv_means_driven(self):
        assert was_launched_from_driver(["prog", "--no-clear-logs"]) is True

    def test_defaults_to_sys_argv(self, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["prog"])
        assert was_launched_from_driver() is False


# ═════════════════════════════════════════════════════════════════════════════
# parse — display-only driver orchestration flags
# ═════════════════════════════════════════════════════════════════════════════


class TestDriverDisplayFlags:
    """Trailing display flags must not collide with BPM's own --parallel."""

    def test_flags_default_false(self):
        args = BPMArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_parse_defaults_when_flags_absent(self, tmp_path):
        args = parse(["prog", str(tmp_path), "0", "--dry", "--start", "--end"])
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed_after_named_pairs(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "0",
                "--dry",
                "--start",
                "--end",
                "--bpm-min",
                "80",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.clear_logs is True
        assert args.parallel_run is True
        assert args.bpm_min == 80

    def test_negative_flags_parsed(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "0",
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
        """BPM's tool-specific --parallel must keep its own meaning."""
        args = parse(
            [
                "prog",
                str(tmp_path),
                "0",
                "--dry",
                "--no-start",
                "--no-end",
                "--parallel",
                "--workers",
                "6",
                "--parallel-run",
            ]
        )
        assert args.parallel_mode is True
        assert args.max_workers == 6
        assert args.parallel_run is True
