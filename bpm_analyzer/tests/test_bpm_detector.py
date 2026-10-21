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
WAVs and asserts the measured BPM against the constructed click rate, and the
real-music corpus class, which decodes the committed CC0 recordings under
tests/data/bpm_corpus (provenance in its ATTRIBUTION.md).

Changed in 1.4.0: the failure contract is now a user-facing reason (the file
name is carried by the status line and the log record), with the decoder's own
exception preserved on __cause__.
Changed in 1.4.1: the real-music corpus's expectations are parsed from
ATTRIBUTION.md's ``## Clips`` table instead of a hardcoded dict, so a refused
recording is a declared row rather than an undocumented deletion (D99).
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import numpy as np
import numpy.typing as npt
import pytest

# Module under test
from bpm_analyzer.core.bpm_detector import (
    _ONSET_HOP_LENGTH,
    MIN_ONSET_PERIODICITY,
    BPMDetectionError,
    NoTempoDetectedError,
    _no_tempo_message,
    _onset_periodicity,
    detect_bpm,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_load_return(tempo_val: float, sr: int = 22050, n_samples: int = 22050 * 8):
    """Return a (y_float32, sr) pair that librosa.load would produce.

    The decode stand-in actually contains the tempo the tracker is mocked to
    report: the periodicity guard measures the onset envelope at *tempo_val*,
    so a mock that claims 120 BPM over a pure tone would (correctly) be
    refused.  Eight seconds give slow tempos enough periods for the
    autocorrelation.  Non-positive/non-finite estimates get an audible tone,
    which the no-tempo branch refuses before periodicity is computed.
    """
    if not np.isfinite(tempo_val) or tempo_val <= 0.0:
        t = np.arange(n_samples, dtype=np.float64) / sr
        return (0.5 * np.sin(2.0 * np.pi * 220.0 * t)).astype(np.float32), sr

    y = np.zeros(n_samples, dtype=np.float64)
    click_len = max(4, int(0.004 * sr))
    decay = np.exp(-np.linspace(0.0, 8.0, click_len))
    carrier = np.sin(2.0 * np.pi * 1000.0 * np.arange(click_len) / sr)
    envelope = carrier * decay
    period = sr * 60.0 / tempo_val
    position = 0.0
    while position < n_samples:
        start = int(position)
        end = min(start + click_len, n_samples)
        y[start:end] += envelope[: end - start]
        position += period
    peak = float(np.max(np.abs(y)))
    if peak > 0.0:
        y = 0.9 * y / peak
    return y.astype(np.float32), sr


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
        before DSP work.  We capture the array passed to onset extraction (the
        first DSP consumer) and inspect its dtype.
        """
        captured: list = []

        def fake_onset_strength(y, sr, **kwargs):
            captured.append(y.dtype)
            envelope = np.zeros(400, dtype=np.float64)
            envelope[::22] = 1.0
            return envelope

        with (
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.load",
                return_value=_make_load_return(120.0),
            ),
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.onset.onset_strength",
                side_effect=fake_onset_strength,
            ),
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
                return_value=(np.array([120.0]), None),
            ),
        ):
            detect_bpm("fake.mp3")

        assert len(captured) == 1
        assert captured[0] == np.float64, (
            f"Expected float64 passed to onset extraction, got {captured[0]}"
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


class TestSilentAudio:
    """A silent decode is a reported failure, not the clamp floor.

    Silence is refused before the tracker now; before the shared guard it
    reached beat tracking, which returns tempo 0.0 for a flat signal, and the
    old clamp turned that into min_bpm — a fabricated value the tool tagged.
    """

    def test_silent_decode_is_reported_not_beaten_tracked(self):
        silent = np.zeros(22050, dtype=np.float32)
        with (
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.load",
                return_value=(silent, 22050),
            ),
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track"
            ) as beat_track,
        ):
            with pytest.raises(BPMDetectionError) as exc_info:
                detect_bpm("silence.wav", min_bpm=75, max_bpm=175)

        assert "silent" in str(exc_info.value).lower()
        beat_track.assert_not_called()

    def test_a_quiet_but_audible_signal_is_still_analysed(self):
        """The guard rejects silence, not quiet music: -40 dBFS is analysed."""
        quiet, _ = _make_load_return(120.0)
        # The click train's RMS is far below its peak, so 0.2 keeps it around
        # -45 dBFS: quiet, but comfortably above the -60 dBFS silence guard.
        quiet = (quiet * 0.2).astype(np.float32)
        with (
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.load",
                return_value=(quiet, 22050),
            ),
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
                return_value=(np.array([120.0]), None),
            ),
        ):
            assert detect_bpm("quiet.mp3") == 120


class TestEmptyAudioBuffer:
    """An empty decode is a reported failure, not a fabricated BPM.

    These tests previously asserted the clamp floor (75 / 110) for an empty
    buffer. A zero-length signal cannot carry a tempo, so returning a number —
    which the tool then wrote as the file's BPM tag — was the defect: the
    shared too-short guard now reports it instead.
    """

    def test_zero_length_buffer_is_reported_as_too_short(self):
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            return_value=(np.zeros(0, dtype=np.float32), 22050),
        ):
            with patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track"
            ) as beat_track:
                with pytest.raises(BPMDetectionError) as exc_info:
                    detect_bpm("empty.wav", min_bpm=75, max_bpm=175)

        assert "too short" in str(exc_info.value).lower()
        beat_track.assert_not_called()

    def test_non_positive_rate_is_reported_not_divided_by_zero(self):
        """A corrupt container can decode to ``sr == 0``; the guard says so."""
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            return_value=(np.zeros(0, dtype=np.float32), 0),
        ):
            with pytest.raises(BPMDetectionError) as exc_info:
                detect_bpm("empty.wav", min_bpm=110, max_bpm=120)

        assert "too short" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# 6. Error handling — BPMDetectionError raised on failures
# ---------------------------------------------------------------------------


class TestErrorHandling:
    def test_raises_on_file_not_found(self):
        """The message is the user-facing reason, not the raw decoder text.

        The file name reaches the user through the per-file status line (and
        through the log record), so the exception carries the one sentence a
        dialog needs; the original error stays on ``__cause__``.
        """
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            side_effect=FileNotFoundError("no such file"),
        ):
            with pytest.raises(BPMDetectionError) as exc_info:
                detect_bpm("nonexistent.mp3")
        assert "could not be found" in str(exc_info.value).lower()
        assert isinstance(exc_info.value.__cause__, FileNotFoundError)

    def test_raises_on_librosa_runtime_error(self):
        with patch(
            "bpm_analyzer.core.bpm_detector.librosa.load",
            side_effect=RuntimeError("librosa internal failure"),
        ):
            with pytest.raises(BPMDetectionError):
                detect_bpm("corrupt.mp3")

    def test_short_audio_is_reported_not_beaten_tracked(self):
        """A 0.2 s decode must not be tagged with the clamp floor.

        Regression: BPM detection decodes through the fallback helper
        directly, bypassing the shared loader's too-short guard, so a blip was
        beat-tracked and reported as BPM 60 (the lower clamp bound) — a
        fabricated value the tool would write to the file.
        """
        short = np.zeros(int(0.2 * 22050), dtype=np.float32)
        with (
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.load",
                return_value=(short, 22050),
            ),
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track"
            ) as beat_track,
        ):
            with pytest.raises(BPMDetectionError) as exc_info:
                detect_bpm("blip.mp3")

        assert "too short" in str(exc_info.value).lower()
        beat_track.assert_not_called()

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
# 7. Regression: non-positive tempo is an absence of a beat, not a floor
#
# Bug: librosa.beat.beat_track() returns 0.0 for beatless material (a
# sustained tone or a pad, confirmed against the real implementation, not a
# mock). It used to be clamped to min_bpm and tagged; earlier still, an
# unconditional octave-correction loop would not terminate for tempo <= 0
# because doubling zero stays zero. The branch now raises instead, and the
# timeout below stays as a guard for the loop on positive estimates.
# ---------------------------------------------------------------------------


class TestNoTempoRegression:
    """A non-positive tempo estimate is an absence of a beat, not a floor.

    Regression: zero (librosa's output for a sustained tone or a pad) and
    negative values were clamped to ``min_bpm``, so the tool tagged a real-
    looking BPM that nothing in the audio supported.
    """

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

    def test_zero_tempo_reports_no_tempo(self):
        """tempo == 0.0 (real librosa output for a sustained tone) is refused."""
        load_p, beat_p = _patch_librosa(0.0)
        with load_p, beat_p:
            with pytest.raises(NoTempoDetectedError) as exc_info:
                self._detect_with_timeout("tone.wav", min_bpm=75, max_bpm=175)
        assert "no tempo detected" in str(exc_info.value).lower()
        assert exc_info.value.context["tempo_estimate"] == 0.0
        # No periodicity was measured, so the sentence must not imply one.
        assert "onset periodicity" not in str(exc_info.value)

    def test_zero_tempo_ignores_the_configured_range(self):
        """The refusal is about the audio, not about the clamp bounds, so a
        narrow custom range must not turn it back into a number."""
        load_p, beat_p = _patch_librosa(0.0)
        with load_p, beat_p:
            with pytest.raises(NoTempoDetectedError):
                self._detect_with_timeout("tone.wav", min_bpm=110, max_bpm=120)

    def test_negative_tempo_reports_no_tempo(self):
        """Defensive case: a negative estimate is also an absence of a beat."""
        load_p, beat_p = _patch_librosa(-5.0)
        with load_p, beat_p:
            with pytest.raises(NoTempoDetectedError):
                self._detect_with_timeout("fake.mp3", min_bpm=75, max_bpm=175)

    def test_non_finite_tempo_reports_no_tempo(self):
        """NaN/inf from the tracker must not survive the clamp as a number."""
        for estimate in (float("nan"), float("inf")):
            load_p, beat_p = _patch_librosa(estimate)
            with load_p, beat_p:
                with pytest.raises(NoTempoDetectedError):
                    self._detect_with_timeout("fake.mp3", min_bpm=75, max_bpm=175)

    def test_a_flat_onset_envelope_reports_no_tempo(self):
        """A positive estimate fitted to a flat envelope is spurious."""
        with (
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.load",
                return_value=_make_load_return(120.0),
            ),
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.onset.onset_strength",
                return_value=np.zeros(200, dtype=np.float64),
            ),
            patch(
                "bpm_analyzer.core.bpm_detector.librosa.beat.beat_track",
                return_value=(np.array([120.0]), None),
            ),
        ):
            with pytest.raises(NoTempoDetectedError) as exc_info:
                detect_bpm("noise.wav", min_bpm=75, max_bpm=175)
        assert exc_info.value.context["onset_periodicity"] == 0.0
        assert "onset periodicity 0.00" in str(exc_info.value)
        assert f"minimum {MIN_ONSET_PERIODICITY:.2f}" in str(exc_info.value)


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


class TestNoTempoMessage:
    """The skip sentence: auditable when measured, plain when not."""

    def test_unmeasured_periodicity_has_no_score(self) -> None:
        assert _no_tempo_message() == (
            "No tempo detected — the audio has no discernible beat."
        )

    def test_measured_score_and_minimum_are_rendered(self) -> None:
        assert _no_tempo_message(0.043) == (
            "No tempo detected — the audio has no discernible beat "
            f"(onset periodicity 0.04, minimum {MIN_ONSET_PERIODICITY:.2f})."
        )


class TestOnsetPeriodicity:
    """The confidence measure itself: noise at the floor, music clear of it."""

    @staticmethod
    def _envelope(y: np.ndarray, sr: int = 22050) -> np.ndarray:
        import librosa

        return librosa.onset.onset_strength(
            y=y, sr=sr, hop_length=512, aggregate=np.median
        )

    def test_a_clean_click_train_scores_far_above_the_threshold(self) -> None:
        y, _ = _make_load_return(120.0)
        score = _onset_periodicity(self._envelope(y), 120.0, 22050)
        assert score >= 0.5, score

    def test_music_over_a_noisy_floor_still_clears_the_threshold(self) -> None:
        """A beat mixed with broadband noise keeps its periodicity."""
        generator = np.random.default_rng(11)
        beat = clicked(2.0, 30.0, dither_seed=5)
        noisy = 0.7 * beat + 0.15 * generator.standard_normal(len(beat))
        score = _onset_periodicity(self._envelope(noisy), 120.0, 22050)
        assert score >= MIN_ONSET_PERIODICITY, score

    def test_white_noise_scores_below_the_threshold(self) -> None:
        generator = np.random.default_rng(99)
        noise = 0.5 * generator.standard_normal(30 * 22050)
        score = _onset_periodicity(self._envelope(noise), 120.0, 22050)
        assert score < MIN_ONSET_PERIODICITY, score

    def test_a_flat_envelope_scores_zero(self) -> None:
        flat = np.zeros(400, dtype=np.float64)
        assert _onset_periodicity(flat, 120.0, 22050) == 0.0

    def test_non_positive_tempo_scores_zero(self) -> None:
        envelope = np.zeros(400, dtype=np.float64)
        envelope[::22] = 1.0
        assert _onset_periodicity(envelope, 0.0, 22050) == 0.0


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

    def test_digital_silence_is_refused_not_clamped(self, tmp_path: Path) -> None:
        """Real-librosa behaviour (not a mock): a silent file has no tempo.

        Regression: this test previously asserted the hard clamp's floor (BPM
        75) for 30 s of digital silence -- real-librosa beat tracking reports
        tempo 0.0, the non-positive guard skipped octave correction, and the
        clamp turned that into a number the tool wrote to the file.  The
        shared guard now refuses the decode instead.
        """
        silence = np.zeros(int(30 * 22050), dtype=np.float64)
        wav_path = _write_wav(tmp_path / "silence.wav", silence)
        with pytest.raises(BPMDetectionError) as exc_info:
            detect_bpm(wav_path, min_bpm=75, max_bpm=175)
        assert "silent" in str(exc_info.value).lower()
        assert "nothing to analyse" in str(exc_info.value).lower()

    def test_a_sustained_tone_reports_no_tempo(self, tmp_path: Path) -> None:
        """Real-librosa behaviour (not a mock): a 10 s pure tone is beatless.

        Beat tracking returns tempo 0.0, which used to be clamped to the floor
        and tagged.  The file is audible and longer than the duration guard, so
        only the no-tempo branch can refuse it.
        """
        t = np.arange(10 * 22050) / 22050.0
        tone = 0.4 * np.sin(2 * np.pi * 440.0 * t)
        wav_path = _write_wav(tmp_path / "tone.wav", tone)
        with pytest.raises(NoTempoDetectedError) as exc_info:
            detect_bpm(wav_path, min_bpm=75, max_bpm=175)
        assert "no tempo detected" in str(exc_info.value).lower()

    def test_a_pad_with_no_transients_reports_no_tempo(self, tmp_path: Path) -> None:
        """A slow chord swell has onset energy but no beat periodicity."""
        t = np.arange(10 * 22050) / 22050.0
        chord = sum(np.sin(2 * np.pi * f * t) for f in (220.0, 277.18, 329.63))
        pad = 0.2 * chord * (1.0 + 0.3 * np.sin(2 * np.pi * 0.15 * t))
        wav_path = _write_wav(tmp_path / "pad.wav", pad)
        with pytest.raises(NoTempoDetectedError):
            detect_bpm(wav_path, min_bpm=75, max_bpm=175)

    def test_white_noise_reports_no_tempo(self, tmp_path: Path) -> None:
        """Seeded white noise has a spurious tracker estimate but no period.

        Regression: random onsets were fitted to a tempo grid and returned as
        a measurement.  The onset autocorrelation at that tempo is at the
        noise floor, so the file is now refused.
        """
        generator = np.random.default_rng(99)
        noise = 0.5 * generator.standard_normal(int(30 * 22050))
        wav_path = _write_wav(tmp_path / "noise.wav", noise)
        with pytest.raises(NoTempoDetectedError) as exc_info:
            detect_bpm(wav_path, min_bpm=75, max_bpm=175)
        message = str(exc_info.value)
        assert "no tempo detected" in message.lower()
        # The score that justified the skip is in the sentence the log shows.
        assert "onset periodicity" in message
        assert f"minimum {MIN_ONSET_PERIODICITY:.2f}" in message
        assert exc_info.value.context["onset_periodicity"] < MIN_ONSET_PERIODICITY

    def test_noise_with_an_embedded_click_train_is_still_measured(
        self, tmp_path: Path
    ) -> None:
        """The guard rejects noise, not music playing over a noisy floor."""
        generator = np.random.default_rng(7)
        beat = clicked(120.0 / 60.0, 30.0, dither_seed=5)
        noise = 0.15 * generator.standard_normal(len(beat))
        wav_path = _write_wav(tmp_path / "noisy.wav", 0.7 * beat + noise)
        detected = detect_bpm(wav_path, min_bpm=75, max_bpm=175)
        assert abs(detected - 120) <= 4

    def test_repeat_runs_are_identical(self, tmp_path: Path) -> None:
        """Seeded fixture, run twice: identical results (reproducibility)."""
        for constructed_bpm in (100.0, 120.0):
            wav_path = _write_wav(
                tmp_path / f"repeat_{int(constructed_bpm)}.wav",
                clicked(constructed_bpm / 60.0, 30.0, dither_seed=3),
            )
            assert detect_bpm(wav_path) == detect_bpm(wav_path)


# ═════════════════════════════════════════════════════════════════════════════
# Licensed real-music corpus (plan feature expansion D79, D99)
# ═════════════════════════════════════════════════════════════════════════════
# The synthetic click trains above prove the tracker follows a constructed
# pulse; they cannot show that the periodicity gate accepts actual music.  The
# committed clips under tests/data/bpm_corpus are short excerpts of CC0
# recordings (provenance, licence and transformation: the directory's
# ATTRIBUTION.md).  D99 makes that file's ``## Clips`` table the source of
# truth: it is parsed here, so a clip cannot exist without provenance and an
# annotated pulse, and a recording the gate refuses keeps its place as a
# ``refused`` row instead of being quietly deleted.  Each row's annotated
# pulse is the musical tempo; detection may report that pulse's octave because
# the metrical level is ambiguous, so the comparison accepts the annotated
# tempo or its double/half within the same +/-4 BPM band the golden vectors
# use.

CORPUS_DIR = Path(__file__).resolve().parents[2] / "tests" / "data" / "bpm_corpus"
ATTRIBUTION_PATH = CORPUS_DIR / "ATTRIBUTION.md"

#: The table cell that declares a recording the gate must not report a tempo for.
_REFUSED = "refused"

#: Clips are excerpts, not masters: this ceiling keeps the corpus reviewable
#: in git instead of turning the repository into an audio archive.
_MAX_CLIP_BYTES = 200_000

#: The calibrated promise to real recordings: music clears the floor by 1.2x.
_MUSIC_MARGIN = 1.2

#: The floor the promise is expressed against.  Pinned by
#: :meth:`TestRealMusicCorpus.test_the_calibration_constants_are_pinned`, which
#: fails if either number is edited to make a red corpus green.
_CALIBRATED_FLOOR = 0.10

#: The hardest clip in the corpus must sit inside this multiple of the floor,
#: or the corpus no longer contains evidence near the boundary (P4).
_HARD_CLIP_LIMIT = 1.6

#: How far a table's recorded score may drift from the measurement before the
#: row is stale.  Loose enough for a librosa upgrade, tight enough that
#: re-encoding a clip or replacing its source fails the suite.
_SCORE_TOLERANCE = 0.05


@dataclass(frozen=True)
class CorpusRow:
    """One row of the ``## Clips`` table: a clip and its recorded expectation.

    Attributes:
        filename: The committed ``.ogg`` in :data:`CORPUS_DIR`.
        annotated_bpm: The musical pulse, or ``None`` for a ``refused`` row.
        offset: Where the excerpt starts in the source, as written in the table.
        length: The excerpt's length, as written in the table.
        source: The Commons file page the excerpt came from.
        author: The credited author.
        licence: The licence short name; the suite requires CC0 1.0.
        recorded_score: The comb score at the estimated tempo, or ``None`` when
            the estimate was non-positive and no score exists.
        detected_bpm: What ``detect_bpm`` reports, as written in the table.
    """

    filename: str
    annotated_bpm: float | None
    offset: str
    length: str
    source: str
    author: str
    licence: str
    recorded_score: float | None
    detected_bpm: str


def _pipe_rows(markdown: str, heading: str) -> list[dict[str, str]]:
    """Return the first pipe table under *heading*, keyed by its header cells.

    Args:
        markdown: The ATTRIBUTION.md text.
        heading: The heading line the table sits under, e.g. ``"## Clips"``.

    Returns:
        One dict per data row, mapping header cell to cell text.  The
        ``|---|---|`` separator is skipped.

    Raises:
        AssertionError: If the heading or a table under it is missing, or a row
            does not have the header's column count - a malformed table must
            fail loudly rather than parse into a shorter corpus.
    """
    lines = markdown.splitlines()
    assert heading in lines, (
        f"{heading!r} heading missing from {ATTRIBUTION_PATH.name} - the table "
        "is the suite's source of truth"
    )
    start = lines.index(heading)
    table: list[list[str]] = []
    for line in lines[start + 1 :]:
        if line.startswith("|"):
            table.append([cell.strip() for cell in line.strip().strip("|").split("|")])
        elif table:
            break
    assert len(table) >= 2, f"no pipe table under {heading!r}"

    header = table[0]
    rows: list[dict[str, str]] = []
    for row in table[1:]:
        if all(cell and set(cell) <= set("-: ") for cell in row):
            continue
        assert len(row) == len(header), (
            f"malformed row under {heading!r}: {len(row)} cells for "
            f"{len(header)} columns: {row}"
        )
        rows.append(dict(zip(header, row, strict=True)))
    return rows


def _corpus_rows() -> list[CorpusRow]:
    """Parse the corpus table into rows.

    Returns:
        Every declared clip, in table order.

    Raises:
        AssertionError: If the table is empty, a filename repeats, or a pulse
            cell is neither ``refused`` nor a number followed by ``BPM``.
    """
    rows = _pipe_rows(ATTRIBUTION_PATH.read_text(encoding="utf-8"), "## Clips")
    assert rows, "the corpus table is empty - the scan would pass vacuously"

    parsed: list[CorpusRow] = []
    for row in rows:
        pulse = row["Annotated pulse"]
        refused = pulse.casefold() == _REFUSED
        score = row["Measured score"]
        parsed.append(
            CorpusRow(
                filename=row["Clip"].strip("`"),
                annotated_bpm=None if refused else float(pulse.split()[0]),
                offset=row["Offset"],
                length=row["Length"],
                source=row["Source"].strip("<>"),
                author=row["Author"],
                licence=row["Licence"],
                recorded_score=None if score == "-" else float(score),
                detected_bpm=row["Detected BPM"],
            )
        )

    names = [row.filename for row in parsed]
    assert len(names) == len(set(names)), (
        f"the corpus table names a clip twice: {sorted(names)}"
    )
    return parsed


_CORPUS_ROWS = _corpus_rows()
_ACCEPTED_ROWS = [row for row in _CORPUS_ROWS if row.annotated_bpm is not None]
_REFUSED_ROWS = [row for row in _CORPUS_ROWS if row.annotated_bpm is None]


def _score_clip(path: Path) -> float | None:
    """Return a clip's harmonic-comb score, or ``None`` without a positive estimate.

    Args:
        path: A committed corpus clip.

    Returns:
        The periodicity at the tempo ``beat_track`` estimates, or ``None`` when
        that estimate is not positive - the zero-tempo branch computes no
        score at all.
    """
    import librosa

    y, sr = librosa.load(str(path), sr=22050, mono=True)
    envelope = librosa.onset.onset_strength(
        y=y, sr=sr, hop_length=_ONSET_HOP_LENGTH, aggregate=np.median
    )
    tempo, _ = librosa.beat.beat_track(
        onset_envelope=envelope, sr=sr, hop_length=_ONSET_HOP_LENGTH
    )
    tempo_value = float(np.atleast_1d(tempo)[0])
    if tempo_value <= 0:
        return None
    return _onset_periodicity(envelope, tempo_value, sr)


def _noise_scores(seconds: int = 20, seeds: int = 10) -> list[float]:
    """Score seeded white, pink and brown noise with the same pipeline."""
    import librosa

    scores: list[float] = []
    for color in ("white", "pink", "brown"):
        for seed in range(seeds):
            rng = np.random.default_rng(seed)
            n = 22050 * seconds
            signal = rng.standard_normal(n)
            if color == "pink":
                freq = np.fft.rfftfreq(n, 1 / 22050)
                freq[0] = 1.0
                signal = np.fft.irfft(np.fft.rfft(signal) / np.sqrt(freq), n)
            elif color == "brown":
                signal = np.cumsum(rng.standard_normal(n))
                signal -= np.linspace(signal[0], signal[-1], n)
            signal = signal / np.max(np.abs(signal)) * 0.5
            envelope = librosa.onset.onset_strength(
                y=signal, sr=22050, hop_length=_ONSET_HOP_LENGTH, aggregate=np.median
            )
            tempo, _ = librosa.beat.beat_track(
                onset_envelope=envelope, sr=22050, hop_length=_ONSET_HOP_LENGTH
            )
            scores.append(
                _onset_periodicity(envelope, float(np.atleast_1d(tempo)[0]), 22050)
            )
    return scores


class TestCorpusTableParsing:
    """The corpus table parser fails loudly instead of silently shrinking.

    D99 moved the expectations out of a Python dict and into prose, so the
    parser is now the gate's own input: a table it mis-reads would certify a
    smaller corpus. These cases prove it cannot swallow a malformed row or a
    missing table, and that the committed table really parses.
    """

    def test_a_malformed_row_is_rejected(self) -> None:
        """A row with fewer cells than the header is an error, not a short row."""
        markdown = (
            "## Clips\n"
            "| Clip | Annotated pulse |\n"
            "|------|-----------------|\n"
            "| `a.ogg` | 120 BPM |\n"
            "| `b.ogg` |\n"
        )
        with pytest.raises(AssertionError, match="malformed row"):
            _pipe_rows(markdown, "## Clips")

    def test_a_missing_heading_is_rejected(self) -> None:
        """Without the heading there is no table, which must not read as empty."""
        with pytest.raises(AssertionError, match="heading missing"):
            _pipe_rows("| Clip |\n|--|\n| `a.ogg` |\n", "## Clips")

    def test_the_committed_table_parses(self) -> None:
        """The real table yields accepted and refused rows, so neither set is empty."""
        assert len(_CORPUS_ROWS) >= 8, f"only {len(_CORPUS_ROWS)} rows parsed"
        assert _ACCEPTED_ROWS, "no accepted row - the tempo assertions are vacuous"
        assert _REFUSED_ROWS, "no refused row - the refusal path is untested"


class TestRealMusicCorpus:
    """Real recordings are analysed, and the calibration margin survives."""

    @pytest.mark.parametrize(
        ("filename", "annotated_bpm"),
        [(row.filename, row.annotated_bpm) for row in _ACCEPTED_ROWS],
        ids=[row.filename for row in _ACCEPTED_ROWS],
    )
    def test_real_music_is_analysed(self, filename: str, annotated_bpm: float) -> None:
        """Every accepted clip decodes and returns a tempo at a musical level."""
        detected = detect_bpm(str(CORPUS_DIR / filename))
        matches = [
            factor
            for factor in (1.0, 2.0, 0.5)
            if abs(detected - annotated_bpm * factor) <= 4.0
        ]
        assert matches, (
            f"{filename}: detected {detected} BPM, annotated {annotated_bpm} "
            "(octave-tolerant +/-4 BPM)"
        )

    @pytest.mark.parametrize(
        "filename",
        [row.filename for row in _ACCEPTED_ROWS],
        ids=[row.filename for row in _ACCEPTED_ROWS],
    )
    def test_the_recorded_detected_bpm_is_current(self, filename: str) -> None:
        """The table's ``Detected BPM`` cell describes what the tool reports now.

        The annotation test above accepts the annotated tempo at any octave, so
        it cannot notice that the *reported* number moved - only that some
        musical level still matches.  That is how a range policy change hides:
        `ambient_pulse_60.ogg` is annotated 60 and reported **120**, because 60
        is below `detect_bpm`'s 75 BPM floor and the tool doubles it.  A change
        to that floor would still pass the octave-tolerant test while every user
        of the tool saw a different number for the same file, so the recorded
        cell is checked against the live return value and a move fails here for
        re-annotation rather than silently invalidating the column.
        """
        row = next(row for row in _ACCEPTED_ROWS if row.filename == filename)
        detected = detect_bpm(str(CORPUS_DIR / filename))
        assert abs(detected - float(row.detected_bpm)) <= 1.0, (
            f"{filename}: table records {row.detected_bpm} BPM but the tool now "
            f"reports {detected} - re-measure the row (the octave rule would "
            "still accept it, which is why this column needs its own lock)"
        )

    @pytest.mark.parametrize(
        "filename",
        [row.filename for row in _REFUSED_ROWS],
        ids=[row.filename for row in _REFUSED_ROWS],
    )
    def test_refused_recordings_are_refused(self, filename: str) -> None:
        """A ``refused`` row is a decision the gate still makes.

        The row records either a score below the floor (the periodicity gate
        declined a pulse it measured) or ``-`` (no positive estimate existed,
        so no score was computed).  Both must still raise, and a measured
        score must agree with the row - otherwise the refusal moved and the
        table is stale.
        """
        row = next(row for row in _REFUSED_ROWS if row.filename == filename)
        with pytest.raises(NoTempoDetectedError):
            detect_bpm(str(CORPUS_DIR / filename))

        if row.recorded_score is not None:
            assert row.recorded_score < MIN_ONSET_PERIODICITY, (
                f"{filename}: the table records {row.recorded_score:.3f}, at or "
                f"above the {MIN_ONSET_PERIODICITY:.2f} floor - a refused row "
                "must record why the gate declined it"
            )
        measured = _score_clip(CORPUS_DIR / filename)
        if row.recorded_score is None:
            assert measured is None, (
                f"{filename}: the table records no score but the tracker now "
                f"estimates one ({measured:.3f}) - re-annotate the row"
            )
        else:
            assert measured is not None, f"{filename}: the table records a score"
            assert abs(measured - row.recorded_score) <= _SCORE_TOLERANCE, (
                f"{filename}: table records {row.recorded_score:.3f}, measured "
                f"{measured:.3f}"
            )

    def test_the_corpus_is_complete_and_attributed(self) -> None:
        """The directory, the table and the provenance agree, and nothing is huge."""
        import librosa

        assert _CORPUS_ROWS, "the corpus table parsed to nothing"
        files = sorted(path.name for path in CORPUS_DIR.glob("*.ogg"))
        assert files == sorted(row.filename for row in _CORPUS_ROWS), (
            "the committed corpus and the table diverged - a clip is missing "
            "its row or a row is missing its clip"
        )

        attribution = ATTRIBUTION_PATH.read_text(encoding="utf-8")
        for row in _CORPUS_ROWS:
            path = CORPUS_DIR / row.filename
            assert row.filename in attribution, f"{row.filename} has no row"
            assert row.licence == "CC0 1.0", (
                f"{row.filename}: licence {row.licence!r} is not the verified "
                "CC0 dedication the corpus requires"
            )
            assert row.source.startswith("https://commons.wikimedia.org/wiki/File:"), (
                f"{row.filename}: '{row.source}' is not a Commons file page"
            )
            assert path.stat().st_size <= _MAX_CLIP_BYTES, (
                f"{row.filename} is {path.stat().st_size} bytes - corpus clips "
                f"must stay under {_MAX_CLIP_BYTES}"
            )
            duration = librosa.get_duration(path=str(path))
            assert 3.0 <= duration <= 20.5, (
                f"{row.filename}: unexpected duration {duration}"
            )

    def test_the_calibration_margins_hold(self) -> None:
        """Music clears the floor by 1.2x, noise does not, and rows are current.

        The 1.2x margin (0.12 at the current 0.10 floor) is the calibrated
        promise to real recordings.  Since D99 the binding clip is the rubato
        nocturne at 0.124, 1.24x - rubato playing straddles the floor, which is
        the tightest real-music evidence in the corpus.  Noise is asserted
        against the floor itself: the 30 s calibration sweep (600 windows)
        peaked at 0.080, and these shorter 20 s windows at 0.090, so this test
        also covers the harsher end of the noise distribution.
        """
        measured: dict[str, float] = {}
        for row in _CORPUS_ROWS:
            score = _score_clip(CORPUS_DIR / row.filename)
            if score is not None:
                measured[row.filename] = score

        accepted = {
            row.filename: measured[row.filename]
            for row in _ACCEPTED_ROWS
            if row.filename in measured
        }
        assert accepted, "no accepted clip produced a score - the scan is vacuous"
        weakest = min(accepted, key=lambda name: accepted[name])
        assert accepted[weakest] >= _MUSIC_MARGIN * MIN_ONSET_PERIODICITY, (
            f"weakest real-music clip {weakest} scored {accepted[weakest]:.3f}, "
            f"below {_MUSIC_MARGIN}x the {MIN_ONSET_PERIODICITY:.2f} floor: "
            f"{accepted}"
        )

        for row in _CORPUS_ROWS:
            if row.recorded_score is None:
                continue
            assert row.filename in measured, (
                f"{row.filename}: the table records a score the pipeline did "
                "not compute - re-annotate the row"
            )
            assert abs(measured[row.filename] - row.recorded_score) <= (
                _SCORE_TOLERANCE
            ), (
                f"{row.filename}: table records {row.recorded_score:.3f}, "
                f"measured {measured[row.filename]:.3f}"
            )

        noise = _noise_scores()
        loudest = max(noise)
        assert loudest < MIN_ONSET_PERIODICITY, (
            f"seeded noise scored {loudest:.3f}, at or above the "
            f"{MIN_ONSET_PERIODICITY:.2f} floor"
        )

    def test_the_calibration_constants_are_pinned(self) -> None:
        """The floor and the promise are calibrated numbers, not knobs (P4).

        The 1.2x promise has 0.024 of absolute headroom on its weakest clip, so
        the tempting fix when a librosa upgrade shifts scores down is to lower
        one of these two numbers until the suite is green again — which would
        quietly accept the fabricated tempos the gate exists to reject.  The
        recorded rule is to re-derive both from a re-measured corpus instead
        (PLAN_feature_expansion P4), and this test is what makes that rule
        hold: changing either constant fails here, with the reason attached.
        """
        assert MIN_ONSET_PERIODICITY == _CALIBRATED_FLOOR, (
            f"MIN_ONSET_PERIODICITY is {MIN_ONSET_PERIODICITY}, not the "
            f"calibrated {_CALIBRATED_FLOOR}. If the corpus went red, re-derive "
            "the floor from a re-measured corpus (D79's method: seeded noise vs "
            "the committed clips) and record the new calibration; do not lower "
            "it to make this suite pass"
        )
        assert _MUSIC_MARGIN == 1.2, (
            f"the real-music promise is {_MUSIC_MARGIN}x, not the calibrated "
            "1.2x; loosening the promise is the same edit as lowering the "
            "floor and hides the same regression"
        )

    def test_the_corpus_keeps_a_clip_near_the_boundary(self) -> None:
        """At least one accepted clip is hard, or the margin proves nothing (P4).

        If the rubato recording were dropped, the weakest remaining clip is
        0.154 (1.54x) and the 1.2x promise would still pass while no longer
        corresponding to anything in the corpus: the suite would look green and
        stop being evidence.  Keeping a clip inside 1.6x of the floor means the
        promise is tested against music that is genuinely near the gate.
        """
        measured = {
            row.filename: score
            for row in _ACCEPTED_ROWS
            if (score := _score_clip(CORPUS_DIR / row.filename)) is not None
        }
        assert measured, "no accepted clip produced a score - the scan is vacuous"

        hard = {
            name: score
            for name, score in measured.items()
            if score <= _HARD_CLIP_LIMIT * MIN_ONSET_PERIODICITY
        }
        assert hard, (
            "every accepted clip clears the floor by more than "
            f"{_HARD_CLIP_LIMIT}x (scores: {measured}); the corpus no longer "
            "contains a recording near the gate, so the 1.2x promise is no "
            "longer tested by it"
        )
