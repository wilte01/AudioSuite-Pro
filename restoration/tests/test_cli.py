"""Tests for the ``declip`` CLI command.

Exercised through Click's runner, so the option names, the exit contract and the
JSON payload are the ones a script sees.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner, Result
from pydub import AudioSegment

from restoration.cli import declip

from .conftest import channel, peak, sine, thd_db, to_segment

ORIGINAL_PEAK = 0.9886


def run(*args: str) -> Result:
    """Invoke the command with *args*.

    Args:
        *args: Command-line arguments.

    Returns:
        CliRunner's result.
    """
    return CliRunner().invoke(declip, list(args), catch_exceptions=False)


def sha256(path: Path) -> str:
    """Return the file's hex digest.

    Args:
        path: File to hash.

    Returns:
        The SHA-256 digest.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    """Return a folder with one clipped file and one clean file.

    Args:
        tmp_path: The test's own directory.

    Returns:
        The folder.
    """
    folder = tmp_path / "music"
    folder.mkdir()
    clipped = np.clip(sine(ORIGINAL_PEAK), -0.8, 0.8)
    to_segment(clipped).export(str(folder / "clipped.flac"), format="flac")
    to_segment(sine(0.95)).export(str(folder / "clean.flac"), format="flac")
    return folder


class TestOptions:
    """Usage errors are Click's own, before any audio is touched."""

    def test_a_missing_directory_is_a_usage_error(self, tmp_path: Path) -> None:
        result = run(str(tmp_path / "nope"), "--dry")

        assert result.exit_code == 2

    @pytest.mark.parametrize("threshold", ["0", "1.5"])
    def test_a_threshold_outside_the_unit_range_is_a_usage_error(
        self, tmp_path: Path, threshold: str
    ) -> None:
        result = run(str(tmp_path), "--dry", "--threshold", threshold)

        assert result.exit_code == 2
        assert "threshold" in result.output

    def test_a_zero_width_limit_is_a_usage_error(self, tmp_path: Path) -> None:
        result = run(str(tmp_path), "--dry", "--max-run-ms", "0")

        assert result.exit_code == 2
        assert "max-run-ms" in result.output

    def test_the_help_names_the_shipped_defaults(self) -> None:
        result = run("--help")

        assert result.exit_code == 0
        assert "--threshold" in result.output
        assert "--max-run-ms" in result.output
        assert "0.98" in result.output
        assert "50" in result.output


@pytest.mark.integration
class TestDryRun:
    """A dry run reports what it would repair and writes nothing."""

    def test_the_file_is_left_alone(self, library: Path) -> None:
        target = library / "clipped.flac"
        before = sha256(target)

        result = run(str(library), "--dry")

        assert result.exit_code == 0, result.output
        assert "1 repaired" in result.output
        assert "1 clean" in result.output
        assert sha256(target) == before

    def test_json_reports_the_counts(self, library: Path) -> None:
        result = run(str(library), "--dry", "--json")

        payload = json.loads(result.stdout)

        assert payload["total"] == 2
        assert payload["succeeded"] == 1
        assert payload["skipped"] == 1
        assert payload["dry_run"] is True


@pytest.mark.integration
class TestLiveRun:
    """A live run repairs the file it reported."""

    def test_the_repair_is_measurable_on_disk(self, library: Path) -> None:
        before = channel(AudioSegment.from_file(str(library / "clipped.flac")))

        result = run(str(library), "--live")

        assert result.exit_code == 0, result.output
        after = channel(AudioSegment.from_file(str(library / "clipped.flac")))
        assert thd_db(before) - thd_db(after) >= 15.0
        assert peak(after) > peak(before)
        assert abs(peak(after) - ORIGINAL_PEAK) < 0.05

    def test_a_second_run_finds_nothing_to_repair(self, library: Path) -> None:
        run(str(library), "--live")

        again = run(str(library), "--live")

        assert again.exit_code == 0, again.output
        assert "0 repaired" in again.output
        assert "2 clean" in again.output

    def test_an_empty_directory_reports_why(self, tmp_path: Path) -> None:
        result = run(str(tmp_path), "--dry")

        assert "No supported audio files" in result.output
        assert "ERROR:" in result.output
