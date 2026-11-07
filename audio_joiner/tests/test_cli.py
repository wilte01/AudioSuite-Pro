"""Tests for ``audiosuite join``.

Changed in 2.5.0: new module (F-E5).
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
    for name, frequency in (("a.wav", 440), ("b.wav", 880)):
        _tone(400, frequency).export(str(tmp_path / name), format="wav")
    return tmp_path


class TestUsage:
    def test_a_gap_and_a_crossfade_together_is_a_usage_error(
        self, library: Path
    ) -> None:
        result = CliRunner().invoke(
            cli, ["join", str(library), "--gap-ms", "500", "--crossfade-ms", "500"]
        )

        assert result.exit_code == 2
        assert "not both" in result.output

    def test_a_folder_with_one_file_cannot_start(self, tmp_path: Path) -> None:
        _tone(400, 440).export(str(tmp_path / "only.wav"), format="wav")

        result = CliRunner().invoke(cli, ["join", str(tmp_path)])

        assert result.exit_code == 1
        assert "at least two" in result.output


@pytest.mark.integration
class TestRun:
    def test_a_dry_run_reports_the_plan_and_writes_nothing(self, library: Path) -> None:
        result = CliRunner().invoke(
            cli, ["join", str(library), "--dry", "--gap-ms", "200"]
        )

        assert result.exit_code == 0, result.output
        assert "Segments: 2" in result.output
        assert "Length: 00:01.000" in result.output
        assert not (library / "a_joined.wav").exists()
        report = library / "audio_joiner_dry_run_log.txt"
        assert report.is_file()
        assert report.read_text(encoding="utf-8").startswith("AUDIO JOINER REPORT")

    def test_a_live_run_writes_the_joined_file(self, library: Path) -> None:
        result = CliRunner().invoke(cli, ["join", str(library), "--live", "--json"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["reencoded"] is False
        joined = library / "a_joined.wav"
        assert joined.is_file()
        assert len(AudioSegment.from_file(str(joined))) == pytest.approx(800, abs=3)
        assert (library / "audio_joiner_sync_log.txt").is_file()

    def test_the_json_payload_matches_the_declared_schema(self, library: Path) -> None:
        result = CliRunner().invoke(
            cli, ["join", str(library), "--live", "--gap-ms", "100", "--json"]
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["command"] == "join"
        assert payload["tool"] == "audio_joiner"
        assert payload["dry_run"] is False
        assert payload["segments"] == 2
        assert payload["duration_ms"] == 900
        # A gap changes the boundary, so the streams cannot be copied as they
        # are; the payload says the writer re-encoded.
        assert payload["reencoded"] is True
        assert payload["output"].endswith("a_joined.wav")

    def test_an_order_names_the_segments_in_join_order(self, library: Path) -> None:
        result = CliRunner().invoke(
            cli, ["join", str(library), "--live", "--order", "b.wav,a.wav", "--json"]
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["segments"] == 2
        assert payload["output"].endswith("b_joined.wav")
