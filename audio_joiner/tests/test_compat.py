"""Tests for the compatibility probe.

Changed in 2.5.0: new module (F-E5).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from pydub import AudioSegment

from audio_joiner.core.compat import probe_inputs
from audio_suite_shared.exceptions import AudioConfigValueError

SAMPLE_RATE = 44_100


def _write(path: Path, *, rate: int = SAMPLE_RATE, channels: int = 1) -> None:
    times = np.arange(int(rate * 0.3)) / rate
    samples = (0.3 * np.sin(2 * np.pi * 440 * times) * 32767).astype(np.int16)
    segment = AudioSegment(
        data=samples.tobytes(), sample_width=2, frame_rate=rate, channels=1
    )
    if channels == 2:
        segment = segment.set_channels(2)
    segment.export(str(path), format="wav")


def test_no_inputs_is_refused() -> None:
    with pytest.raises(AudioConfigValueError):
        probe_inputs([])


@pytest.mark.integration
class TestReport:
    def test_matching_streams_are_identical(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.wav")
        _write(tmp_path / "b.wav")

        report = probe_inputs([tmp_path / "a.wav", tmp_path / "b.wav"])

        assert report.identical is True
        assert report.mismatch == ""
        assert report.sample_rate == SAMPLE_RATE
        assert report.channels == 1

    def test_a_different_sample_rate_names_the_file(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.wav")
        _write(tmp_path / "b.wav", rate=22_050)

        report = probe_inputs([tmp_path / "a.wav", tmp_path / "b.wav"])

        assert report.identical is False
        assert "b.wav" in report.mismatch
        assert "22050" in report.mismatch

    def test_a_different_channel_count_is_a_mismatch(self, tmp_path: Path) -> None:
        _write(tmp_path / "a.wav")
        _write(tmp_path / "b.wav", channels=2)

        report = probe_inputs([tmp_path / "a.wav", tmp_path / "b.wav"])

        assert report.identical is False
        assert "2 ch" in report.mismatch
