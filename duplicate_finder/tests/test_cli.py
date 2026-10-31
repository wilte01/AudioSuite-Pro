"""Tests for the ``duplicates`` CLI command.

The command is exercised through Click's runner so the option names, the exit
contract and the JSON payload are the ones a user's script sees.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from duplicate_finder.cli import duplicates


def run(*args: str) -> Result:
    """Invoke the command with *args*.

    Args:
        *args: Command-line arguments.

    Returns:
        CliRunner's result.
    """
    return CliRunner().invoke(duplicates, list(args), catch_exceptions=False)


class TestOptions:
    """Input validation, before any audio work happens."""

    def test_a_missing_directory_is_a_click_usage_error(self, tmp_path: Path) -> None:
        result = run(str(tmp_path / "nope"), "--dry")

        assert result.exit_code == 2
        assert "Invalid value" in result.output or "does not exist" in result.output

    @pytest.mark.parametrize("threshold", ["0", "1.5"])
    def test_a_threshold_outside_the_unit_range_is_a_usage_error(
        self, tmp_path: Path, threshold: str
    ) -> None:
        result = run(str(tmp_path), "--dry", "--threshold", threshold)

        assert result.exit_code == 2
        assert "threshold" in result.output

    def test_the_help_names_the_measured_default(self) -> None:
        result = run("--help")

        assert result.exit_code == 0
        assert "--threshold" in result.output
        assert "0.1" in result.output


@pytest.mark.integration
class TestDryRun:
    """The report a first pass prints."""

    def test_a_dry_run_reports_one_group_and_moves_nothing(self, library: Path) -> None:
        before = sorted(path.name for path in library.iterdir())

        result = run(str(library), "--dry")

        assert result.exit_code == 0, result.output
        assert "1 groups" in result.output
        assert "3 duplicates" in result.output
        assert "0 quarantined" in result.output
        assert sorted(path.name for path in library.iterdir()) == before

    def test_json_reports_the_same_counts(self, library: Path) -> None:
        result = run(str(library), "--dry", "--json")

        # Progress goes to stderr and the payload to stdout; ``Result.output``
        # mixes the two, so the document is read from ``stdout`` alone.
        payload = json.loads(result.stdout)

        assert payload["total"] == 7
        assert payload["groups"] == 1
        assert payload["duplicates"] == 3
        assert payload["quarantined"] == 0
        assert payload["dry_run"] is True

    def test_the_report_lines_name_the_files(self, library: Path) -> None:
        result = run(str(library), "--dry", "--json")

        entries = json.loads(result.stdout)["log_entries"]

        assert any("[KEEP]" in line and "song.flac" in line for line in entries)
        assert sum("[DUPLICATE]" in line for line in entries) == 3


@pytest.mark.integration
class TestLiveRun:
    """A live run moves what the dry run reported."""

    def test_the_duplicates_move_into_the_chosen_quarantine(
        self, library: Path, tmp_path: Path
    ) -> None:
        quarantine = tmp_path / "quarantine"

        result = run(str(library), "--live", "--quarantine-dir", str(quarantine))

        assert result.exit_code == 0, result.output
        assert "3 quarantined" in result.output
        assert (library / "song.flac").exists()
        assert sorted(path.name for path in quarantine.iterdir()) == [
            "song_128.mp3",
            "song_320.mp3",
            "song_96.mp3",
        ]

    def test_a_second_run_finds_nothing_left_to_move(
        self, library: Path, tmp_path: Path
    ) -> None:
        quarantine = tmp_path / "quarantine"
        run(str(library), "--live", "--quarantine-dir", str(quarantine))

        again = run(str(library), "--live", "--quarantine-dir", str(quarantine))

        assert again.exit_code == 0, again.output
        assert "0 duplicates" in again.output

    def test_an_empty_directory_is_reported_as_a_run_error(
        self, tmp_path: Path
    ) -> None:
        result = run(str(tmp_path), "--dry")

        # A fatal ``on_error`` is reported in the output; the shared exit
        # contract turns per-file errors and crashes into status 1, not a
        # run that never started, which exits 0 like every peer's.
        assert "No supported audio files" in result.output
        assert "ERROR:" in result.output
