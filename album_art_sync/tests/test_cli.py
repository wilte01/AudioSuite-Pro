"""Tests for album_art_sync CLI commands.

Changed in 1.0.1: added an M1 regression asserting an internal pipeline error
prints a clean error line and never a 'NoneType' AttributeError traceback.
Changed in 1.4.0: patches the pipeline's single handler load (PLAN D55).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

# Import the CLI module so @cli.command() decorators register on the group.
import album_art_sync.cli  # noqa: F401
from audio_suite_shared.cli_base import cli


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def audio_dir(tmp_path: Path) -> Path:
    d = tmp_path / "music"
    d.mkdir()
    return d


class TestAlbumArtHelp:
    def test_help_output_includes_all_options(self, runner: CliRunner):
        result = runner.invoke(cli, ["album-art", "--help"])
        assert result.exit_code == 0
        assert "DIRECTORY" in result.output
        assert "--embed-size" in result.output
        assert "--purge" in result.output
        assert "--dry" in result.output
        assert "--json" in result.output
        assert "--min-dimension" in result.output
        assert "--match-threshold" in result.output


class TestAlbumArtValidation:
    def test_nonexistent_directory_returns_error(
        self, runner: CliRunner, tmp_path: Path
    ):
        result = runner.invoke(cli, ["album-art", str(tmp_path / "missing")])
        assert result.exit_code != 0

    def test_file_path_not_directory_returns_error(
        self, runner: CliRunner, tmp_path: Path
    ):
        f = tmp_path / "file.txt"
        f.write_text("x")
        result = runner.invoke(cli, ["album-art", str(f)])
        assert result.exit_code != 0


class TestAlbumArtRun:
    def test_dry_run_on_empty_dir(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(cli, ["album-art", str(audio_dir), "--dry"])
        assert result.exit_code == 0

    def test_json_flag(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(cli, ["album-art", str(audio_dir), "--dry", "--json"])
        assert result.exit_code == 0

    def test_size_option(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(
            cli, ["album-art", str(audio_dir), "--embed-size", "1200", "--dry"]
        )
        assert result.exit_code == 0

    def test_no_purge_option(self, runner: CliRunner, audio_dir: Path):
        result = runner.invoke(
            cli, ["album-art", str(audio_dir), "--no-purge", "--dry"]
        )
        assert result.exit_code == 0


class TestAlbumArtUndoBatch:
    """Phase 2: the CLI run path must wrap resolve_and_apply in an active
    ``tag_edit`` undo batch so writes auto-snapshot."""

    def test_cli_run_opens_active_batch_around_resolve(
        self, runner: CliRunner, audio_dir: Path
    ):
        from album_art_sync.core.pipeline import ArtSyncReport

        mock_active_batch = MagicMock()
        report = ArtSyncReport(
            success=True,
            source="TestSource",
            total_files=0,
            processed=0,
            skipped=0,
            errors=0,
            duration_secs=0.0,
            log_entries=[],
        )
        with (
            patch("album_art_sync.cli.active_batch", mock_active_batch),
            patch(
                "album_art_sync.core.pipeline.resolve_and_apply",
                return_value=report,
            ) as mock_resolve,
        ):
            result = runner.invoke(cli, ["album-art", str(audio_dir), "--dry"])

        assert result.exit_code == 0
        mock_active_batch.assert_called_once_with("album_art_sync", "tag_edit")
        mock_resolve.assert_called_once()


class TestAlbumArtErrorContract:
    """M1 (G4.1): an internal pipeline error must not surface as a crash.

    Pre-fix, ``resolve_and_apply`` returned ``None`` and ``run_cli_art_sync``
    read ``report.total_files``, so ``_run_tool`` reported
    ``FATAL: 'NoneType' object has no attribute 'total_files'``.  Post-fix the
    failure report reaches ``on_complete`` and the run prints a clean
    "Error: ..." line.
    """

    def test_internal_error_prints_clean_line_not_traceback(
        self, runner: CliRunner, audio_dir: Path
    ):
        (audio_dir / "track.mp3").write_bytes(b"fake mp3 content")
        with (
            patch(
                "album_art_sync.core.pipeline.source_resolver.resolve",
                side_effect=RuntimeError("resolver exploded"),
            ),
            patch(
                "album_art_sync.core.pipeline.TagHandlerFactory.get_handler",
                return_value=MagicMock(
                    read_artist_album=MagicMock(return_value=("Artist", "Album")),
                    read_album_artist=MagicMock(return_value=""),
                    read_custom_field=MagicMock(return_value=None),
                ),
            ),
            patch("album_art_sync.config.settings.load_config", return_value={}),
        ):
            result = runner.invoke(cli, ["album-art", str(audio_dir), "--live"])

        assert result.exit_code == 0
        assert "Error: Audio analysis failed" in result.output
        assert "AttributeError" not in result.output
        assert "NoneType" not in result.output
        assert "FATAL" not in result.output
