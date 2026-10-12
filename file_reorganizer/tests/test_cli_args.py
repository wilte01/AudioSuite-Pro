"""Tests for file_reorganizer.utils.cli_args.

Covers the G2.1 contract: ``File_Reorganizer.pyw`` (via
``file_reorganizer.app.main``) must parse the Master Driver's argv and
pre-fill the GUI widgets instead of silently ignoring every argument.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from file_reorganizer.utils.cli_args import (
    FileReorganizerArgs,
    parse,
    validate_args,
    was_launched_from_driver,
)


class TestFileReorganizerArgs:
    def test_default_values(self) -> None:
        args = FileReorganizerArgs()
        assert args.folder_path == ""
        assert args.output_dir == ""
        assert args.action == ""
        assert args.specific_pattern == ""
        assert args.various_pattern == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False
        assert args.clear_logs is False
        assert args.parallel_run is False


class TestValidateArgs:
    def test_empty_path_is_valid(self) -> None:
        assert validate_args(FileReorganizerArgs()) == []

    def test_existing_directory_is_valid(self, tmp_path: Path) -> None:
        args = FileReorganizerArgs(folder_path=str(tmp_path))
        assert validate_args(args) == []

    def test_missing_path_is_invalid(self, tmp_path: Path) -> None:
        args = FileReorganizerArgs(folder_path=str(tmp_path / "missing"))
        assert validate_args(args) != []

    def test_bad_action_is_invalid(self, tmp_path: Path) -> None:
        args = FileReorganizerArgs(folder_path=str(tmp_path), action="delete")
        assert validate_args(args) != []


class TestParse:
    def test_bare_launch_returns_defaults(self) -> None:
        assert parse(["File_Reorganizer.pyw"]) == FileReorganizerArgs()

    def test_positional_source(self, tmp_path: Path) -> None:
        args = parse(["File_Reorganizer.pyw", str(tmp_path)])
        assert args.folder_path == str(tmp_path)

    def test_driver_argv_is_fully_parsed(self, tmp_path: Path) -> None:
        args = parse(
            [
                "File_Reorganizer.pyw",
                str(tmp_path),
                "--output-dir",
                str(tmp_path / "out"),
                "--action",
                "move",
                "--specific-pattern",
                "{artist}/{album}",
                "--various-pattern",
                "Various/{album}",
                "--live",
                "--no-start",
                "--end",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.folder_path == str(tmp_path)
        assert args.output_dir == str(tmp_path / "out")
        assert args.action == "move"
        assert args.specific_pattern == "{artist}/{album}"
        assert args.various_pattern == "Various/{album}"
        assert args.live_mode is True
        assert args.auto_start is False
        assert args.auto_end is True
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_unknown_flags_are_ignored(self, tmp_path: Path) -> None:
        args = parse(["File_Reorganizer.pyw", str(tmp_path), "--future-flag", "x"])
        assert args.folder_path == str(tmp_path)

    def test_invalid_path_exits(self, tmp_path: Path, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            parse(["File_Reorganizer.pyw", str(tmp_path / "missing")])
        assert exc_info.value.code == 1
        assert "does not exist" in capsys.readouterr().err

    def test_invalid_action_exits(self, tmp_path: Path, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            parse(["File_Reorganizer.pyw", str(tmp_path), "--action", "nuke"])
        assert exc_info.value.code == 1
        assert "copy" in capsys.readouterr().err

    def test_reexports_driver_helper(self) -> None:
        assert callable(was_launched_from_driver)
        assert "file_reorganizer.utils.cli_args" in sys.modules
