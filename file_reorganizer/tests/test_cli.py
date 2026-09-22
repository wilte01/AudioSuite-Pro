"""
tests/test_cli.py
Tests for file_reorganizer CLI command defaults.

Verifies that the ``reorganize`` CLI falls back to the shared suite config
when ``--action``/pattern flags are omitted, and that explicitly provided
flags win over saved settings.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from click.testing import CliRunner

import file_reorganizer.cli  # noqa: F401  (registers the reorganize command)
from audio_suite_shared.cli_base import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def music_dir(tmp_path) -> object:
    """An existing directory usable as the CLI ``directory`` argument."""
    d = tmp_path / "music"
    d.mkdir()
    return d


_CLI_RUN = "file_reorganizer.cli.run_reorganizer"


class TestReorganizeDefaults:
    def test_action_defaults_to_saved_config(
        self, runner: CliRunner, music_dir: object
    ) -> None:
        with (
            patch(
                "file_reorganizer.cli.load_settings",
                return_value={
                    "dest_dir": "/saved/out",
                    "action": "move",
                    "specific_pattern": "sp",
                    "various_pattern": "va",
                },
            ),
            patch(_CLI_RUN) as mock_run,
        ):
            result = runner.invoke(
                cli,
                [
                    "reorganize",
                    str(music_dir),
                    "--output-dir",
                    str(music_dir),
                    "--dry",
                ],
            )
        assert result.exit_code == 0
        assert mock_run.call_args.kwargs["action"] == "move"

    def test_explicit_action_wins_over_saved_config(
        self, runner: CliRunner, music_dir: object
    ) -> None:
        with (
            patch(
                "file_reorganizer.cli.load_settings",
                return_value={
                    "dest_dir": "/saved/out",
                    "action": "move",
                    "specific_pattern": "sp",
                    "various_pattern": "va",
                },
            ),
            patch(_CLI_RUN) as mock_run,
        ):
            result = runner.invoke(
                cli,
                [
                    "reorganize",
                    str(music_dir),
                    "--output-dir",
                    str(music_dir),
                    "--action",
                    "copy",
                    "--dry",
                ],
            )
        assert result.exit_code == 0
        assert mock_run.call_args.kwargs["action"] == "copy"

    def test_patterns_default_to_saved_config(
        self, runner: CliRunner, music_dir: object
    ) -> None:
        with (
            patch(
                "file_reorganizer.cli.load_settings",
                return_value={
                    "dest_dir": "/saved/out",
                    "action": "copy",
                    "specific_pattern": "saved_sp",
                    "various_pattern": "saved_va",
                },
            ),
            patch(_CLI_RUN) as mock_run,
        ):
            result = runner.invoke(
                cli,
                [
                    "reorganize",
                    str(music_dir),
                    "--output-dir",
                    str(music_dir),
                    "--dry",
                ],
            )
        assert result.exit_code == 0
        assert mock_run.call_args.kwargs["specific_pattern"] == "saved_sp"
        assert mock_run.call_args.kwargs["various_pattern"] == "saved_va"

    def test_explicit_patterns_override_saved_config(
        self, runner: CliRunner, music_dir: object
    ) -> None:
        with (
            patch(
                "file_reorganizer.cli.load_settings",
                return_value={
                    "dest_dir": "/saved/out",
                    "action": "copy",
                    "specific_pattern": "saved_sp",
                    "various_pattern": "saved_va",
                },
            ),
            patch(_CLI_RUN) as mock_run,
        ):
            result = runner.invoke(
                cli,
                [
                    "reorganize",
                    str(music_dir),
                    "--output-dir",
                    str(music_dir),
                    "--specific-pattern",
                    "cli_sp",
                    "--various-pattern",
                    "cli_va",
                    "--dry",
                ],
            )
        assert result.exit_code == 0
        assert mock_run.call_args.kwargs["specific_pattern"] == "cli_sp"
        assert mock_run.call_args.kwargs["various_pattern"] == "cli_va"

    def test_help_mentions_saved_config_default(self, runner: CliRunner) -> None:
        result = runner.invoke(cli, ["reorganize", "--help"])
        assert result.exit_code == 0
        assert "defaults to saved config" in result.output
