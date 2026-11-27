"""Tests for mood_analyzer CLI command.

Changed in 2.9.0: this file's first change in the window that opened at
c50e533; the per-file note lock names that window 2.9.0, and the 2.9.1 note
below records what changed.
Changed in 2.9.1: an empty folder is the reported abort, so the run cases
assert status 1 and the reason in the JSON document.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

# Import the CLI module so @cli.command() decorators register on the group.
import mood_analyzer.cli  # noqa: F401
from audio_suite_shared.cli_base import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    d = tmp_path / "music"
    d.mkdir()
    return d


class TestMoodAnalyzerHelp:
    def test_help_output_includes_all_options(self, runner: CliRunner):
        result = runner.invoke(cli, ["mood-analyzer", "--help"])
        assert result.exit_code == 0
        assert "DIRECTORY" in result.output
        assert "--dry" in result.output
        assert "--json" in result.output
        assert "--duration" in result.output
        assert "--parallel" in result.output
        assert "--workers" in result.output


class TestMoodAnalyzerValidation:
    def test_nonexistent_directory_returns_error(
        self, runner: CliRunner, tmp_path: Path
    ):
        result = runner.invoke(cli, ["mood-analyzer", str(tmp_path / "missing")])
        assert result.exit_code != 0

    def test_file_path_not_directory_returns_error(
        self, runner: CliRunner, tmp_path: Path
    ):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = runner.invoke(cli, ["mood-analyzer", str(f)])
        assert result.exit_code != 0


class TestMoodAnalyzerRun:
    def test_dry_run_on_empty_dir(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(cli, ["mood-analyzer", str(audio_dir), "--dry"])
        # No files → the on_error path reports one failed item.
        assert result.exit_code == 1
        assert "Summary" in result.output

    def test_json_flag_produces_valid_json(self, runner: CliRunner, audio_dir: Path):
        import json as _json

        result = runner.invoke(
            cli, ["mood-analyzer", str(audio_dir), "--dry", "--json"]
        )
        assert result.exit_code == 1
        payload = _json.loads(result.stdout)
        assert payload["errors"] == 1
        assert payload["error"]

    def test_duration_option_accepted(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(
            cli, ["mood-analyzer", str(audio_dir), "--dry", "--duration", "60"]
        )
        # The option is accepted; the empty folder is the reported abort.
        assert result.exit_code == 1
        assert "Invalid value" not in result.output
