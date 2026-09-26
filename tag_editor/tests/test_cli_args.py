"""Tests for tag_editor.utils.cli_args."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from tag_editor.utils.cli_args import (
    TagEditorArgs,
    parse,
    validate_args,
    was_launched_from_driver,
)


class TestTagEditorArgs:
    def test_default_values(self) -> None:
        args = TagEditorArgs()
        assert args.folder_path == ""
        assert args.live_mode is False
        assert args.auto_start is False
        assert args.auto_end is False
        assert args.clear_logs is False
        assert args.parallel_run is False


class TestValidateArgs:
    def test_empty_path_is_valid(self) -> None:
        assert validate_args(TagEditorArgs()) == []

    def test_existing_directory_is_valid(self, tmp_path: Path) -> None:
        args = TagEditorArgs(folder_path=str(tmp_path))
        assert validate_args(args) == []

    def test_missing_path_is_invalid(self, tmp_path: Path) -> None:
        args = TagEditorArgs(folder_path=str(tmp_path / "missing"))
        assert validate_args(args) != []


class TestParse:
    def test_bare_launch_returns_defaults(self) -> None:
        args = parse(["Tag_Editor.pyw"])
        assert args == TagEditorArgs()

    def test_positional_path(self, tmp_path: Path) -> None:
        args = parse(["Tag_Editor.pyw", str(tmp_path)])
        assert args.folder_path == str(tmp_path)
        assert args.live_mode is False

    def test_live_mode(self, tmp_path: Path) -> None:
        args = parse(["Tag_Editor.pyw", str(tmp_path), "--live"])
        assert args.live_mode is True

    def test_driver_handshake_flags(self, tmp_path: Path) -> None:
        args = parse(
            [
                "Tag_Editor.pyw",
                str(tmp_path),
                "--live",
                "--start",
                "--end",
                "--clear-logs",
                "--parallel-run",
            ]
        )
        assert args.live_mode is True
        assert args.auto_start is True
        assert args.auto_end is True
        assert args.clear_logs is True
        assert args.parallel_run is True

    def test_unknown_flags_are_ignored(self, tmp_path: Path) -> None:
        args = parse(["Tag_Editor.pyw", str(tmp_path), "--future-flag", "value"])
        assert args.folder_path == str(tmp_path)

    def test_invalid_path_exits(self, tmp_path: Path, capsys) -> None:
        with pytest.raises(SystemExit) as exc_info:
            parse(["Tag_Editor.pyw", str(tmp_path / "missing")])
        assert exc_info.value.code == 1
        assert "does not exist" in capsys.readouterr().err

    def test_reexports_driver_helper(self) -> None:
        assert callable(was_launched_from_driver)
        assert "tag_editor.utils.cli_args" in sys.modules
