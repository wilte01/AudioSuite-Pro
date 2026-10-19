"""
tests/test_cli_args.py — pytest suite for lyrics_manager.utils.cli_args.

Covers defaults, positional slots, named flag pairs, boolean flag pairs,
display-only driver flags, invalid values, and folder-path validation.
Changed in 1.4.0: the worker default is read from default_max_workers().
"""

from __future__ import annotations

import logging
import sys
from unittest.mock import patch

import pytest

from audio_suite_shared.cli_dataclasses import LyricsArgs
from lyrics_manager.utils.cli_args import parse


class TestParseDefaults:
    def test_no_args_returns_defaults(self):
        result = parse(["prog"])
        assert result.folder_path == ""
        assert result.provider == "lrclib"
        assert result.request_timeout == 10.0
        assert result.skip_existing is True
        assert result.plain_fallback is True
        assert result.live_mode is False
        assert result.auto_start is False
        assert result.auto_end is False

    def test_returns_lyrics_args_instance(self):
        assert isinstance(parse(["prog"]), LyricsArgs)


class TestParsePositional:
    def test_folder_path_set(self, tmp_path):
        result = parse(["prog", str(tmp_path)])
        assert result.folder_path == str(tmp_path)

    def test_live_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "0", "--live"])
        assert result.live_mode is True

    def test_dry_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "0", "--dry"])
        assert result.live_mode is False

    def test_auto_start_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "0", "--live", "--start"])
        assert result.auto_start is True

    def test_no_start_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "0", "--live", "--no-start"])
        assert result.auto_start is False

    def test_auto_end_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "0", "--live", "--start", "--end"])
        assert result.auto_end is True

    def test_no_end_flag(self, tmp_path):
        result = parse(["prog", str(tmp_path), "0", "--live", "--start", "--no-end"])
        assert result.auto_end is False


class TestParseNamedOptions:
    def _base(self, tmp_path, *extra):
        return [
            "prog",
            str(tmp_path),
            "0",
            "--dry",
            "--no-start",
            "--no-end",
            *extra,
        ]

    def test_provider_parsed(self, tmp_path):
        result = parse(self._base(tmp_path, "--provider", "lrclib"))
        assert result.provider == "lrclib"

    def test_request_timeout_parsed(self, tmp_path):
        result = parse(self._base(tmp_path, "--request-timeout", "15.5"))
        assert result.request_timeout == 15.5

    def test_workers_parsed(self, tmp_path):
        result = parse(self._base(tmp_path, "--workers", "8"))
        assert result.max_workers == 8

    def test_skip_existing_flag(self, tmp_path):
        result = parse(self._base(tmp_path, "--skip-existing"))
        assert result.skip_existing is True

    def test_no_skip_existing_flag(self, tmp_path):
        result = parse(self._base(tmp_path, "--no-skip-existing"))
        assert result.skip_existing is False

    def test_plain_fallback_flag(self, tmp_path):
        result = parse(self._base(tmp_path, "--plain-fallback"))
        assert result.plain_fallback is True

    def test_no_plain_fallback_flag(self, tmp_path):
        result = parse(self._base(tmp_path, "--no-plain-fallback"))
        assert result.plain_fallback is False

    def test_multiple_named_options(self, tmp_path):
        result = parse(
            self._base(
                tmp_path,
                "--provider",
                "lrclib",
                "--request-timeout",
                "20",
                "--workers",
                "6",
                "--no-skip-existing",
                "--no-plain-fallback",
            )
        )
        assert result.provider == "lrclib"
        assert result.request_timeout == 20.0
        assert result.max_workers == 6
        assert result.skip_existing is False
        assert result.plain_fallback is False


class TestParseEdgeCases:
    def test_invalid_float_retains_default(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="lyrics_manager.utils.cli_args"):
            result = parse(
                [
                    "prog",
                    str(tmp_path),
                    "0",
                    "--dry",
                    "--no-start",
                    "--no-end",
                    "--request-timeout",
                    "notanumber",
                ]
            )
        assert result.request_timeout == 10.0
        assert any("notanumber" in r.message for r in caplog.records)

    def test_invalid_workers_retains_default(self, tmp_path, caplog):
        with caplog.at_level(logging.WARNING, logger="lyrics_manager.utils.cli_args"):
            result = parse(
                [
                    "prog",
                    str(tmp_path),
                    "0",
                    "--dry",
                    "--no-start",
                    "--no-end",
                    "--workers",
                    "many",
                ]
            )
        from audio_suite_shared.constants import default_max_workers

        assert result.max_workers == default_max_workers()
        assert any("many" in r.message for r in caplog.records)

    def test_unknown_token_skipped(self, tmp_path):
        result = parse(
            [
                "prog",
                str(tmp_path),
                "0",
                "--dry",
                "--no-start",
                "--no-end",
                "--unknown-flag",
                "--provider",
                "lrclib",
            ]
        )
        assert result.provider == "lrclib"

    def test_none_argv_uses_sysargv(self, tmp_path):
        fake_argv = ["prog", str(tmp_path)]
        with patch.object(sys, "argv", fake_argv):
            result = parse(None)
        assert result.folder_path == str(tmp_path)

    def test_empty_argv_list_returns_defaults(self):
        result = parse([])
        assert result.folder_path == ""


class TestFolderValidation:
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
        assert "Lyrics Manager:" in captured.err

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
        result = parse(["prog"])
        captured = capsys.readouterr()
        assert result.folder_path == ""
        assert captured.err == ""


class TestDriverDisplayFlags:
    def test_flags_default_false(self):
        args = LyricsArgs()
        assert args.clear_logs is False
        assert args.parallel_run is False

    def test_positive_flags_parsed(self, tmp_path):
        args = parse(
            [
                "prog",
                str(tmp_path),
                "0",
                "--dry",
                "--start",
                "--end",
                "--provider",
                "lrclib",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.clear_logs is True
        assert args.parallel_run is True
        assert args.provider == "lrclib"

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

    def test_tool_parallel_flag_distinct_from_parallel_run(self, tmp_path):
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
