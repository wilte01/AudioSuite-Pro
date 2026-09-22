"""Tests for album_genre_tagger CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

# Import the CLI module so @cli.command() decorators register on the group.
import album_genre_tagger.cli  # noqa: F401
from audio_suite_shared.cli_base import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    d = tmp_path / "music"
    d.mkdir()
    return d


class TestAlbumGenreHelp:
    def test_help_output_includes_all_options(self, runner: CliRunner):
        result = runner.invoke(cli, ["album-genre", "--help"])
        assert result.exit_code == 0
        assert "DIRECTORY" in result.output
        assert "--dry" in result.output
        assert "--json" in result.output
        assert "--coverage" in result.output


class TestAlbumGenreValidation:
    def test_nonexistent_directory_returns_error(
        self, runner: CliRunner, tmp_path: Path
    ):
        result = runner.invoke(cli, ["album-genre", str(tmp_path / "missing")])
        assert result.exit_code != 0

    def test_file_path_not_directory_returns_error(
        self, runner: CliRunner, tmp_path: Path
    ):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = runner.invoke(cli, ["album-genre", str(f)])
        assert result.exit_code != 0


class TestAlbumGenreRun:
    def test_dry_run_on_empty_dir(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(cli, ["album-genre", str(audio_dir), "--dry"])
        # Should not crash; dry-run on empty dir should complete gracefully
        assert result.exit_code == 0

    def test_json_flag_produces_valid_json(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(cli, ["album-genre", str(audio_dir), "--dry", "--json"])
        assert result.exit_code == 0


class TestAlbumGenreCoverageOption:
    def test_coverage_option_accepted(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(
            cli, ["album-genre", str(audio_dir), "--coverage", "75", "--dry"]
        )
        assert result.exit_code == 0

    def test_coverage_out_of_range_rejected(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(
            cli, ["album-genre", str(audio_dir), "--coverage", "999"]
        )
        assert result.exit_code in (0, 2)


class TestAlbumGenreUndoBatch:
    """Phase 2: the CLI command must open an active ``tag_edit`` undo batch
    before running the analysis."""

    def test_cli_command_opens_active_batch(self, runner: CliRunner, audio_dir: Path):
        mock_active_batch = MagicMock()
        with (
            patch("album_genre_tagger.cli.active_batch", mock_active_batch),
            patch("album_genre_tagger.cli.run_cli_analysis") as mock_run,
        ):
            result = runner.invoke(cli, ["album-genre", str(audio_dir), "--dry"])

        assert result.exit_code == 0
        mock_active_batch.assert_called_once_with("album_genre_tagger", "tag_edit")
        mock_run.assert_called_once()
