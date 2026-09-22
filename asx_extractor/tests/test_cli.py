"""Tests for asx_extractor CLI commands."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

# Import the CLI module so @cli.command() decorators register on the group.
import asx_extractor.cli  # noqa: F401
from audio_suite_shared.cli_base import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    d = tmp_path / "playlists"
    d.mkdir()
    return d


class TestAsxExtractHelp:
    def test_help_output_includes_all_options(self, runner: CliRunner):
        result = runner.invoke(cli, ["asx-extract", "--help"])
        assert result.exit_code == 0
        assert "DIRECTORY" in result.output
        assert "--dry" in result.output
        assert "--json" in result.output


class TestAsxExtractValidation:
    def test_nonexistent_directory_returns_error(
        self, runner: CliRunner, tmp_path: Path
    ):
        result = runner.invoke(cli, ["asx-extract", str(tmp_path / "missing")])
        assert result.exit_code != 0

    def test_file_path_not_directory_returns_error(
        self, runner: CliRunner, tmp_path: Path
    ):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = runner.invoke(cli, ["asx-extract", str(f)])
        assert result.exit_code != 0


class TestAsxExtractRun:
    def test_dry_run_on_empty_dir(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(cli, ["asx-extract", str(audio_dir), "--dry"])
        assert result.exit_code == 0

    def test_json_flag(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(cli, ["asx-extract", str(audio_dir), "--dry", "--json"])
        assert result.exit_code == 0


class TestNoOpCallbacks:
    """The headless fallback callbacks must be harmless no-ops."""

    def test_no_op_accepts_any_kwargs(self) -> None:
        from asx_extractor.cli import _no_op

        _no_op(anything="value", processed=0, total=1)

    def test_no_op_error_accepts_message(self) -> None:
        from asx_extractor.cli import _no_op_error

        _no_op_error("silently ignored")
