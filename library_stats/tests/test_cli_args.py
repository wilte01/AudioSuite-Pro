"""Tests for library_stats.utils.cli_args.

Covers the G2.3 contract: ``Library_Stats.pyw`` (via
``library_stats.app.main``) must parse the Master Driver's argv and
pre-fill the GUI widgets.

Changed in 1.0.1: adds parser tests for the driver handshake.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from library_stats.utils.cli_args import (
    LibraryStatsArgs,
    parse,
    was_launched_from_driver,
)


class TestLibraryStatsArgs:
    def test_default_values(self) -> None:
        args = LibraryStatsArgs()
        assert args.folder_path == ""
        assert args.incremental is False
        assert args.refresh is False
        assert args.export_csv == ""
        assert args.export_json == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False
        assert args.clear_logs is False
        assert args.parallel_run is False


class TestParse:
    def test_bare_launch_returns_defaults(self) -> None:
        assert parse(["library_stats"]) == LibraryStatsArgs()

    def test_positional_directory(self, tmp_path: Path) -> None:
        args = parse(["library_stats", str(tmp_path)])
        assert args.folder_path == str(tmp_path)

    def test_incremental_flag(self, tmp_path: Path) -> None:
        args = parse(["library_stats", str(tmp_path), "--incremental"])
        assert args.incremental is True

    def test_refresh_flag(self, tmp_path: Path) -> None:
        args = parse(["library_stats", str(tmp_path), "--refresh"])
        assert args.refresh is True

    def test_driver_argv_is_fully_parsed(self, tmp_path: Path) -> None:
        args = parse(
            [
                "library_stats",
                str(tmp_path),
                "--incremental",
                "--refresh",
                "--export-csv",
                str(tmp_path / "stats.csv"),
                "--export-json",
                str(tmp_path / "stats.json"),
                "--dry",
                "--start",
                "--end",
            ]
        )
        assert args.folder_path == str(tmp_path)
        assert args.incremental is True
        assert args.refresh is True
        assert args.export_csv == str(tmp_path / "stats.csv")
        assert args.export_json == str(tmp_path / "stats.json")
        assert args.live_mode is False
        assert args.auto_start is True
        assert args.auto_end is True

    def test_unknown_flags_are_ignored(self, tmp_path: Path) -> None:
        args = parse(["library_stats", str(tmp_path), "--future-flag", "x"])
        assert args.folder_path == str(tmp_path)

    def test_invalid_path_exits(self, tmp_path: Path, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            parse(["library_stats", str(tmp_path / "missing")])
        assert exc_info.value.code == 1
        assert "does not exist" in capsys.readouterr().err

    def test_reexports_driver_helper(self) -> None:
        assert callable(was_launched_from_driver)
        assert "library_stats.utils.cli_args" in sys.modules
