"""Tests for album_genre_tagger CLI commands.

Changed in 2.9.0: this file's first change in the window that opened at
c50e533; the per-file note lock names that window 2.9.0, and the 2.9.1 note
below records what changed.
Changed in 2.9.1: a run that stops before measuring a file is one
failed item - status 1 and the reason in the ``--json`` document's
``error`` field - so the empty-folder cases assert 1 and
``TestAlbumGenreAbortedRun`` locks the folder of unreadable containers.
"""

from __future__ import annotations

import json
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
        # An empty folder is a run that could not start, not a clean run:
        # the command reports one failed item and exits 1.
        assert result.exit_code == 1
        assert "No supported audio files found" in result.output

    def test_json_flag_produces_valid_json(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(cli, ["album-genre", str(audio_dir), "--dry", "--json"])
        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["errors"] == 1
        assert "No supported audio files found" in payload["error"]


class TestAlbumGenreCoverageOption:
    def test_coverage_option_accepted(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(
            cli, ["album-genre", str(audio_dir), "--coverage", "75", "--dry"]
        )
        # The empty folder is the one reported failure; the point is that
        # the option is accepted, not rejected as a usage error.
        assert result.exit_code == 1
        assert "Invalid value" not in result.output

    def test_coverage_out_of_range_rejected(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(
            cli, ["album-genre", str(audio_dir), "--coverage", "999"]
        )
        # The help text and the CLI reference both say 0-100, so an
        # out-of-range value is a usage error, not a run that always fails.
        assert result.exit_code == 2
        assert "--coverage" in result.output


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


class TestAlbumGenreAbortedRun:
    """A run that measured nothing must not look like a clean run.

    An empty folder and a folder of nothing but containers the tag layer cannot
    read both reach ``run_analysis``'s ``on_error``.  ``_run_tool``'s own
    collector echoed the line to stderr but left the result at ``errors=0``, so
    the command printed a clean zero summary, exited 0 and its ``--json``
    document carried no reason at all.
    """

    @pytest.fixture
    def unreadable_dir(self, tmp_path: Path) -> Path:
        d = tmp_path / "unreadable"
        d.mkdir()
        (d / "track.wma").write_bytes(b"not really a wma")
        (d / "track.aac").write_bytes(b"not really an aac")
        return d

    def test_text_mode_exits_one_and_prints_the_reason(
        self, runner: CliRunner, unreadable_dir: Path
    ):
        result = runner.invoke(cli, ["album-genre", str(unreadable_dir), "--dry"])

        assert result.exit_code == 1
        assert "No file could be read in the selected directory" in result.output
        assert "1 errors" in result.output

    def test_json_mode_carries_the_reason(
        self, runner: CliRunner, unreadable_dir: Path
    ):
        result = runner.invoke(
            cli, ["album-genre", str(unreadable_dir), "--dry", "--json"]
        )

        assert result.exit_code == 1
        payload = json.loads(result.stdout)
        assert payload["errors"] == 1
        assert "No file could be read in the selected directory" in payload["error"]
