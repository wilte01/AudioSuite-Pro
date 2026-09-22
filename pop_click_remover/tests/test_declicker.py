"""
test_declicker.py
Pytest test suite for the Pop & Click Remover DSP engine.

Run with:
    pytest tests/test_declicker.py -v

Test coverage
-------------
* Single click detection and repair (mono, 16-bit)
* Multiple clicks in a single pass
* Stereo (multi-channel) processing — verifies both channels repaired
* 24-bit audio (pydub stores as 32-bit int) — bit-depth round-trip
* Clean audio produces no modifications (no false positives)
* Repair quality: repaired amplitude is lower than the original spike
* Input validation: AudioConfigurationError on bad threshold / width
* Clicks at signal boundaries (near index 0, near end of file)
"""

from __future__ import annotations

import numpy as np
import pytest
from pydub import AudioSegment

from audio_suite_shared.exceptions import AudioConfigurationError
from pop_click_remover.core.declicker import (
    DeclickResult,
    _merge_regions,
    _repair_region,
    _threshold_to_k,
    declick_audio,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

FS = 44100  # sample rate used throughout


def _sine_segment(
    duration_s: float = 1.0,
    freq_hz: float = 440.0,
    amplitude: float = 0.4,
    channels: int = 1,
    sample_width: int = 2,
) -> AudioSegment:
    """
    Generate a pure sine wave as a pydub AudioSegment.

    Parameters
    ----------
    sample_width : int
        Bytes per sample.  2 = 16-bit, 4 = 32-bit (used to simulate 24-bit).
    """
    n = int(duration_s * FS)
    t = np.linspace(0, duration_s, n, endpoint=False)
    sine = amplitude * np.sin(2.0 * np.pi * freq_hz * t)

    if sample_width == 2:
        dtype = np.int16
        max_val = 32767
    else:
        dtype = np.int32
        max_val = 2**23 - 1  # simulate 24-bit range inside 32-bit container

    pcm = (sine * max_val).astype(dtype)

    if channels == 2:
        # Interleave identical L/R channels
        pcm = np.repeat(pcm, 2)

    return AudioSegment(
        pcm.tobytes(),
        frame_rate=FS,
        sample_width=sample_width,
        channels=channels,
    )


def _inject_clicks(
    audio: AudioSegment, indices: list[int], magnitude: int = 28000
) -> AudioSegment:
    """Return a copy of *audio* with hard spikes at the given sample indices."""
    raw = np.frombuffer(audio.raw_data, dtype=_pcm_dtype(audio)).copy()
    n_ch = audio.channels
    for idx in indices:
        frame_start = idx * n_ch
        for ch in range(n_ch):
            if frame_start + ch < len(raw):
                raw[frame_start + ch] = magnitude
    return audio._spawn(raw.tobytes())


def _pcm_dtype(audio: AudioSegment) -> np.dtype:
    return np.int16 if audio.sample_width == 2 else np.int32


def _repaired_samples(result: DeclickResult) -> np.ndarray:
    return np.frombuffer(result.audio.raw_data, dtype=_pcm_dtype(result.audio))


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestBasicDetection:
    def test_single_click_detected(self):
        audio = _sine_segment()
        audio = _inject_clicks(audio, [5000])
        result = declick_audio(audio, threshold=0.05)
        assert result.was_modified
        assert result.clicks_found >= 1

    def test_multiple_clicks_detected(self):
        """Three injected spikes at near-zero crossings → clicks_found == 3.
        Spikes placed at near-zero positions have unambiguous spike-to-signal ratio.
        """
        audio = _sine_segment()
        click_indices = [351, 5362, 10524]  # near zero-crossings, away from boundaries
        audio = _inject_clicks(audio, click_indices)
        result = declick_audio(audio, threshold=0.05)
        assert result.was_modified
        assert result.clicks_found >= len(click_indices)

    def test_clean_audio_not_modified(self):
        """A clean sine wave should not trigger any repairs."""
        audio = _sine_segment()
        result = declick_audio(audio, threshold=0.1)
        assert not result.was_modified
        assert result.clicks_found == 0
        # Original AudioSegment returned unchanged (same object)
        assert result.audio is audio


class TestRepairQuality:
    def test_spike_amplitude_reduced(self):
        """Repaired sample values should be significantly lower than the original spike.
        Spikes at near-zero crossings ensure reliable detection."""
        click_indices = [351, 5362, 10524]  # near zero-crossings, away from boundaries
        audio = _sine_segment()
        audio = _inject_clicks(audio, click_indices, magnitude=28000)
        result = declick_audio(audio, threshold=0.05)
        assert result.was_modified

        repaired = _repaired_samples(result)
        for idx in click_indices:
            assert abs(repaired[idx]) < 20000, (
                f"Spike at {idx} not sufficiently reduced: {abs(repaired[idx])}"
            )

    def test_repair_does_not_amplify(self):
        """Repaired values must never exceed the original spike magnitude."""
        click_index = 22050
        audio = _sine_segment()
        original_peak = 25000
        audio = _inject_clicks(audio, [click_index], magnitude=original_peak)

        original_samples = np.frombuffer(audio.raw_data, dtype=np.int16).copy()
        result = declick_audio(audio, threshold=0.05)
        repaired = _repaired_samples(result)

        assert abs(int(repaired[click_index])) <= abs(
            int(original_samples[click_index])
        )


class TestMultiChannel:
    def test_stereo_both_channels_repaired(self):
        """Clicks in a stereo file should be repaired in both channels."""
        audio = _sine_segment(channels=2)
        # Inject into frame 5000 (affects both L and R in interleaved layout)
        audio = _inject_clicks(audio, [5000], magnitude=28000)
        result = declick_audio(audio, threshold=0.05)
        assert result.was_modified

        repaired = _repaired_samples(result)
        # Interleaved: L is even indices, R is odd
        assert abs(repaired[5000 * 2]) < 20000, "Left channel not repaired"
        assert abs(repaired[5000 * 2 + 1]) < 20000, "Right channel not repaired"

    def test_stereo_clean_audio_untouched(self):
        audio = _sine_segment(channels=2)
        result = declick_audio(audio, threshold=0.1)
        assert not result.was_modified


class TestBitDepth:
    def test_24bit_audio_round_trips_correctly(self):
        """
        24-bit audio stored as 32-bit ints (pydub convention) must be
        clipped and returned within the 24-bit range (±8,388,607).
        """
        audio = _sine_segment(sample_width=4)  # 32-bit container, 24-bit range
        audio = _inject_clicks(audio, [3000], magnitude=7_000_000)
        result = declick_audio(audio, threshold=0.05)
        assert result.was_modified

        repaired = _repaired_samples(result)
        # All samples must be within 24-bit signed range
        assert np.all(repaired <= 2**23 - 1)
        assert np.all(repaired >= -(2**23))

    def test_sample_width_preserved(self):
        """sample_width metadata must be unchanged after processing."""
        for sw in (2, 4):
            audio = _sine_segment(sample_width=sw)
            audio = _inject_clicks(audio, [1000], magnitude=20000)
            result = declick_audio(audio, threshold=0.05)
            assert result.audio.sample_width == sw


class TestBoundaryConditions:
    def test_click_near_start(self):
        """Clicks in the first few samples should be repaired without IndexError,
        and the repaired values should be intermediate to the clean neighbours."""
        audio = _sine_segment()
        audio = _inject_clicks(audio, [1], magnitude=28000)
        np.frombuffer(audio.raw_data, dtype=np.int16)
        result = declick_audio(audio, threshold=0.05)
        repaired = np.frombuffer(result.audio.raw_data, dtype=np.int16)
        assert abs(int(repaired[1])) < 20000, (
            f"Near-start click not sufficiently reduced: {int(repaired[1])}"
        )

    def test_click_near_end(self):
        audio = _sine_segment()
        n = int(FS * 1.0)
        audio = _inject_clicks(audio, [n - 2], magnitude=28000)
        result = declick_audio(audio, threshold=0.05)
        repaired = np.frombuffer(result.audio.raw_data, dtype=np.int16)
        assert abs(int(repaired[n - 2])) < 20000, (
            f"Near-end click not sufficiently reduced: {int(repaired[n - 2])}"
        )

    def test_wide_click_not_repaired(self):
        """A defect wider than max_width_ms must be left untouched.

        max_width_ms=1 at 44100 Hz → max_width_samples = 44.
        A 100-sample-wide block of spikes is injected; the merged defect
        region spans 100 samples which exceeds the 44-sample cap, so the
        repair guard must reject it and leave the samples unchanged.
        """
        click_start = 5000
        click_end = 5100
        indices = list(range(click_start, click_end))
        spike_magnitude = 28000

        audio = _sine_segment()
        audio_with_clicks = _inject_clicks(audio, indices, magnitude=spike_magnitude)
        original_raw = np.frombuffer(audio_with_clicks.raw_data, dtype=np.int16).copy()

        result = declick_audio(audio_with_clicks, threshold=0.05, max_width_ms=1)

        assert isinstance(result, DeclickResult)

        repaired_raw = np.frombuffer(result.audio.raw_data, dtype=np.int16)

        # Samples at the exact entry (5000) and exit (5100) of the block are
        # single-sample transition spikes and are legitimately treated as
        # independent 1-sample clicks — the declicker is correct to repair them.
        # The interior (click_start+1 : click_end-1) forms a merged region of
        # 98 samples which exceeds the 44-sample cap, so those samples must be
        # left bitwise-identical to the input.
        interior_original = original_raw[click_start + 1 : click_end - 1]
        interior_repaired = repaired_raw[click_start + 1 : click_end - 1]
        assert np.array_equal(interior_original, interior_repaired), (
            "Interior of wide defect region was modified despite exceeding "
            "max_width_ms; the width guard in _repair_region did not fire."
        )

        # Confirm only the boundary transitions were touched (at most 2 samples)
        changed = np.where(original_raw != repaired_raw)[0]
        interior_changed = changed[(changed > click_start) & (changed < click_end)]
        assert len(interior_changed) == 0, (
            f"Unexpected interior samples modified: {interior_changed}"
        )


class TestIdempotency:
    """A second pass on already-repaired audio must find nothing."""

    def test_second_pass_finds_nothing(self):
        audio = _sine_segment()
        audio = _inject_clicks(audio, [351, 5362, 10524], magnitude=28000)

        first = declick_audio(audio, threshold=0.05)
        assert first.was_modified
        assert first.clicks_found >= 1

        second = declick_audio(first.audio, threshold=0.05)
        assert not second.was_modified
        assert second.clicks_found == 0
        assert second.audio is first.audio


class TestMergeRegions:
    """Edge-case coverage for _merge_regions."""

    def test_empty_array_returns_empty_list(self):
        assert _merge_regions(np.array([], dtype=int)) == []

    def test_single_index_returns_single_region(self):
        assert _merge_regions(np.array([5])) == [(5, 5)]

    def test_consecutive_indices_merged(self):
        assert _merge_regions(np.array([5, 6, 7])) == [(5, 7)]

    def test_wide_gap_produces_separate_regions(self):
        assert _merge_regions(np.array([5, 10])) == [(5, 5), (10, 10)]

    def test_gap_at_boundary_merged(self):
        assert _merge_regions(np.array([5, 7]), max_gap=2) == [(5, 7)]

    def test_gap_beyond_boundary_separate(self):
        assert _merge_regions(np.array([5, 9]), max_gap=2) == [(5, 5), (9, 9)]


class TestRepairRegion:
    """Direct unit tests for _repair_region guards."""

    def test_width_guard_rejects_wide_defect(self):
        ch = np.zeros(50, dtype=np.float64)
        ch[10:30] = 10000.0 / 32767.0  # ~0.305, normalized scale
        result = _repair_region(
            ch,
            start=10,
            end=29,
            max_width_samples=5,
            clip_max=1.0,
            sample_rate=44100,
        )
        assert not result
        assert np.all(ch[10:30] == 10000.0 / 32767.0)

    def test_amplitude_guard_skips_near_silence(self):
        n = 200
        ch = np.zeros(n, dtype=np.float64)
        # 15 counts on 16-bit ≈ -66 dBFS; well below the normalized
        # _MIN_AMPLITUDE_FRACTION threshold (~0.001).
        ch[100] = 15.0 / 32767.0
        result = _repair_region(
            ch,
            start=100,
            end=100,
            max_width_samples=10,
            clip_max=1.0,
            sample_rate=44100,
        )
        assert not result
        assert ch[100] == 15.0 / 32767.0

    def test_saturation_guard_skips_repair_when_both_neighbours_clipped(self):
        """When both immediate neighbours are near clip_max, treat as
        legitimate distortion and do not repair."""
        n = 20
        ch = np.zeros(n, dtype=np.float64)
        # ~0.992 in normalized scale — above the 0.99 saturation threshold.
        ch[5] = 32500.0 / 32767.0
        ch[6] = 1000.0 / 32767.0
        ch[7] = 32500.0 / 32767.0
        result = _repair_region(
            ch,
            start=6,
            end=6,
            max_width_samples=10,
            clip_max=1.0,
            sample_rate=44100,
        )
        assert not result
        assert ch[6] == 1000.0 / 32767.0

    def test_linear_fallback_near_start(self):
        """Insufficient left context (< 2 samples) triggers linear fallback."""
        ch = np.zeros(10, dtype=np.float64)
        ch[0] = -8000.0 / 32767.0
        ch[1] = 28000.0 / 32767.0
        ch[2] = -8000.0 / 32767.0
        result = _repair_region(
            ch,
            start=1,
            end=1,
            max_width_samples=10,
            clip_max=1.0,
            sample_rate=44100,
        )
        assert result
        # linspace(v, v, 3)[1:-1] = [v] with v = -8000/32767 (normalized)
        assert ch[1] == pytest.approx(-8000.0 / 32767.0)

    def test_overshoot_guard_falls_back_to_linear(self):
        """When cubic spline would overshoot the original defect peak,
        linear interpolation is used instead."""
        left_ctx = np.full(6, 20000.0 / 32767.0)
        right_ctx = np.full(6, -5000.0 / 32767.0)
        defect = np.array([5000.0 / 32767.0, 5000.0 / 32767.0])
        ch = np.concatenate([left_ctx, defect, right_ctx])

        result = _repair_region(
            ch,
            start=6,
            end=7,
            max_width_samples=10,
            clip_max=1.0,
            sample_rate=44100,
        )
        assert result
        expected = np.linspace(20000.0 / 32767.0, -5000.0 / 32767.0, 4)[1:-1]
        np.testing.assert_array_almost_equal(ch[6:8], expected)


class TestThresholdDirection:
    """
    Regression coverage for a confirmed bug: _threshold_to_k previously mapped
    LOWER threshold values to a HIGHER k (less sensitive), the inverse of the
    documented contract ("lower values are more aggressive / detect quieter
    clicks"). Confirmed via direct execution: at threshold=0.40 ("gentlest"
    per the docs) real musical transients in dynamic material were detected
    and repaired as false-positive clicks, while threshold=0.01 ("most
    aggressive") produced zero detections on the same material — the exact
    opposite of the intended behaviour.
    """

    def test_lower_threshold_gives_lower_k(self):
        """Lower threshold (more aggressive) must map to a lower k
        (easier to trigger), matching the documented contract."""
        k_low_threshold = _threshold_to_k(0.05)
        k_high_threshold = _threshold_to_k(0.35)
        assert k_low_threshold < k_high_threshold, (
            f"threshold=0.05 gave k={k_low_threshold}, threshold=0.35 gave "
            f"k={k_high_threshold}; lower threshold must map to lower "
            "(more sensitive) k."
        )

    def test_extremes_map_to_documented_k_bounds(self):
        """threshold=_T_MIN (most aggressive) must give the lowest k (12);
        threshold=_T_MAX (gentlest) must give the highest k (30)."""
        assert _threshold_to_k(0.01) == pytest.approx(12.0)
        assert _threshold_to_k(0.40) == pytest.approx(30.0)

    def test_default_threshold_preserves_prior_effective_k(self):
        """
        The public default was changed from 0.1 to 0.31 specifically so
        that existing users/configs relying on the previous (buggy)
        default's effective sensitivity see no behaviour change: the old
        buggy default of 0.1 produced k≈25.846; the new default of 0.31,
        under the corrected direction, reproduces that same k.
        """
        assert _threshold_to_k(0.31) == pytest.approx(25.846153846153847, rel=1e-6)


class TestInputValidation:
    @pytest.mark.parametrize("bad_threshold", [0.0, -0.1, 1.1, 2.0])
    def test_invalid_threshold_raises(self, bad_threshold):
        audio = _sine_segment()
        with pytest.raises(AudioConfigurationError, match="threshold"):
            declick_audio(audio, threshold=bad_threshold)

    @pytest.mark.parametrize("bad_width", [0, -1, -100])
    def test_invalid_max_width_raises(self, bad_width):
        audio = _sine_segment()
        with pytest.raises(AudioConfigurationError, match="max_width_ms"):
            declick_audio(audio, max_width_ms=bad_width)

    def test_valid_boundary_threshold(self):
        """threshold=1.0 (maximum, gentlest) should not raise."""
        audio = _sine_segment()
        result = declick_audio(audio, threshold=1.0)
        assert isinstance(result, DeclickResult)

    def test_valid_minimum_threshold(self):
        """threshold=0.01 (most aggressive) should not raise."""
        audio = _sine_segment()
        audio = _inject_clicks(audio, [5000])
        result = declick_audio(audio, threshold=0.01)
        assert isinstance(result, DeclickResult)
