"""Tests for ``audiosuite pitchtime``.

The run is asserted through the real parser and the real engine, and the
written file is decoded: no test reads back the setting it passed.

Changed in 2.7.0: new module (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

from __future__ import annotations

import json
from pathlib import Path

import librosa
import numpy as np
import pytest
from click.testing import CliRunner
from pydub import AudioSegment

from audio_suite_shared.cli_app import cli

SAMPLE_RATE = 44_100


def _write_tone(path: Path, *, frequency: float = 440.0, seconds: float = 1.0) -> Path:
    times = np.arange(int(SAMPLE_RATE * seconds)) / SAMPLE_RATE
    samples = (0.3 * np.sin(2 * np.pi * frequency * times) * 32767).astype(np.int16)
    AudioSegment(
        data=samples.tobytes(), sample_width=2, frame_rate=SAMPLE_RATE, channels=1
    ).export(str(path), format="wav")
    return path


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    _write_tone(tmp_path / "song.wav")
    return tmp_path


class TestUsage:
    def test_neither_mode_is_a_usage_error(self, library: Path) -> None:
        result = CliRunner().invoke(cli, ["pitchtime", str(library)])

        assert result.exit_code == 2
        assert "Set --rate" in result.output

    def test_both_modes_is_a_usage_error(self, library: Path) -> None:
        result = CliRunner().invoke(
            cli, ["pitchtime", str(library), "--rate", "1.2", "--semitones", "2"]
        )

        assert result.exit_code == 2
        assert "not both" in result.output

    def test_a_rate_the_engine_cannot_honour_is_a_usage_error(
        self, library: Path
    ) -> None:
        result = CliRunner().invoke(cli, ["pitchtime", str(library), "--rate", "9"])

        assert result.exit_code == 2
        assert "between" in result.output


@pytest.mark.integration
class TestRun:
    def test_a_tempo_run_writes_the_shorter_file_at_the_same_pitch(
        self, library: Path
    ) -> None:
        result = CliRunner().invoke(
            cli, ["pitchtime", str(library), "--rate", "1.25", "--json"]
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["command"] == "pitchtime"
        assert payload["tool"] == "pitch_time"
        assert payload["mode"] == "tempo"
        assert payload["rate"] == pytest.approx(1.25)
        assert payload["written"] == 1
        written = library / "song_tempo_1.25.wav"
        assert written.is_file()
        decoded, rate = librosa.load(str(written), sr=None, mono=True)
        assert rate == SAMPLE_RATE
        assert len(decoded) / rate == pytest.approx(0.8, abs=0.005)

    def test_a_pitch_run_writes_the_shifted_file(self, library: Path) -> None:
        result = CliRunner().invoke(
            cli, ["pitchtime", str(library), "--semitones", "12", "--json"]
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["mode"] == "pitch"
        assert (library / "song_pitch_+12st.wav").is_file()

    def test_a_dry_run_writes_no_audio_and_names_its_own_report(
        self, library: Path
    ) -> None:
        result = CliRunner().invoke(
            cli, ["pitchtime", str(library), "--rate", "1.25", "--dry", "--json"]
        )

        assert result.exit_code == 0, result.output
        assert not (library / "song_tempo_1.25.wav").exists()
        assert (library / "pitch_time_dry_run_log.txt").is_file()
        assert not (library / "pitch_time_sync_log.txt").exists()

    def test_a_neutral_setting_reports_a_skip_not_a_failure(
        self, library: Path
    ) -> None:
        result = CliRunner().invoke(
            cli, ["pitchtime", str(library), "--rate", "1.0", "--json"]
        )

        assert result.exit_code == 0, result.output
        payload = json.loads(result.stdout)
        assert payload["written"] == 0
        assert payload["skipped"] == 1
        assert payload["errors"] == 0
        assert not (library / "song_tempo_1.wav").exists()

    def test_a_missing_folder_is_a_usage_error(self, tmp_path: Path) -> None:
        """Click's ``exists=True`` refuses the path before the run starts."""
        result = CliRunner().invoke(
            cli, ["pitchtime", str(tmp_path / "absent"), "--rate", "1.25"]
        )

        assert result.exit_code == 2
        assert "does not exist" in result.output
