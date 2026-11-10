"""Tests for the equal-power overlap.

The mixer's arithmetic is checked on decoded frames: the level an equal-power
fade actually produces through the overlap, and the length the combined
segment actually has.

Two identical, in-phase segments gain through the overlap - ``cos + sin``
reaches sqrt(2) at the midpoint - while equal power is what holds the level of
*uncorrelated* material where linear fades would dip by 3 dB.  The level test
below pins the measured +2.14 dB rather than a one-sided "did not dip" bound,
so a switch to linear fades (which would read 0 dB here) fails it.

Changed in 2.5.0: new module (F-E5).

Changed in 2.6.0: the correlated-pair test now locks the measured +2.14 dB and
the sqrt(2) midpoint instead of accepting any level at or above -0.5 dB, and a
second duration case pins the 1000 + 1000 - 400 = 1600 ms result (D141).
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

    def test_two_equal_segments_lose_exactly_one_overlap(self) -> None:
        """Measured joined length: 1000 + 1000 - 400 = 1600 ms, not 2000."""
        mixed = equal_power_mix(_sine(1000, 1000), _sine(1000, 1000), 400)

        assert len(mixed) == pytest.approx(1600, abs=1)
        assert len(mixed[600:1000]) == pytest.approx(400, abs=1)


class TestLevel:
    def test_two_identical_segments_gain_2_14_db_through_the_overlap(self) -> None:
        """Measured, not bounded: a linear fade would read 0.00 dB here.

        For in-phase copies the fade sums to ``cos + sin``, whose mean square
        over the quarter turn is ``1 + 2/pi``, i.e. +2.14 dB; the old assertion
        ("at least -0.5 dB") passed for a linear fade too and locked nothing.
        """
        tone = _sine(1000, 1000)
        mixed = equal_power_mix(tone, tone, 400)
        overlap = mixed[600:1000]

        gain = _rms_dbfs(overlap) - _rms_dbfs(tone)
        assert gain == pytest.approx(2.14, abs=0.1)

    def test_the_midpoint_is_the_equal_power_sum(self) -> None:
        """cos(pi/4) + sin(pi/4) = sqrt(2) times one segment's amplitude."""
        tone = _sine(1000, 1000)
        mixed = equal_power_mix(tone, tone, 400)

        source = np.array(tone.get_array_of_samples(), dtype=np.float64)
        overlap = np.array(mixed[600:1000].get_array_of_samples(), dtype=np.float64)
        midpoint = len(overlap) // 2

        assert overlap[midpoint] == pytest.approx(
            source[midpoint] * np.sqrt(2), rel=0.01
        )

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
