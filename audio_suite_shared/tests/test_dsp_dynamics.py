"""Locks for the F-S2 dynamics engine — measured, never read back.

Every acceptance figure here is measured from the rendered audio (or from the
rendered WAV read back by the shared probe), because a compressor that is only
tested through its settings cannot tell a working stage from a fabricated one.

Changed in 2.7.0: new locks for the compressor and limiter engine (F-S2).
"""

from __future__ import annotations

import dataclasses
import os
import tempfile

import numpy as np
import pytest
import soundfile

from audio_suite_shared import dsp_dynamics
from audio_suite_shared.audio_probe import measure_loudness
from audio_suite_shared.dsp_dynamics import (
    CompressorSettings,
    LimiterSettings,
    apply_dynamics,
    measure_levels,
)
from audio_suite_shared.exceptions import AudioConfigValueError

SR = 44_100
TONE_HZ = 1_000.0


def _tone_db(peak_db: float, seconds: float = 1.0) -> np.ndarray:
    """Return a 1 kHz tone whose peak is *peak_db* dBFS, shape (1, samples)."""
    t = np.arange(int(SR * seconds), dtype=np.float32) / SR
    amplitude = 10.0 ** (peak_db / 20.0)
    return (amplitude * np.sin(2.0 * np.pi * TONE_HZ * t)).astype(np.float32)[None, :]


def _rms_db(audio: np.ndarray) -> float:
    """Return the RMS level of *audio* in dB."""
    values = np.asarray(audio, dtype=np.float64)
    return float(20.0 * np.log10(np.sqrt(np.mean(values**2))))


def _window_db(audio: np.ndarray, start_s: float, end_s: float) -> float:
    """Return the RMS level of one time window in dB."""
    start = int(start_s * SR)
    end = int(end_s * SR)
    return _rms_db(np.asarray(audio)[:, start:end])


def _tail_db(audio: np.ndarray) -> float:
    """Return the RMS of the back half, past the attack transient."""
    return _rms_db(np.asarray(audio)[:, len(np.asarray(audio)[0]) // 2 :])


def _peak_db(audio: np.ndarray) -> float:
    """Return the sample peak of *audio* in dBFS."""
    return float(20.0 * np.log10(np.max(np.abs(np.asarray(audio, dtype=np.float64)))))


class TestCompressorStaticCurve:
    def test_a_tone_above_the_threshold_is_reduced(self) -> None:
        tone = _tone_db(-14.0)
        rendered, _report = apply_dynamics(
            tone, CompressorSettings(threshold_db=-20.0, ratio=4.0), None, SR
        )

        reduction = _tail_db(tone) - _tail_db(rendered)

        # The hard-knee ideal is 6 dB over the threshold * (1 - 1/4) = 4.5 dB.
        # The installed compressor's fixed soft knee costs a measured ~0.86 dB
        # at every level, so the lock is the measured curve within a knee-wide
        # tolerance rather than a formula the renderer does not implement.
        assert reduction == pytest.approx(4.5, abs=1.0)

    def test_the_static_curve_has_the_requested_slope(self) -> None:
        settings = CompressorSettings(threshold_db=-20.0, ratio=4.0)
        quiet_in = _tone_db(-14.0)
        loud_in = _tone_db(-8.0)

        quiet_out, _ = apply_dynamics(quiet_in, settings, None, SR)
        loud_out, _ = apply_dynamics(loud_in, settings, None, SR)

        quiet_reduction = _tail_db(quiet_in) - _tail_db(quiet_out)
        loud_reduction = _tail_db(loud_in) - _tail_db(loud_out)

        # 6 dB more input at 4:1 must buy 4.5 dB more reduction; the soft knee
        # is level-independent, so it cancels out of the slope.
        assert loud_reduction - quiet_reduction == pytest.approx(4.5, abs=0.2)

    def test_makeup_gain_is_applied_after_compression(self) -> None:
        tone = _tone_db(-14.0)
        base = CompressorSettings(threshold_db=-20.0, ratio=4.0)
        boosted = dataclasses.replace(base, makeup_db=3.0)

        plain_out, _ = apply_dynamics(tone, base, None, SR)
        boosted_out, report = apply_dynamics(tone, boosted, None, SR)

        assert _tail_db(boosted_out) - _tail_db(plain_out) == pytest.approx(
            3.0, abs=0.2
        )
        # The report must not present makeup gain as extra reduction.
        assert report.max_reduction_db == pytest.approx(
            _tail_db(tone) - _tail_db(boosted_out) + 3.0, abs=0.5
        )


class TestLimiterCeiling:
    def test_the_ceiling_holds_with_no_overshoot(self) -> None:
        tone = _tone_db(-0.9)  # 5.1 dB over a -6 dBTP ceiling

        rendered, report = apply_dynamics(
            tone, None, LimiterSettings(ceiling_dbtp=-6.0), SR
        )

        assert _peak_db(rendered) <= -6.0 + 0.1
        assert report.output_true_peak_dbtp <= -6.0 + 0.2
        assert _peak_db(rendered) < _peak_db(tone)

    def test_the_limiter_runs_without_a_compressor(self) -> None:
        tone = _tone_db(-0.9)

        rendered, report = apply_dynamics(
            tone, None, LimiterSettings(ceiling_dbtp=-3.0), SR
        )

        assert rendered.shape == tone.shape
        assert report.blocks > 0
        assert report.output_lufs < 0.0


class TestReportIsMeasured:
    def test_the_report_matches_the_probe_reading_of_the_rendered_wav(self) -> None:
        tone = _tone_db(-12.0)
        settings = CompressorSettings(threshold_db=-24.0, ratio=3.0)
        limiter = LimiterSettings(ceiling_dbtp=-3.0)

        rendered, report = apply_dynamics(tone, settings, limiter, SR)

        with tempfile.TemporaryDirectory(prefix="dyn-report-") as tmp:
            path = os.path.join(tmp, "rendered.wav")
            soundfile.write(
                path, np.asarray(rendered, dtype=np.float32).T, SR, subtype="FLOAT"
            )
            independent = measure_loudness(path)

        assert report.output_lufs == pytest.approx(independent.integrated_lufs, abs=0.2)
        assert independent.true_peak_dbtp is not None
        assert report.output_true_peak_dbtp == pytest.approx(
            independent.true_peak_dbtp, abs=0.2
        )

    def test_the_total_reduction_is_the_measured_loudness_change(self) -> None:
        tone = _tone_db(-10.0)
        settings = CompressorSettings(threshold_db=-30.0, ratio=4.0, makeup_db=2.0)

        rendered, report = apply_dynamics(tone, settings, None, SR)

        before, _ = measure_levels(tone, SR)
        after, _ = measure_levels(rendered, SR)
        assert report.total_reduction_db == pytest.approx(before - after + 2.0, abs=0.2)


class TestAttackAndRelease:
    def test_reduction_engages_on_the_burst_and_recovers_after_it(self) -> None:
        quiet = _tone_db(-40.0)
        loud = _tone_db(-6.0)
        burst = np.concatenate([quiet, loud, quiet], axis=1)
        settings = CompressorSettings(
            threshold_db=-30.0,
            ratio=8.0,
            attack_ms=5.0,
            release_ms=150.0,
        )

        rendered, report = apply_dynamics(burst, settings, None, SR)

        pre = _window_db(burst, 0.4, 0.9) - _window_db(rendered, 0.4, 0.9)
        during = _window_db(burst, 1.5, 1.9) - _window_db(rendered, 1.5, 1.9)
        after = _window_db(burst, 2.7, 2.95) - _window_db(rendered, 2.7, 2.95)

        assert during > pre + 3.0, "the burst must be reduced far more than the bed"
        assert after < during - 3.0, "the gain must recover after the burst"
        assert report.max_reduction_db > report.mean_reduction_db


class TestBypass:
    def test_a_bypassed_pair_returns_the_input_untouched(self) -> None:
        tone = _tone_db(-6.0)

        rendered, report = apply_dynamics(
            tone,
            CompressorSettings(bypass=True),
            LimiterSettings(bypass=True),
            SR,
        )

        assert rendered is tone
        assert np.array_equal(rendered, tone)
        assert report.max_reduction_db == 0.0
        assert report.mean_reduction_db == 0.0
        assert report.total_reduction_db == 0.0
        assert report.blocks == 0

    def test_no_settings_at_all_is_the_same_bypass(self) -> None:
        tone = _tone_db(-6.0)

        rendered, report = apply_dynamics(tone, None, None, SR)

        assert rendered is tone
        assert report.blocks == 0


class TestSettingsValidation:
    @pytest.mark.parametrize(
        "kwargs",
        [
            {"knee_db": 3.0},
            {"ratio": 0.5},
            {"ratio": 25.0},
            {"threshold_db": 3.0},
            {"threshold_db": -80.0},
            {"attack_ms": 0.0},
            {"release_ms": 0.0},
            {"makeup_db": 30.0},
        ],
    )
    def test_the_compressor_refuses_unrenderable_settings(
        self, kwargs: dict[str, float]
    ) -> None:
        with pytest.raises(AudioConfigValueError):
            CompressorSettings(**kwargs)

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"ceiling_dbtp": 1.0},
            {"ceiling_dbtp": -30.0},
            {"lookahead_ms": -1.0},
            {"lookahead_ms": 50.0},
            {"release_ms": 0.0},
        ],
    )
    def test_the_limiter_refuses_unrenderable_settings(
        self, kwargs: dict[str, float]
    ) -> None:
        with pytest.raises(AudioConfigValueError):
            LimiterSettings(**kwargs)

    def test_a_knee_refusal_names_the_installed_limitation(self) -> None:
        with pytest.raises(AudioConfigValueError, match="fixed soft knee"):
            CompressorSettings(knee_db=6.0)


class TestMeasureLevels:
    def test_a_tone_measures_near_its_generated_level(self) -> None:
        tone = _tone_db(-20.0)

        lufs, true_peak = measure_levels(tone, SR)

        assert lufs == pytest.approx(-23.0, abs=1.0)
        assert true_peak == pytest.approx(-20.0, abs=1.0)

    def test_the_block_helper_counts_only_whole_blocks(self) -> None:
        levels = dsp_dynamics._block_rms_db(np.zeros((1, 100), dtype=np.float32), 30)

        assert levels.size == 3
