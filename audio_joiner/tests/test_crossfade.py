"""Tests for the equal-power overlap.

The mixer's arithmetic is checked on decoded frames: a fade that keeps two
correlated signals at their level, and one that leaves no step at the seam.

Changed in 2.5.0: new module (F-E5).
"""

from __future__ import annotations

import numpy as np
import pytest
from pydub import AudioSegment

from audio_joiner.core.crossfade import equal_power_mix

SAMPLE_RATE = 44_100
RATE_KWARGS = {"sample_width": 2, "frame_rate": SAMPLE_RATE, "channels": 1}


def _sine(duration_ms: int, frequency: int, amplitude: float = 0.5) -> AudioSegment:
    times = np.arange(int(SAMPLE_RATE * duration_ms / 1000)) / SAMPLE_RATE
    samples = (amplitude * np.sin(2 * np.pi * frequency * times) * 32767).astype(
        np.int16
    )
    return AudioSegment(data=samples.tobytes(), **RATE_KWARGS)


def _rms_dbfs(segment: AudioSegment) -> float:
    samples = np.array(segment.get_array_of_samples(), dtype=np.float64) / 32768.0
    return float(20 * np.log10(np.sqrt(np.mean(samples**2)) + 1e-12))


class TestDuration:
    def test_the_overlap_is_removed_once(self) -> None:
        mixed = equal_power_mix(_sine(500, 100), _sine(400, 300), 100)

        assert len(mixed) == pytest.approx(800, abs=1)


class TestLevel:
    def test_a_correlated_pair_keeps_its_level(self) -> None:
        tone = _sine(500, 100)
        mixed = equal_power_mix(tone, tone, 200)
        overlap = mixed[300:500]

        # Two copies of the same tone: cos + sin peaks at sqrt(2), so the
        # equal-power fade gains up to 3 dB in the middle - what it must not do
        # is dip the way two linear fades would.
        assert _rms_dbfs(overlap) >= _rms_dbfs(tone) - 0.5

    def test_a_silent_tail_fades_in_without_a_step(self) -> None:
        quiet = AudioSegment.silent(duration=400, frame_rate=SAMPLE_RATE)
        mixed = equal_power_mix(_sine(400, 100), quiet, 100)
        samples = np.array(mixed.get_array_of_samples(), dtype=np.float64)

        assert np.max(np.abs(np.diff(samples))) < 400


class TestRefusals:
    def test_a_zero_overlap_is_refused(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            equal_power_mix(_sine(400, 100), _sine(400, 100), 0)

    def test_an_overlap_longer_than_a_segment_is_refused(self) -> None:
        with pytest.raises(ValueError, match="does not fit"):
            equal_power_mix(_sine(100, 100), _sine(400, 100), 200)

    def test_a_channel_mismatch_is_refused(self) -> None:
        stereo = AudioSegment.silent(duration=400, frame_rate=SAMPLE_RATE).set_channels(
            2
        )

        with pytest.raises(ValueError, match="channel count"):
            equal_power_mix(_sine(400, 100), stereo, 100)
