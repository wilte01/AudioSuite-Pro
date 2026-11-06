"""Tests for ``audiosuite split``.

Changed in 2.5.0: new module (F-E4).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
from click.testing import CliRunner
from pydub import AudioSegment

from audio_suite_shared.cli_app import cli

SAMPLE_RATE = 44_100


def _tone(duration_ms: int, frequency: int) -> AudioSegment:
    times = np.arange(int(SAMPLE_RATE * duration_ms / 1000)) / SAMPLE_RATE
    samples = (0.3 * np.sin(2 * np.pi * frequency * times) * 32767).astype(np.int16)
    return AudioSegment(
        data=samples.tobytes(), sample_width=2, frame_rate=SAMPLE_RATE, channels=1
    )


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    audio = (
        _tone(500, 440)
        + AudioSegment.silent(duration=800, frame_rate=SAMPLE_RATE)
        + _tone(500, 880)
        + AudioSegment.silent(duration=800, frame_rate=SAMPLE_RATE)
        + _tone(500, 1320)
    )
    audio.export(str(tmp_path / "gig.wav"), format="wav")
    return tmp_path


class TestUsage:
    def test_an_unknown_boundary_is_a_usage_error(self, tmp_path: Path) -> None:
        result = CliRunner().invoke(
            cli, ["split", str(tmp_path), "--boundary", "middle"]
        )
        assert result.exit_code == 2

    def test_a_fatal_error_takes_the_shared_exit_contract(self) -> None:
        result = CliRunner().invoke(cli, ["split", "no-such-folder"])
        assert result.exit_code == 2


@pytest.mark.integration
class TestRun:
    def test_a_dry_run_reports_the_plan_and_writes_nothing(self, library: Path) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "split",
                str(library),
                "--dry",
                "--min-silence",
                "400",
                "--min-track",
                "200",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Tracks: 3" in result.output
        assert "Written: 0" in result.output
        assert not (library / "split").exists()

    def test_the_json_payload_matches_the_declared_schema(self, library: Path) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "split",
                str(library),
                "--live",
                "--min-silence",
                "400",
                "--min-track",
                "200",
                "--json",
            ],
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["command"] == "split"
        assert payload["tool"] == "track_splitter"
        assert payload["dry_run"] is False
        assert payload["tracks"] == 3
        assert payload["files_written"] == 3
        # The CUE sheet is on by default, so a live run reports the one it wrote.
        assert payload["cue_files"] == ["gig.cue"]

    def test_a_live_run_writes_tracks_and_a_cue_sheet(self, library: Path) -> None:
        result = CliRunner().invoke(
            cli,
            [
                "split",
                str(library),
                "--live",
                "--min-silence",
                "400",
                "--min-track",
                "200",
                "--cue",
            ],
        )

        assert result.exit_code == 0, result.output
        written = sorted((library / "split").glob("*.wav"))
        assert len(written) == 3
        assert (library / "split" / "gig.cue").exists()
