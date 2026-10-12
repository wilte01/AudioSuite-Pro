"""Tests for tag_field_updater.utils.cli_args.

Covers the G2.2 contract: ``Tag_Field_Updater.pyw`` (via
``tag_field_updater.ui.app.main``) must parse the Master Driver's argv and
pre-fill the directory and dry-run mode.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tag_field_updater.utils.cli_args import (
    TagFieldUpdaterArgs,
    parse,
    was_launched_from_driver,
)


class TestTagFieldUpdaterArgs:
    def test_default_values(self) -> None:
        args = TagFieldUpdaterArgs()
        assert args.folder_path == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False
        assert args.clear_logs is False
        assert args.parallel_run is False


class TestParse:
    def test_bare_launch_returns_defaults(self) -> None:
        assert parse(["tag_field_updater"]) == TagFieldUpdaterArgs()

    def test_positional_directory(self, tmp_path: Path) -> None:
        args = parse(["tag_field_updater", str(tmp_path)])
        assert args.folder_path == str(tmp_path)
        assert args.live_mode is False

    def test_live_mode(self, tmp_path: Path) -> None:
        args = parse(["tag_field_updater", str(tmp_path), "--live"])
        assert args.live_mode is True

    def test_driver_argv_is_fully_parsed(self, tmp_path: Path) -> None:
        args = parse(
            [
                "tag_field_updater",
                str(tmp_path),
                "--dry",
                "--start",
                "--end",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.folder_path == str(tmp_path)
        assert args.live_mode is False
        assert args.auto_start is True
        assert args.auto_end is True
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_unknown_flags_are_ignored(self, tmp_path: Path) -> None:
        args = parse(["tag_field_updater", str(tmp_path), "--future-flag", "x"])
        assert args.folder_path == str(tmp_path)

    def test_invalid_path_exits(self, tmp_path: Path, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            parse(["tag_field_updater", str(tmp_path / "missing")])
        assert exc_info.value.code == 1
        assert "does not exist" in capsys.readouterr().err

    def test_reexports_driver_helper(self) -> None:
        assert callable(was_launched_from_driver)
        assert "tag_field_updater.utils.cli_args" in sys.modules
