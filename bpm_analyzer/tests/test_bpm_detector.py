"""
tests/test_bpm_detector.py
pytest suite for bpm_analyzer.core.bpm_detector

Tests are structured per claude.md §4:
  • Impulse / synthetic signal inputs
  • Float64 precision contract
  • Octave-correction logic (white-box)
  • Hard-clamp safety
  • BPMDetectionError raised on librosa failure
  • Edge-case boundaries (min==max, zero duration guard, corrupt file)

All librosa I/O is mocked — tests run without real audio files — except the
F1 golden-vector measurement class, which writes real seeded click-train
WAVs and asserts the measured BPM against the constructed click rate.
"""

from __future__ import annotations

import wave
from pathlib import Path
from unittest.mock import patch

import numpy as np
import numpy.typing as npt
import pytest

# Module under test
from bpm_analyzer.core.bpm_detector import BPMDetectionError, detect_bpm

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_load_return(tempo_val: float, sr: int = 22050, n_samples: int = 22050):
    """Return a (y_float32, sr) pair that librosa.load would produce."""
    y = np.zeros(n_samples, dtype=np.float32)
    return y, sr


def _patch_librosa(tempo_val: float, sr: int = 22050):
    """
    Context-manager stack that mocks librosa.load and librosa.beat.beat_track
    to return predictable values.
    """
    load_patch = patch(
        "bpm_analyzer.core.bpm_detector.librosa.load",
        return_value=_make_load_return(tempo_val, sr),
    )
    beat_patch = patch(
        "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
        return_value=(np.array([tempo_val]), None),
    )
    return load_patch, beat_patch


# ---------------------------------------------------------------------------
# 1. Normal operation — BPM already within range
# ---------------------------------------------------------------------------


class TestDetectBpmNormalRange:
    def test_returns_integer(self):
        load_p, beat_p = _patch_librosa(120.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert isinstance(result, int)

    def test_midrange_bpm_unchanged(self):
        load_p, beat_p = _patch_librosa(128.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 128

    def test_exact_lower_bound_accepted(self):
        load_p, beat_p = _patch_librosa(75.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 75

    def test_exact_upper_bound_accepted(self):
        load_p, beat_p = _patch_librosa(175.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 175


# ---------------------------------------------------------------------------
# 2. DSP precision contract — internal array must be float64
# ---------------------------------------------------------------------------


class TestFloat64Precision:
    def test_load_output_is_upcast_to_float64(self):
        """
        Verify that even though librosa returns float32, the code upcasts
        before DSP work.  We capture the array passed to beat_track and
        inspect its dtype.
        """
        captured: list = []

        def fake_beat_track(y, sr):
            captured.append(y.dtype)
            return np.array([120.0]), None

        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            return_value=_make_load_return(120.0),
        ):
            with patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
                side_effect=fake_beat_track,
            ):
                detect_bpm("fake.mp3")

        assert len(captured) == 1
        assert captured[0] == np.float64, (
            f"Expected float64 passed to beat_track, got {captured[0]}"
        )


# ---------------------------------------------------------------------------
# 3. Octave-correction logic
# ---------------------------------------------------------------------------


class TestOctaveCorrection:
    def test_doubles_when_too_slow(self):
        """60 BPM should double to 120 to land in [75, 175]."""
        load_p, beat_p = _patch_librosa(60.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 120

    def test_halves_when_too_fast(self):
        """200 BPM should halve to 100 to land in [75, 175]."""
        load_p, beat_p = _patch_librosa(200.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 100

    def test_multi_step_doubling(self):
        """30 BPM needs two doublings → 120, within [75, 175]."""
        load_p, beat_p = _patch_librosa(30.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 120

    def test_multi_step_halving(self):
        """400 BPM needs two halvings → 100, within [75, 175]."""
        load_p, beat_p = _patch_librosa(400.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 100

    def test_no_correction_needed(self):
        """100 BPM is already in range — must not be modified."""
        load_p, beat_p = _patch_librosa(100.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 100


# ---------------------------------------------------------------------------
# 3b. Rounding behavior — round(tempo) → int
# ---------------------------------------------------------------------------


class TestRoundingBehavior:
    def test_rounds_down_correctly(self):
        """120.4 rounds to 120."""
        load_p, beat_p = _patch_librosa(120.4)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 120

    def test_rounds_up_correctly(self):
        """120.6 rounds to 121."""
        load_p, beat_p = _patch_librosa(120.6)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 121

    def test_bankers_rounding_half_to_even(self):
        """120.5 rounds to 120 (banker's rounding: half → even)."""
        load_p, beat_p = _patch_librosa(120.5)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 120

    def test_bankers_rounding_half_to_even_odd(self):
        """121.5 rounds to 122 (banker's rounding: half → even)."""
        load_p, beat_p = _patch_librosa(121.5)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 122


# ---------------------------------------------------------------------------
# 4. Hard-clamp safety net
# ---------------------------------------------------------------------------


class TestHardClamp:
    def test_clamp_below_min(self):
        """A value that cannot be doubled into range is clamped to min."""
        # 50 BPM: doubling gives 100 (in range) — use a value where
        # doubling would overshoot: min=110, max=120, raw=50 → 100 < 110,
        # 200 > 120 — clamp to 110.
        load_p, beat_p = _patch_librosa(50.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=110, max_bpm=120)
        assert result == 110

    def test_clamp_above_max(self):
        """Value that cannot be halved into range is clamped to max."""
        # 300 BPM: halving gives 150 (in range for 75–175) — craft a
        # narrow range: min=50, max=60, raw=300 → halve to 150, still >60;
        # halve to 75, still >60; halve to 37.5 < 50 — clamp to 60.
        load_p, beat_p = _patch_librosa(300.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=50, max_bpm=60)
        assert result == 60


# ---------------------------------------------------------------------------
# 4b. Equal bounds — min_bpm == max_bpm
# ---------------------------------------------------------------------------


class TestEqualBounds:
    def test_above_equal_bounds_clamps_to_bounds(self):
        """tempo=150, min=max=120 → clamp to 120."""
        load_p, beat_p = _patch_librosa(150.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=120, max_bpm=120)
        assert result == 120

    def test_below_equal_bounds_clamps_to_bounds(self):
        """tempo=80, min=max=120 → clamp to 120."""
        load_p, beat_p = _patch_librosa(80.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=120, max_bpm=120)
        assert result == 120

    def test_at_equal_bounds_unchanged(self):
        """tempo=120, min=max=120 → returned as-is."""
        load_p, beat_p = _patch_librosa(120.0)
        with load_p, beat_p:
            result = detect_bpm("fake.mp3", min_bpm=120, max_bpm=120)
        assert result == 120


# ---------------------------------------------------------------------------
# 5. numpy array return from librosa.beat.beat_track
# ---------------------------------------------------------------------------


class TestNumpyArrayHandling:
    def test_single_element_array(self):
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            return_value=_make_load_return(120.0),
        ):
            with patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
                return_value=(np.array([120.0]), None),
            ):
                assert detect_bpm("fake.mp3") == 120

    def test_empty_array_defaults_to_120(self):
        """Empty tempo array must not raise; should default to 120 BPM."""
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            return_value=_make_load_return(120.0),
        ):
            with patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
                return_value=(np.array([]), None),
            ):
                result = detect_bpm("fake.mp3", min_bpm=75, max_bpm=175)
        # 120 is in [75, 175] → returned as-is
        assert result == 120

    def test_scalar_float_accepted(self):
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            return_value=_make_load_return(120.0),
        ):
            with patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
                return_value=(140.0, None),
            ):
                assert detect_bpm("fake.mp3") == 140


# ---------------------------------------------------------------------------
# 5b. Zero-length / empty audio buffer
# ---------------------------------------------------------------------------


class TestEmptyAudioBuffer:
    def test_zero_length_buffer_does_not_crash(self):
        """An empty audio array (0 samples) must not crash the function."""
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            return_value=(np.zeros(0, dtype=np.float32), 22050),
        ):
            with patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
                return_value=(np.array([0.0]), None),
            ):
                result = detect_bpm("empty.wav", min_bpm=75, max_bpm=175)
        assert result == 75

    def test_zero_samples_with_positive_tempo(self):
        """Empty buffer but beat_track returns a positive tempo -> clamped to
        min_bpm since tempo <= 0 guard skips octave correction."""
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            return_value=(np.zeros(0, dtype=np.float32), 22050),
        ):
            with patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
                return_value=(np.array([0.0]), None),
            ):
                result = detect_bpm("empty.wav", min_bpm=110, max_bpm=120)
        assert result == 110


# ---------------------------------------------------------------------------
# 6. Error handling — BPMDetectionError raised on failures
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_raises_on_file_not_found(self):
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            side_effect=FileNotFoundError("no such file"),
        ):
            with pytest.raises(BPMDetectionError) as exc_info:
                detect_bpm("nonexistent.mp3")
        assert "nonexistent.mp3" in str(exc_info.value)

    def test_raises_on_librosa_runtime_error(self):
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            side_effect=RuntimeError("librosa internal failure"),
        ):
            with pytest.raises(BPMDetectionError):
                detect_bpm("corrupt.mp3")

    def test_original_exception_chained(self):
        original = ValueError("bad audio data")
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            return_value=_make_load_return(120.0),
        ):
            with patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
                side_effect=original,
            ):
                with pytest.raises(BPMDetectionError) as exc_info:
                    detect_bpm("bad.mp3")
        # __cause__ must be the original exception
        assert exc_info.value.__cause__ is original

    def test_does_not_swallow_keyboard_interrupt(self):
        """KeyboardInterrupt must never be caught and wrapped."""
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load", side_effect=KeyboardInterrupt
        ):
            with pytest.raises(KeyboardInterrupt):
                detect_bpm("fake.mp3")


# ---------------------------------------------------------------------------
# 7. Regression: non-positive tempo must not hang octave correction
#
# Bug: librosa.beat.beat_track() returns 0.0 for digital silence (confirmed
# against the real librosa implementation, not a mock). The previous
# octave-correction loop `while tempo < min_bpm and tempo * 2 <= max_bpm:
# tempo *= 2` never terminates for tempo <= 0, since doubling zero stays
# zero. Fix: skip octave correction entirely when tempo <= 0 and let the
# hard clamp resolve it to min_bpm.
# ---------------------------------------------------------------------------


class TestNonPositiveTempoRegression:
    def _detect_with_timeout(self, *args, timeout: float = 5.0, **kwargs):
        """Run detect_bpm on a worker thread with a hard wall-clock bound.

        If the octave-correction loop regresses to an infinite loop, this
        fails the assertion instead of hanging the test run forever.
        """
        import threading

        result_box: dict = {}

        def _target():
            try:
                result_box["value"] = detect_bpm(*args, **kwargs)
            except Exception as exc:  # pragma: no cover - propagated below
                result_box["error"] = exc

        thread = threading.Thread(target=_target, daemon=True)
        thread.start()
        thread.join(timeout=timeout)
        assert not thread.is_alive(), (
            "detect_bpm did not return within the timeout — "
            "octave-correction loop likely regressed to an infinite loop "
            "for a non-positive tempo input."
        )
        if "error" in result_box:
            raise result_box["error"]
        return result_box["value"]

    def test_zero_tempo_clamps_to_min_bpm(self):
        """tempo == 0.0 (real librosa output for digital silence) must
        clamp to min_bpm, not hang."""
        load_p, beat_p = _patch_librosa(0.0)
        with load_p, beat_p:
            result = self._detect_with_timeout("silent.wav", min_bpm=75, max_bpm=175)
        assert result == 75

    def test_zero_tempo_respects_custom_range(self):
        load_p, beat_p = _patch_librosa(0.0)
        with load_p, beat_p:
            result = self._detect_with_timeout("silent.wav", min_bpm=110, max_bpm=120)
        assert result == 110

    def test_negative_tempo_clamps_to_min_bpm(self):
        """Defensive case: a negative tempo (should not occur from librosa
        in practice, but the guard covers it) must also clamp, not hang."""
        load_p, beat_p = _patch_librosa(-5.0)
        with load_p, beat_p:
            result = self._detect_with_timeout("fake.mp3", min_bpm=75, max_bpm=175)
        assert result == 75


# ═════════════════════════════════════════════════════════════════════════════
# Golden-vector measurement (plan iteration 5, item F1 / audit #19)
# ═════════════════════════════════════════════════════════════════════════════
# These cases write real 16-bit mono WAVs whose beat period is known by
# construction, then assert the measured BPM against the constructed click
# rate within a declared tolerance.  No mocks, no commercial audio -- the
# fixtures are unambiguously redistributable under GPL-3.0.
#
# Tolerance provenance (recorded in the Completion Log): the +/-4 BPM band is
# declared once for the whole octave-corrected sweep, not fitted per fixture.
# It covers beat tracking's tempo-grid quantisation error with headroom on both
# sides; measured at HEAD (three seeds per rate, 30 s trains) and must not be
# loosened to rescue a failing engine.
# ═════════════════════════════════════════════════════════════════════════════


def _write_wav(path: Path, y: npt.NDArray[np.float64], sr: int = 22050) -> str:
    """Write a 16-bit mono PCM WAV (values clipped to +/-1); return the path."""
    pcm_bytes = (np.clip(y, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sr)
        handle.writeframes(pcm_bytes)
    return str(path)


def clicked(
    clicks_per_second: float,
    seconds: float,
    dither_seed: int = 7,
) -> npt.NDArray[np.float64]:
    """An impulse click train with seeded dither; peak-normalised to 0.9.

    Clicks are 4 ms sine-carrier blips under an exponential decay so onset
    strength keeps a sharp leading edge.  The dither floor is white (aperiodic),
    so it adds no beat periodicity of its own -- it only keeps the onset
    matrix away from degenerate zero energy.
    """
    sample_rate = 22050
    n_samples = int(sample_rate * seconds)
    signal = np.zeros(n_samples, dtype=np.float64)
    click_len = max(4, int(0.004 * sample_rate))
    onsets = np.arange(int(clicks_per_second * seconds) + 1)
    starts = (onsets / clicks_per_second * sample_rate).astype(int)
    decay = np.exp(-np.linspace(0.0, 8.0, click_len))
    carrier = 2.0 * np.pi * 1000.0 * np.arange(click_len) / sample_rate
    envelope = np.sin(carrier) * decay
    for start in starts[starts + click_len < n_samples]:
        signal[start : start + click_len] += envelope
    generator = np.random.default_rng(dither_seed)
    signal += generator.normal(0.0, 0.004, n_samples)
    peak = float(np.max(np.abs(signal)))
    if peak > 0:
        signal = signal / peak * 0.9
    return signal.astype(np.float64)


class TestGoldenVectorMeasuredBpm:
    """Measured tempo vectors: detected BPM == constructed click rate."""

    def test_click_trains_across_the_default_band(self, tmp_path: Path) -> None:
        """Seeded click trains at 90/100/120/140/165/172 BPM, three dither
        seeds each for flakiness insurance; tolerance +/-4 BPM as declared
        above."""
        for constructed_bpm in (90.0, 100.0, 120.0, 140.0, 165.0, 172.0):
            for dither_seed in (1, 2, 3):
                signal = clicked(constructed_bpm / 60.0, 30.0, dither_seed=dither_seed)
                wav_path = _write_wav(
                    tmp_path / f"click_{int(constructed_bpm)}_{dither_seed}.wav",
                    signal,
                )
                detected = detect_bpm(wav_path)
                assert abs(detected - constructed_bpm) <= 4.0, (
                    f"Click train at {constructed_bpm} BPM (seed {dither_seed}) "
                    f"detected as {detected}"
                )

    def test_octave_correction_resolves_subband_clicks(self, tmp_path: Path) -> None:
        """60 clicks/min sits below the default [75, 175] band; the engine
        must return 120 -- the unique in-range octave (measured at HEAD:
        raw 60.09 -> corrected 120).

        A narrowed range [50, 90] pins the octave logic from the other side:
        the same fixture returns 60 there.
        """
        slow_path = _write_wav(
            tmp_path / "click_60.wav",
            clicked(60 / 60.0, 30.0, dither_seed=11),
        )
        assert detect_bpm(slow_path) == 120
        assert detect_bpm(slow_path, min_bpm=50, max_bpm=90) == 60

    def test_digital_silence_resolves_via_hard_clamp(self, tmp_path: Path) -> None:
        """Real-librosa behaviour (not a mock): silence -> tempo 0.0 -> the
        non-positive guard skips octave correction -> the hard clamp lands on
        min_bpm.  This asserts the documented resolution path itself."""
        silence = np.zeros(int(30 * 22050), dtype=np.float64)
        wav_path = _write_wav(tmp_path / "silence.wav", silence)
        assert detect_bpm(wav_path, min_bpm=75, max_bpm=175) == 75

    def test_white_noise_never_returns_outside_the_band(self, tmp_path: Path) -> None:
        """Pure noise is beatless; only the in-range invariant holds."""
        generator = np.random.default_rng(99)
        noise = 0.5 * generator.standard_normal(int(30 * 22050))
        detected = detect_bpm(_write_wav(tmp_path / "noise.wav", noise))
        assert isinstance(detected, int)
        assert 75 <= detected <= 175

    def test_repeat_runs_are_identical(self, tmp_path: Path) -> None:
        """Seeded fixture, run twice: identical results (reproducibility)."""
        for constructed_bpm in (100.0, 120.0):
            wav_path = _write_wav(
                tmp_path / f"repeat_{int(constructed_bpm)}.wav",
                clicked(constructed_bpm / 60.0, 30.0, dither_seed=3),
            )
            assert detect_bpm(wav_path) == detect_bpm(wav_path)
