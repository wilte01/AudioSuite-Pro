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
"""

from __future__ import annotations

import wave
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
# Licensed real-music corpus (plan feature expansion D79)
# ═════════════════════════════════════════════════════════════════════════════
# The synthetic click trains above prove the tracker follows a constructed
# pulse; they cannot show that the periodicity gate accepts actual music.  The
# committed clips under tests/data/bpm_corpus are centre excerpts of seven CC0
# recordings (provenance, licence and transformation: the directory's
# ATTRIBUTION.md).  Each is annotated with its musical pulse; detection may
# report that pulse's octave because the metrical level is ambiguous, so the
# comparison accepts the annotated tempo or its double/half within the same
# +/-4 BPM band the golden vectors use.
#
# Calibration (2026-10-20): harmonic-comb scores on these clips were
# 0.154-0.595, the weakest being live_jazz_103; seeded white/pink/brown noise
# over 600 x 30 s windows never exceeded 0.080.  The assertions below lock the
# resulting margins, not the individual scores, so a librosa upgrade that
# shifts every value slightly does not turn the corpus red by itself -- but a
# change that lets noise through, or drags real music under the floor, does.

CORPUS_DIR = Path(__file__).resolve().parents[2] / "tests" / "data" / "bpm_corpus"

#: Committed clip -> annotated musical tempo (BPM).
_CORPUS_TEMPOS: dict[str, float] = {
    "brazilian_funk_130.ogg": 130.0,
    "hiphop_86.ogg": 86.0,
    "krautrock_152.ogg": 152.0,
    "lick_swing_120.ogg": 120.0,
    "live_jazz_103.ogg": 103.0,
    "samba_103.ogg": 103.0,
    "swing_152.ogg": 152.0,
}

#: Clips are excerpts, not masters: this ceiling keeps the corpus reviewable
#: in git instead of turning the repository into an audio archive.
_MAX_CLIP_BYTES = 200_000


def _corpus_scores() -> dict[str, float]:
    """Return the calibrated periodicity score of every committed clip."""
    import librosa

    scores: dict[str, float] = {}
    for name in _CORPUS_TEMPOS:
        y, sr = librosa.load(str(CORPUS_DIR / name), sr=22050, mono=True)
        envelope = librosa.onset.onset_strength(
            y=y, sr=sr, hop_length=_ONSET_HOP_LENGTH, aggregate=np.median
        )
        tempo, _ = librosa.beat.beat_track(
            onset_envelope=envelope, sr=sr, hop_length=_ONSET_HOP_LENGTH
        )
        scores[name] = _onset_periodicity(envelope, float(np.atleast_1d(tempo)[0]), sr)
    return scores


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


class TestRealMusicCorpus:
    """Real recordings are analysed, and the calibration margin survives."""

    @pytest.mark.parametrize(
        ("filename", "annotated_bpm"), sorted(_CORPUS_TEMPOS.items())
    )
    def test_real_music_is_analysed(self, filename: str, annotated_bpm: float) -> None:
        """Every clip decodes and returns a tempo at a musical metrical level."""
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

    def test_the_corpus_is_complete_and_attributed(self) -> None:
        """Files, sizes, durations and provenance are all accounted for."""
        import librosa

        files = sorted(path.name for path in CORPUS_DIR.glob("*.ogg"))
        assert files == sorted(_CORPUS_TEMPOS), (
            "the committed corpus and the annotated set diverged - add or "
            "remove the clip in both places"
        )
        attribution = (CORPUS_DIR / "ATTRIBUTION.md").read_text(encoding="utf-8")
        for name in files:
            path = CORPUS_DIR / name
            assert name in attribution, f"{name} has no provenance entry"
            assert path.stat().st_size <= _MAX_CLIP_BYTES, (
                f"{name} is {path.stat().st_size} bytes - corpus clips must "
                f"stay under {_MAX_CLIP_BYTES}"
            )
            duration = librosa.get_duration(path=str(path))
            assert 3.0 <= duration <= 20.5, f"{name}: unexpected duration {duration}"

    def test_the_calibration_margins_hold(self) -> None:
        """Music clears the floor by 1.2x; noise does not reach it.

        The 1.2x margin (0.12 at the current 0.10 floor) is the calibrated
        promise to real recordings, measured at 1.54x on the weakest clip.
        Noise is asserted against the floor itself: the 30 s calibration sweep
        (600 windows) peaked at 0.080, and these shorter 20 s windows at 0.090,
        so this test also covers the harsher end of the noise distribution.
        """
        scores = _corpus_scores()
        weakest = min(scores, key=lambda name: scores[name])
        assert scores[weakest] >= 1.2 * MIN_ONSET_PERIODICITY, (
            f"weakest real-music clip {weakest} scored {scores[weakest]:.3f}, "
            f"below 1.2x the {MIN_ONSET_PERIODICITY:.2f} floor: {scores}"
        )

        noise = _noise_scores()
        loudest = max(noise)
        assert loudest < MIN_ONSET_PERIODICITY, (
            f"seeded noise scored {loudest:.3f}, at or above the "
            f"{MIN_ONSET_PERIODICITY:.2f} floor"
        )
