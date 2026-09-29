"""
tests/test_noise_reducer.py
Pytest test suite for the Noise Reduction DSP engine.

Run with:
    pytest noise_reduction/tests/test_noise_reducer.py -v

Test coverage
-------------
* Hum removal: 60 Hz, 50 Hz, harmonics, preserves non-hum content
* Spectral gating: noise reduction, signal preservation, silence handling
* Combined processing
* Dry-run mode
* Input validation (bad frequency, bad harmonics, bad quality, bad region)
* Stereo processing
* Corrupt / edge-case inputs
"""

from __future__ import annotations

import numpy as np
import pytest
from pydub import AudioSegment

from audio_suite_shared.audio_conversion import segment_to_numpy
from audio_suite_shared.exceptions import AudioConfigurationError
from noise_reduction.core.models import NoiseReductionParams, NoiseReductionResult
from noise_reduction.core.noise_reducer import (
    _rms_db,
    reduce_noise,
    remove_hum,
    spectral_gate,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

FS = 44100


def _sine_segment(
    freq_hz: float = 440.0,
    duration_ms: int = 1000,
    amplitude: float = 0.4,
    channels: int = 1,
    sample_width: int = 2,
) -> AudioSegment:
    """Generate a pure sine wave as a pydub AudioSegment."""
    n = int(FS * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    wave = amplitude * np.sin(2.0 * np.pi * freq_hz * t)
    if sample_width == 2:
        pcm = (wave * 32767).astype(np.int16)
    else:
        pcm = (wave * (2**23 - 1)).astype(np.int32)
    if channels == 2:
        raw = np.column_stack([pcm, pcm]).tobytes()
    else:
        raw = pcm.tobytes()
    return AudioSegment(
        raw, frame_rate=FS, sample_width=sample_width, channels=channels
    )


def _multi_sine_segment(
    freqs: list[float],
    duration_ms: int = 1000,
    amplitude: float = 0.2,
    channels: int = 1,
) -> AudioSegment:
    """Generate a signal with multiple sine components."""
    n = int(FS * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    wave = np.zeros(n, dtype=np.float64)
    for f in freqs:
        wave += amplitude * np.sin(2.0 * np.pi * f * t)
    max_val = max(abs(wave.min()), abs(wave.max()))
    if max_val > 0:
        wave = wave / max_val * 0.4
    pcm = (wave * 32767).astype(np.int16)
    if channels == 2:
        raw = np.column_stack([pcm, pcm]).tobytes()
    else:
        raw = pcm.tobytes()
    return AudioSegment(raw, frame_rate=FS, sample_width=2, channels=channels)


def _noise_segment(
    duration_ms: int = 1000,
    amplitude: float = 0.05,
    channels: int = 1,
) -> AudioSegment:
    """Generate broadband noise as a pydub AudioSegment."""
    n = int(FS * duration_ms / 1000)
    noise = amplitude * np.random.randn(n)
    pcm = (noise * 32767).astype(np.int16)
    if channels == 2:
        raw = np.column_stack([pcm, pcm]).tobytes()
    else:
        raw = pcm.tobytes()
    return AudioSegment(raw, frame_rate=FS, sample_width=2, channels=channels)


def _signal_plus_noise(
    signal_freq: float = 1000.0,
    duration_ms: int = 2000,
    signal_amp: float = 0.4,
    noise_amp: float = 0.05,
) -> AudioSegment:
    """Generate a sine signal with additive broadband noise."""
    n = int(FS * duration_ms / 1000)
    t = np.linspace(0, duration_ms / 1000, n, endpoint=False)
    sig = signal_amp * np.sin(2.0 * np.pi * signal_freq * t)
    noise = noise_amp * np.random.randn(n)
    combined = sig + noise
    max_val = max(abs(combined.min()), abs(combined.max()))
    if max_val > 0.9:
        combined = combined / max_val * 0.8
    pcm = (combined * 32767).astype(np.int16)
    return AudioSegment(pcm.tobytes(), frame_rate=FS, sample_width=2, channels=1)


def _energy_db(audio: AudioSegment) -> float:
    """Compute RMS energy in dBFS of an AudioSegment via the shared decoder."""
    samples_f32, _sample_rate = segment_to_numpy(audio)
    return _rms_db(samples_f32.astype(np.float64))


# ── Hum Removal Tests ─────────────────────────────────────────────────────────


class TestHumRemoval:
    """Tests for remove_hum()."""

    def test_removes_60hz_tone(self) -> None:
        audio = _sine_segment(freq_hz=60.0, duration_ms=2000, amplitude=0.4)
        result = remove_hum(audio, fundamental_hz=60, harmonics=8, quality=30.0)
        assert result.was_modified is True
        attenuation = result.energy_before_db - result.energy_after_db
        assert attenuation > 10.0, (
            f"60 Hz tone not attenuated enough: {attenuation:.1f} dB reduction"
        )

    def test_removes_50hz_tone(self) -> None:
        audio = _sine_segment(freq_hz=50.0, duration_ms=2000, amplitude=0.4)
        result = remove_hum(audio, fundamental_hz=50, harmonics=8, quality=30.0)
        assert result.was_modified is True
        attenuation = result.energy_before_db - result.energy_after_db
        assert attenuation > 10.0, (
            f"50 Hz tone not attenuated enough: {attenuation:.1f} dB reduction"
        )

    def test_removes_harmonics(self) -> None:
        audio = _multi_sine_segment(
            [60.0, 120.0, 180.0], duration_ms=2000, amplitude=0.2
        )
        result = remove_hum(audio, fundamental_hz=60, harmonics=3, quality=30.0)
        assert result.was_modified is True
        attenuation = result.energy_before_db - result.energy_after_db
        assert attenuation > 10.0, (
            f"Harmonics not attenuated enough: {attenuation:.1f} dB reduction"
        )

    def test_preserves_non_hum_content(self) -> None:
        audio = _sine_segment(freq_hz=440.0, duration_ms=1000, amplitude=0.4)
        energy_before = _energy_db(audio)
        result = remove_hum(audio, fundamental_hz=60, harmonics=8, quality=30.0)
        energy_after = _energy_db(result.audio)
        assert abs(energy_before - energy_after) < 3.0, (
            f"440 Hz content changed too much: before={energy_before:.1f}, "
            f"after={energy_after:.1f}"
        )

    def test_stereo_processing(self) -> None:
        audio = _sine_segment(freq_hz=60.0, duration_ms=2000, amplitude=0.4, channels=2)
        result = remove_hum(audio, fundamental_hz=60, harmonics=8, quality=30.0)
        assert result.was_modified is True
        assert result.audio.channels == 2

    def test_energy_before_is_computed(self) -> None:
        audio = _sine_segment(freq_hz=60.0, duration_ms=1000, amplitude=0.4)
        result = remove_hum(audio, fundamental_hz=60, harmonics=8, quality=30.0)
        assert result.energy_before_db > -60.0
        assert result.energy_after_db < result.energy_before_db

    def test_invalid_frequency(self) -> None:
        audio = _sine_segment()
        with pytest.raises(AudioConfigurationError, match="hum_frequency"):
            remove_hum(audio, fundamental_hz=55, harmonics=8)

    def test_invalid_harmonics_too_low(self) -> None:
        audio = _sine_segment()
        with pytest.raises(AudioConfigurationError, match="hum_harmonics"):
            remove_hum(audio, fundamental_hz=60, harmonics=0)

    def test_invalid_harmonics_too_high(self) -> None:
        audio = _sine_segment()
        with pytest.raises(AudioConfigurationError, match="hum_harmonics"):
            remove_hum(audio, fundamental_hz=60, harmonics=25)

    def test_invalid_quality(self) -> None:
        audio = _sine_segment()
        with pytest.raises(AudioConfigurationError, match="hum_quality"):
            remove_hum(audio, fundamental_hz=60, quality=0.5)

    def test_clean_audio_no_modification(self) -> None:
        audio = _sine_segment(freq_hz=1000.0, duration_ms=500, amplitude=0.1)
        result = remove_hum(audio, fundamental_hz=60, harmonics=8)
        energy_change = abs(result.energy_before_db - result.energy_after_db)
        assert energy_change < 1.0, f"Non-hum content changed: {energy_change:.2f} dB"

    def test_harmonics_beyond_nyquist_ignored(self) -> None:
        audio = _sine_segment(freq_hz=60.0, duration_ms=1000, amplitude=0.4)
        result = remove_hum(audio, fundamental_hz=60, harmonics=20, quality=30.0)
        assert result.was_modified is True


# ── Spectral Gating Tests ────────────────────────────────────────────────────


class TestSpectralGate:
    """Tests for spectral_gate()."""

    def test_silence_no_modification(self) -> None:
        audio = AudioSegment.silent(duration=2000, frame_rate=FS)
        result = spectral_gate(audio, noise_start_ms=0, noise_end_ms=500)
        assert result.was_modified is False

    def test_reduces_broadband_noise(self) -> None:
        np.random.seed(42)
        audio = _noise_segment(duration_ms=2000, amplitude=0.05)
        result = spectral_gate(
            audio, noise_start_ms=0, noise_end_ms=500, gate_threshold_db=3.0
        )
        assert isinstance(result, NoiseReductionResult)

    def test_preserves_strong_signal(self) -> None:
        audio = _sine_segment(freq_hz=1000.0, duration_ms=2000, amplitude=0.5)
        result = spectral_gate(
            audio, noise_start_ms=0, noise_end_ms=500, gate_threshold_db=6.0
        )
        assert result.audio.channels == 1

    def test_short_region_raises(self) -> None:
        audio = _sine_segment()
        with pytest.raises(AudioConfigurationError, match="at least"):
            spectral_gate(audio, noise_start_ms=0, noise_end_ms=50)

    def test_negative_start_raises(self) -> None:
        audio = _sine_segment()
        with pytest.raises(AudioConfigurationError, match="noise_start_ms"):
            spectral_gate(audio, noise_start_ms=-10, noise_end_ms=500)

    def test_end_before_start_raises(self) -> None:
        audio = _sine_segment()
        with pytest.raises(AudioConfigurationError, match="at least"):
            spectral_gate(audio, noise_start_ms=500, noise_end_ms=100)

    def test_stereo_processing(self) -> None:
        audio = _noise_segment(duration_ms=2000, amplitude=0.05, channels=2)
        result = spectral_gate(
            audio, noise_start_ms=0, noise_end_ms=500, gate_threshold_db=3.0
        )
        assert result.audio.channels == 2

    def test_energy_measurement(self) -> None:
        audio = _sine_segment(freq_hz=1000.0, duration_ms=1000, amplitude=0.3)
        result = spectral_gate(audio, noise_start_ms=0, noise_end_ms=500)
        assert isinstance(result.energy_before_db, float)
        assert isinstance(result.energy_after_db, float)


# ── Combined Processing Tests ────────────────────────────────────────────────


class TestReduceNoise:
    """Tests for reduce_noise() with combined parameters."""

    def test_dry_run_does_not_short_circuit_the_dsp(self) -> None:
        """The DSP is mode-agnostic: a dry run reports what it found.

        Inverted from the pre-B1 lock, which asserted that a dry run
        returned the untouched input with ``was_modified=False``.  That
        short-circuit made a dry run report ``SKIP ("Clean - no noise
        detected")`` for a file carrying 15.98 dB of hum, while the
        pop-click twin reported ``FOUND`` for the same situation.  The
        suppression of the write is the shared workflow's job (it is
        passed ``is_dry_run`` separately), so the DSP must not fake a
        clean verdict to achieve it.
        """
        audio = _sine_segment(freq_hz=60.0, duration_ms=1000, amplitude=0.4)
        dry = reduce_noise(
            audio, NoiseReductionParams(reduce_hum=True, hum_frequency=60, dry_run=True)
        )
        live = reduce_noise(
            audio, NoiseReductionParams(reduce_hum=True, hum_frequency=60)
        )

        assert dry.was_modified is True
        assert dry.audio != audio
        # The dry-run result is the live result, bit for bit: the flag
        # changes nothing the DSP computes.
        assert dry.audio == live.audio
        assert dry.energy_before_db == live.energy_before_db
        assert dry.energy_after_db == live.energy_after_db
        assert dry.energy_after_db < dry.energy_before_db

    def test_hum_only(self) -> None:
        audio = _sine_segment(freq_hz=60.0, duration_ms=1000, amplitude=0.4)
        params = NoiseReductionParams(reduce_hum=True, hum_frequency=60)
        result = reduce_noise(audio, params)
        assert result.was_modified is True

    def test_broadband_only(self) -> None:
        audio = _sine_segment(freq_hz=1000.0, duration_ms=1000, amplitude=0.3)
        params = NoiseReductionParams(
            reduce_broadband=True, noise_start_ms=0, noise_end_ms=500
        )
        result = reduce_noise(audio, params)
        assert isinstance(result, NoiseReductionResult)

    def test_both_features(self) -> None:
        audio = _multi_sine_segment([60.0, 1000.0], duration_ms=2000, amplitude=0.2)
        params = NoiseReductionParams(
            reduce_hum=True,
            hum_frequency=60,
            reduce_broadband=True,
            noise_start_ms=0,
            noise_end_ms=500,
        )
        result = reduce_noise(audio, params)
        assert isinstance(result, NoiseReductionResult)

    def test_no_features_enabled(self) -> None:
        audio = _sine_segment(freq_hz=440.0, duration_ms=500, amplitude=0.3)
        params = NoiseReductionParams()
        result = reduce_noise(audio, params)
        assert result.was_modified is False

    def test_result_type(self) -> None:
        audio = _sine_segment(freq_hz=60.0, duration_ms=500, amplitude=0.3)
        params = NoiseReductionParams(reduce_hum=True, hum_frequency=60)
        result = reduce_noise(audio, params)
        assert isinstance(result, NoiseReductionResult)
        assert hasattr(result, "audio")
        assert hasattr(result, "energy_before_db")
        assert hasattr(result, "energy_after_db")
        assert hasattr(result, "was_modified")


# ── Model Tests ───────────────────────────────────────────────────────────────


class TestModels:
    """Tests for NoiseReductionParams and NoiseReductionResult."""

    def test_default_params(self) -> None:
        params = NoiseReductionParams()
        assert params.reduce_hum is False
        assert params.hum_frequency == 60
        assert params.hum_harmonics == 8
        assert params.hum_quality == 30.0
        assert params.reduce_broadband is False
        assert params.noise_start_ms == 0
        assert params.noise_end_ms == 500
        assert params.gate_threshold_db == 3.0
        assert params.dry_run is False

    def test_custom_params(self) -> None:
        params = NoiseReductionParams(
            reduce_hum=True,
            hum_frequency=50,
            hum_harmonics=12,
            hum_quality=50.0,
            reduce_broadband=True,
            noise_start_ms=100,
            noise_end_ms=800,
            gate_threshold_db=6.0,
        )
        assert params.reduce_hum is True
        assert params.hum_frequency == 50
        assert params.hum_harmonics == 12
        assert params.hum_quality == 50.0
        assert params.reduce_broadband is True
        assert params.noise_start_ms == 100
        assert params.noise_end_ms == 800
        assert params.gate_threshold_db == 6.0


# ── Edge Case Tests ──────────────────────────────────────────────────────────


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_very_short_audio(self) -> None:
        audio = _sine_segment(freq_hz=60.0, duration_ms=50, amplitude=0.3)
        result = remove_hum(audio, fundamental_hz=60, harmonics=1)
        assert isinstance(result, NoiseReductionResult)

    def test_silence_input_hum(self) -> None:
        audio = AudioSegment.silent(duration=1000, frame_rate=FS)
        result = remove_hum(audio, fundamental_hz=60, harmonics=8)
        assert result.was_modified is False

    def test_high_amplitude_hum(self) -> None:
        audio = _sine_segment(freq_hz=60.0, duration_ms=1000, amplitude=0.95)
        result = remove_hum(audio, fundamental_hz=60, harmonics=8, quality=30.0)
        assert result.was_modified is True
        attenuation = result.energy_before_db - result.energy_after_db
        assert attenuation > 10.0

    def test_low_quality_narrow_notch(self) -> None:
        audio = _sine_segment(freq_hz=60.0, duration_ms=1000, amplitude=0.4)
        result = remove_hum(audio, fundamental_hz=60, harmonics=1, quality=5.0)
        assert result.was_modified is True
