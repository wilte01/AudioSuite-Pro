"""Tests for library_stats.cli — stats command completeness reporting."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from library_stats.cli import _completeness_status, _echo_completeness
from library_stats.core.completeness import (
    TAG_FIELDS,
    CompletenessReport,
    TagCompleteness,
)

# ── Helpers ────────────────────────────────────────────────────────────────────


def _sample_report(directory: str) -> CompletenessReport:
    """Build a deterministic 50%-complete report across every tag field."""
    return CompletenessReport(
        directory=directory,
        total_files=2,
        tag_results={
            tag_field: TagCompleteness(
                field=tag_field,
                total=2,
                present=1,
                missing=1,
                pct_complete=50.0,
                missing_files=tuple(
                    [str(Path(directory) / f"{tag_field}_missing.mp3")]
                ),
            )
            for tag_field in TAG_FIELDS
        },
        overall_pct=50.0,
        duration_secs=0.5,
    )


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# ── _completeness_status ───────────────────────────────────────────────────────


class TestCompletenessStatus:
    @pytest.mark.parametrize(
        ("pct", "expected"),
        [
            (100.0, "complete"),
            (80.1, "complete"),
            (80.0, "partial"),
            (50.0, "partial"),
            (49.9, "needs work"),
            (0.0, "needs work"),
        ],
    )
    def test_status_thresholds(self, pct: float, expected: str) -> None:
        assert _completeness_status(pct) == expected


# ── _echo_completeness ─────────────────────────────────────────────────────────


class TestEchoCompleteness:
    def test_table_lists_every_tag_field(self, capsys: pytest.CaptureFixture) -> None:
        _echo_completeness(_sample_report("/music"))
        captured = capsys.readouterr().out
        assert "Tag Completeness" in captured
        for tag_field in TAG_FIELDS:
            assert _sample_report("/music").tag_results[tag_field].label in captured
        assert "50.0%" in captured
        assert "Overall" in captured

    def test_detail_lists_missing_files(self, capsys: pytest.CaptureFixture) -> None:
        _echo_completeness(_sample_report("/music"), "bpm")
        captured = capsys.readouterr().out
        assert "Files missing BPM (1)" in captured
        assert "bpm_missing.mp3" in captured

    def test_needs_work_status_shown(self, capsys: pytest.CaptureFixture) -> None:
        report = CompletenessReport(
            directory="/music",
            total_files=1,
            tag_results={
                tag_field: TagCompleteness(
                    field=tag_field,
                    total=1,
                    present=0,
                    missing=1,
                    pct_complete=0.0,
                    missing_files=tuple(),
                )
                for tag_field in TAG_FIELDS
            },
            overall_pct=0.0,
        )
        _echo_completeness(report)
        assert "needs work" in capsys.readouterr().out


# ── stats command integration ──────────────────────────────────────────────────


class TestStatsCompletenessCommand:
    @pytest.fixture
    def music_dir(self, tmp_path: Path) -> str:
        (tmp_path / "a.mp3").write_bytes(b"fake")
        (tmp_path / "b.flac").write_bytes(b"fake")
        return str(tmp_path)

    def _invoke(self, runner: CliRunner, music_dir: str, *args: str):
        from audio_suite_shared.cli_app import cli

        # file_processor uses module-level imports (patch the binding);
        # completeness.py still uses function-local imports (patch source).
        scan_stubs = {
            "read_bpm": lambda path: None,
            "read_key": lambda path: None,
            "read_genre": lambda path: None,
            "read_mood": lambda path: None,
            "read_tempo_marking": lambda path: None,
        }
        completeness_stubs = {
            "has_artwork": lambda path: False,
            "read_replaygain": lambda path: None,
            "read_tempo_marking": lambda path: None,
        }
        with (
            patch.multiple("library_stats.core.file_processor", **scan_stubs),
            patch.multiple(
                "audio_suite_shared.tag_helper_reader", **completeness_stubs
            ),
        ):
            return runner.invoke(cli, ["stats", music_dir, *args])

    def test_json_completeness_key_present(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        import json

        result = self._invoke(runner, music_dir, "--json", "--completeness")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert "completeness" in payload
        assert payload["completeness"]["total_files"] == 2
        assert set(payload["completeness"]["tag_results"]) == set(TAG_FIELDS)

    def test_detail_without_completeness_implies_it(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        import json

        result = self._invoke(runner, music_dir, "--json", "--detail", "bpm")
        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert "completeness" in payload

    def test_invalid_detail_choice_rejected(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        result = self._invoke(runner, music_dir, "--json", "--detail", "banana")
        assert result.exit_code != 0
        assert "Invalid value" in result.output


class TestStatsCommandErrorHandling:
    @pytest.fixture
    def music_dir(self, tmp_path: Path) -> str:
        (tmp_path / "a.mp3").write_bytes(b"fake")
        return str(tmp_path)

    def _invoke(self, runner: CliRunner, music_dir: str, *args: str):
        from audio_suite_shared.cli_app import cli

        return runner.invoke(cli, ["stats", music_dir, *args])

    def test_fatal_scan_oserror_reports_and_exits(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        with patch(
            "library_stats.library_stats.scan_directory",
            side_effect=OSError("unreadable directory"),
        ):
            result = self._invoke(runner, music_dir)
        assert result.exit_code == 1
        assert "FATAL" in result.output
        assert "unreadable directory" in result.output

    def test_csv_export_failure_reported_not_fatal(
        self, runner: CliRunner, music_dir: str
    ) -> None:
        out = str(Path(music_dir).parent / "export.csv")
        with patch(
            "library_stats.library_stats.export_csv",
            side_effect=OSError("disk full"),
        ):
            result = self._invoke(runner, music_dir, "--export-csv", out)
        assert result.exit_code == 0
        assert "CSV exported to" not in result.output
        assert "CSV export failed" in result.output
