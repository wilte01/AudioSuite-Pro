"""Tests for asx_extractor CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

# Import the CLI module so @cli.command() decorators register on the group.
import asx_extractor.cli  # noqa: F401
from asx_extractor import cli as asx_cli
from asx_extractor.core import asx_parser, file_ops
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


# ---------------------------------------------------------------------------
# Moved from test_cli_run.py (iteration-9 G5.1): tests for
# asx_extractor/cli.py::run_cli_extraction — the orchestration layer that
# walks a directory of .asx playlists, parses each one, copies the resolved
# audio files, removes the ASX files, and writes a log.
#
# Core helpers are patched at their source modules because they are
# imported lazily inside run_cli_extraction.  (The asx_extractor.cli
# module is bound as `asx_cli` here: this file's `cli` name is the
# shared click group from audio_suite_shared.cli_base.)
# ---------------------------------------------------------------------------

_SUCCESS = {
    "success": True,
    "asx_fn": "a.asx",
    "asx_path": None,  # type: ignore[assignment]
    "audio_path": Path("song.mp3"),
}
_FAILURE = {
    "success": False,
    "asx_fn": "bad.asx",
    "audio_path": "N/A",
    "reason": "could not resolve audio",
}


def _fill(tgt: dict, **kw) -> dict:
    tgt.update(kw)
    return tgt


class TestRunCliExtraction:
    def _make_asx(self, tmp_path: Path, *names: str) -> None:
        for n in names:
            (tmp_path / n).write_text("<ASX/>")

    def test_empty_dir_completes_zero(self, tmp_path: Path) -> None:
        calls: dict = {}
        asx_cli.run_cli_extraction(
            str(tmp_path), on_complete=lambda **kw: calls.update(kw)
        )
        assert calls["total"] == 0
        assert calls["processed"] == 0
        assert calls["errors"] == 0
        assert calls["skipped"] == 0

    def test_default_callbacks_are_noops(self, tmp_path: Path) -> None:
        self._make_asx(tmp_path, "a.asx")
        with (
            patch.object(asx_parser, "process_asx_file", return_value=_SUCCESS),
            patch.object(file_ops, "copy_audio_file", return_value=True),
            patch.object(file_ops, "remove_asx_file", return_value=True),
            patch.object(file_ops, "write_extraction_log"),
        ):
            asx_cli.run_cli_extraction(str(tmp_path))  # no callbacks -> must not raise

    def test_success_path_copies_and_removes(self, tmp_path: Path) -> None:
        self._make_asx(tmp_path, "a.asx")
        asx_path = tmp_path / "a.asx"
        calls: dict = {}
        progress: list[dict] = []
        with (
            patch.object(
                asx_parser,
                "process_asx_file",
                return_value=_fill(dict(_SUCCESS), asx_path=asx_path),
            ),
            patch.object(file_ops, "copy_audio_file", return_value=True) as copy,
            patch.object(file_ops, "remove_asx_file", return_value=True) as remove,
            patch.object(file_ops, "write_extraction_log") as write_log,
        ):
            asx_cli.run_cli_extraction(
                str(tmp_path),
                on_progress=lambda **kw: progress.append(kw),
                on_complete=lambda **kw: calls.update(kw),
            )
        copy.assert_called_with(Path("song.mp3"), tmp_path)
        remove.assert_called_with(asx_path)
        write_log.assert_called_once()
        assert calls["processed"] == 1
        assert calls["failures"] == 0
        assert calls["errors"] == 0
        assert any("[OK]" in p["display_text"] for p in progress)

    def test_copy_failure_records_copy_failed(self, tmp_path: Path) -> None:
        self._make_asx(tmp_path, "a.asx")
        asx_path = tmp_path / "a.asx"
        calls: dict = {}
        with (
            patch.object(
                asx_parser,
                "process_asx_file",
                return_value=_fill(dict(_SUCCESS), asx_path=asx_path),
            ),
            patch.object(file_ops, "copy_audio_file", return_value=False),
            patch.object(file_ops, "remove_asx_file") as remove,
            patch.object(file_ops, "write_extraction_log"),
        ):
            asx_cli.run_cli_extraction(
                str(tmp_path), on_complete=lambda **kw: calls.update(kw)
            )
        remove.assert_not_called()
        assert calls["processed"] == 0
        assert calls["errors"] == 1
        assert calls["failures"] == 1

    def test_remove_failure_records_removal_failed(self, tmp_path: Path) -> None:
        self._make_asx(tmp_path, "a.asx")
        asx_path = tmp_path / "a.asx"
        calls: dict = {}
        with (
            patch.object(
                asx_parser,
                "process_asx_file",
                return_value=_fill(dict(_SUCCESS), asx_path=asx_path),
            ),
            patch.object(file_ops, "copy_audio_file", return_value=True),
            patch.object(file_ops, "remove_asx_file", return_value=False),
            patch.object(file_ops, "write_extraction_log"),
        ):
            asx_cli.run_cli_extraction(
                str(tmp_path), on_complete=lambda **kw: calls.update(kw)
            )
        assert calls["processed"] == 0
        assert calls["errors"] == 1
        assert calls["failures"] == 1

    def test_parse_failure_is_logged_as_fail(self, tmp_path: Path) -> None:
        self._make_asx(tmp_path, "bad.asx")
        calls: dict = {}
        progress: list[dict] = []
        with (
            patch.object(asx_parser, "process_asx_file", return_value=_FAILURE),
            patch.object(file_ops, "copy_audio_file"),
            patch.object(file_ops, "remove_asx_file"),
            patch.object(file_ops, "write_extraction_log"),
        ):
            asx_cli.run_cli_extraction(
                str(tmp_path),
                on_progress=lambda **kw: progress.append(kw),
                on_complete=lambda **kw: calls.update(kw),
            )
        assert calls["errors"] == 1
        assert calls["failures"] == 1
        assert any("[FAIL]" in p["display_text"] for p in progress)

    def test_dry_run_skips_copy_and_remove(self, tmp_path: Path) -> None:
        self._make_asx(tmp_path, "a.asx")
        with (
            patch.object(
                asx_parser,
                "process_asx_file",
                return_value=_SUCCESS,
            ),
            patch.object(file_ops, "copy_audio_file") as copy,
            patch.object(file_ops, "remove_asx_file") as remove,
            patch.object(file_ops, "write_extraction_log") as write_log,
        ):
            asx_cli.run_cli_extraction(str(tmp_path), is_dry_run=True)
        copy.assert_not_called()
        remove.assert_not_called()
        mode = write_log.call_args.kwargs["mode_label"]
        assert "Dry Run" in mode

    def test_oserror_or_value_error_triggers_fatal(self, tmp_path: Path) -> None:
        self._make_asx(tmp_path, "a.asx")
        calls: dict = {}
        with (
            patch.object(
                asx_parser,
                "process_asx_file",
                side_effect=ValueError("boom"),
            ),
            patch.object(file_ops, "write_extraction_log"),
        ):
            asx_cli.run_cli_extraction(
                str(tmp_path), on_complete=lambda **kw: calls.update(kw)
            )
        assert calls["errors"] == 1
        assert calls["total"] == 0
