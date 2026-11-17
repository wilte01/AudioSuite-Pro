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
* The neural engine: the model measured on real audio, a missing extra, an
  unknown engine and the 16-bit refusal (2.8.0)

Changed in 2.8.0: the neural engine's locks join the spectral gate's, so both
broadband engines are held to the same measured outcome.  The hum detector's
locks measure the notched file's own spectrum: a 50 Hz hum is never notched at
60 Hz, and the content between the partials is left alone.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from pydub import AudioSegment

from audio_suite_shared.audio_conversion import segment_to_numpy
from audio_suite_shared.exceptions import (
    AudioConfigurationError,
    AudioMissingDependencyError,
)
from noise_reduction.core.models import (
    NEURAL_ENGINE,
    NoiseReductionParams,
    NoiseReductionResult,
    NoiseWindow,
)
from noise_reduction.core.noise_reducer import (
    _rms_db,
    analyse_noise,
    check_neural_bit_depth,
    detect_hum,
    detect_noise_profile,
    neural_dependency_reason,
    reduce_noise,
    remove_hum,
    remove_hum_lines,
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

    def test_the_cascade_is_built_as_second_order_sections(self) -> None:
        """The cascade is the SOS matrix the module docstring promises.

        The attenuation tests above pass either way, because a biquad filtered
        through ``lfilter`` and one applied as a section of ``sosfilt`` are the
        same maths - which is exactly how the transfer-function form survived a
        docstring naming SOS.  The artefact that tells them apart is the matrix
        itself: one ``[b0, b1, b2, 1, a1, a2]`` row per frequency, in the order
        given, with frequencies at or above Nyquist left out.
        """
        from scipy.signal import iirnotch

        from noise_reduction.core.noise_reducer import _build_notch_sections

        frequencies = [60.0 * order for order in range(1, 9)]

        sos = _build_notch_sections(frequencies, 30.0, FS)

        assert sos.shape == (8, 6)
        assert sos.dtype == np.float64
        for row, freq in zip(sos, frequencies, strict=True):
            assert np.array_equal(row, np.concatenate(iirnotch(freq, 30.0, fs=FS)))

        # Nyquist has no normalised frequency to design at, so it is dropped
        # rather than handed to iirnotch as w0 == 1.
        assert _build_notch_sections([60.0, FS / 2], 30.0, FS).shape == (1, 6)

    def test_the_matrix_reaches_sosfilt_once_per_channel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Both hum paths hand the ``(n, 6)`` matrix to ``sosfilt``.

        The test above proves the builder produces sections; this one proves
        the DSP *applies* them, which is the half a per-section ``lfilter``
        chain would satisfy numerically while disagreeing with the module
        docstring.  The spy wraps the real function, so the audio is filtered
        exactly as shipped - only the argument is observed.
        """
        from scipy.signal import sosfilt as real_sosfilt

        import noise_reduction.core.noise_reducer as reducer

        seen: list[np.ndarray] = []

        def _spy(sos: Any, x: Any, *args: Any, **kwargs: Any) -> Any:
            seen.append(np.asarray(sos))
            return real_sosfilt(sos, x, *args, **kwargs)

        monkeypatch.setattr(reducer, "sosfilt", _spy)
        stereo = _multi_sine_segment(
            [60.0, 120.0, 180.0], duration_ms=1000, amplitude=0.3
        ).set_channels(2)

        manual = remove_hum(stereo, fundamental_hz=60, harmonics=3)
        selective = remove_hum_lines(stereo, 60, (1, 2))

        assert stereo.channels == 2
        assert manual.was_modified is True
        assert selective.was_modified is True
        # One call per channel, per path: a single sosfilt per channel, the
        # manual cascade's every order then the selective path's measured two.
        assert [sos.shape for sos in seen] == [(3, 6), (3, 6), (2, 6), (2, 6)]
        assert np.array_equal(seen[0], seen[1])  # same matrix, both channels
        assert np.array_equal(seen[2], seen[3])

    def test_the_rows_reaching_sosfilt_are_normalised_sections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The argument is an SOS matrix, not a stack of transfer functions.

        A shape check alone cannot see the difference: a per-frequency
        ``[b0, b1, b2, a0, a1, a2]`` stack is also ``(n, 6)``, so a chain of
        ``lfilter`` calls dressed that way would pass the test above while
        disagreeing with the module docstring.  The artefact that separates
        them is the row layout ``sosfilt`` requires - numerator first, then the
        denominator normalised so ``a0 == 1`` - so this lock reads the actual
        argument on the fixed manual cascade and on the selective path, with
        the spy wrapping the real filter so the audio is untouched.
        """
        from scipy.signal import sosfilt as real_sosfilt

        import noise_reduction.core.noise_reducer as reducer

        seen: list[np.ndarray] = []

        def _spy(sos: Any, x: Any, *args: Any, **kwargs: Any) -> Any:
            seen.append(sos)
            return real_sosfilt(sos, x, *args, **kwargs)

        monkeypatch.setattr(reducer, "sosfilt", _spy)
        hum = _multi_sine_segment([60.0, 120.0, 180.0], duration_ms=1000, amplitude=0.3)

        manual = remove_hum(hum, fundamental_hz=60, harmonics=3)
        selective = remove_hum_lines(hum, 60, (1, 2))

        assert manual.was_modified is True
        assert selective.was_modified is True
        assert len(seen) == 2  # mono input: one application per path
        for sos, sections in zip(seen, (3, 2), strict=True):
            assert isinstance(sos, np.ndarray)
            assert sos.ndim == 2
            assert sos.dtype == np.float64
            assert sos.shape == (sections, 6)
            # ``a0`` normalised to one is what makes the row a section; an
            # unnormalised or padded pair stack leaves it elsewhere.
            assert np.all(sos[:, 3] == 1.0)
            # And every row carries a real numerator and denominator tail.
            assert np.all(np.abs(sos[:, 0]) > 0.0)
            assert np.any(sos[:, 4] != 0.0)


# ── Hum detection (2.8.0) ────────────────────────────────────────────────


def _hum_fixture(
    fundamental_hz: int,
    partials: tuple[float, ...],
    *,
    music_hz: float | None = None,
    music_amplitude: float = 0.0,
    duration_ms: int = 3000,
) -> AudioSegment:
    """Build a segment from hum partials plus optional music content."""
    seconds = duration_ms / 1000.0
    time_axis = np.linspace(0.0, seconds, int(FS * seconds), endpoint=False)
    signal = np.zeros_like(time_axis)
    for order, amplitude in enumerate(partials, start=1):
        signal += amplitude * np.sin(2.0 * np.pi * fundamental_hz * order * time_axis)
    if music_hz is not None:
        signal += music_amplitude * np.sin(2.0 * np.pi * music_hz * time_axis)
    pcm = (np.clip(signal, -1.0, 1.0) * 32767).astype(np.int16)
    return AudioSegment(pcm.tobytes(), frame_rate=FS, sample_width=2, channels=1)


def _tone_level_db(audio: AudioSegment, freq_hz: float) -> float:
    """Return a tone's peak bin level in dB, decoded from the segment itself."""
    samples, _rate = segment_to_numpy(audio)
    mono = np.mean(samples.astype(np.float64), axis=0)
    spectrum = np.abs(np.fft.rfft(mono))
    freqs = np.fft.rfftfreq(mono.size, 1.0 / FS)
    peak = float(np.max(spectrum[np.abs(freqs - freq_hz) <= 3.0]))
    return 20.0 * float(np.log10(max(peak, 1e-12)))


class TestHumDetection:
    """The file decides 50 or 60 Hz, and only its live partials are notched."""

    def test_detects_60_hz_and_the_partials_the_file_carries(self) -> None:
        audio = _hum_fixture(
            60, (0.30, 0.12, 0.05), music_hz=500.0, music_amplitude=0.03
        )

        profile = detect_hum(audio)

        assert profile is not None
        assert profile.fundamental_hz == 60
        assert profile.orders == (1, 2, 3)
        assert profile.level_db > 20.0
        assert "60 Hz auto" in profile.describe()
        assert "3 harmonics" in profile.describe()

    def test_detects_50_hz(self) -> None:
        audio = _hum_fixture(50, (0.30, 0.12))

        profile = detect_hum(audio)

        assert profile is not None
        assert profile.fundamental_hz == 50
        assert profile.orders == (1, 2)

    def test_a_clean_file_measures_no_hum(self) -> None:
        """A tone must not read as hum: its own leakage is not a partial."""
        audio = _sine_segment(freq_hz=500.0, duration_ms=2000, amplitude=0.3)

        assert detect_hum(audio) is None

    def test_the_auto_cascade_notches_the_measured_lines_only(self) -> None:
        """The notched file is decoded and measured, not trusted.

        The 60 Hz partial must fall while 500 Hz - content sitting between the
        partials - keeps its level, which a fixed eight-harmonic cascade at the
        wrong frequency could not do.
        """
        audio = _hum_fixture(
            60, (0.30, 0.12, 0.05), music_hz=500.0, music_amplitude=0.20
        )
        before_hum = _tone_level_db(audio, 60.0)
        before_music = _tone_level_db(audio, 500.0)

        result = reduce_noise(audio, NoiseReductionParams(reduce_hum=True))

        assert result.was_modified is True
        assert _tone_level_db(result.audio, 60.0) < before_hum - 20.0
        assert _tone_level_db(result.audio, 500.0) == pytest.approx(
            before_music, abs=1.0
        )

    def test_a_clean_file_is_left_byte_identical(self) -> None:
        audio = _sine_segment(freq_hz=500.0, duration_ms=2000, amplitude=0.3)

        result = reduce_noise(audio, NoiseReductionParams(reduce_hum=True))

        assert result.was_modified is False
        assert result.audio is audio
        assert result.hum_profile is None

    def test_the_manual_frequency_is_the_override(self) -> None:
        """Choosing 50 Hz on a 60 Hz file keeps the manual, fixed cascade."""
        audio = _hum_fixture(60, (0.30, 0.12))

        manual_wrong = reduce_noise(
            audio,
            NoiseReductionParams(reduce_hum=True, hum_auto=False, hum_frequency=50),
        )
        manual_right = reduce_noise(
            audio,
            NoiseReductionParams(reduce_hum=True, hum_auto=False, hum_frequency=60),
        )

        assert manual_wrong.was_modified is False
        assert manual_right.was_modified is True
        assert manual_right.hum_profile is None
        assert detect_hum(audio).fundamental_hz == 60  # the measurement, for contrast

    def test_the_measured_profile_is_reported(self) -> None:
        audio = _hum_fixture(60, (0.30, 0.12, 0.05))

        result = reduce_noise(audio, NoiseReductionParams(reduce_hum=True))

        assert result.hum_profile is not None
        assert result.hum_profile.orders == (1, 2, 3)
        assert "3 harmonics" in result.hum_profile.describe()


# ── Spectral Gating Tests ────────────────────────────────────────────────


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


# ── Neural engine (2.8.0) ─────────────────────────────────────────────────────


def _install_fake_rnnoise(
    monkeypatch: pytest.MonkeyPatch, *, gain: float = 0.5
) -> None:
    """Register a fake ``pyrnnoise`` that scales the signal by *gain*.

    Reproduces the adapter's measured contract - int16 frames in, int16 frames
    out, cut at 10 ms - so the engine is exercised without the optional extra,
    the same way ``tests/test_rnnoise_engine.py`` in this package does.
    """
    module = types.ModuleType("pyrnnoise")

    class _FakeRNNoise:
        def __init__(self, sample_rate: int) -> None:
            self.sample_rate = sample_rate

        def denoise_chunk(self, chunk: Any, partial: bool = False) -> Any:
            array = np.atleast_2d(np.asarray(chunk, dtype=np.int16))
            processed = np.rint(array.astype(np.float64) * gain).astype(np.int16)
            for start in range(0, processed.shape[1], 480):
                frame = processed[:, start : start + 480]
                yield np.zeros((array.shape[0], 1), dtype=np.float32), frame

    module.RNNoise = _FakeRNNoise  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pyrnnoise", module)


def _neural_params(**overrides: Any) -> NoiseReductionParams:
    values: dict[str, Any] = {
        "reduce_broadband": True,
        "broadband_engine": NEURAL_ENGINE,
    }
    values.update(overrides)
    return NoiseReductionParams(**values)


class TestNoiseProfileDetection:
    """The spectral gate measures the file instead of trusting its first 500 ms.

    The default window was the start of the file, which is an intro far more
    often than it is noise: a hot intro gave the gate a floor so high it ate the
    music, and a quiet intro gave it one so low the hiss survived.  Detection
    names the stretch it used so a wrong verdict is inspectable.
    """

    @staticmethod
    def _loud_then_quiet() -> AudioSegment:
        """800 ms of hot hiss, then 2200 ms of the track's real floor."""
        np.random.seed(7)
        return _noise_segment(duration_ms=800, amplitude=0.3) + _noise_segment(
            duration_ms=2200, amplitude=0.002
        )

    @staticmethod
    def _rms(segment: AudioSegment) -> float:
        return float(_rms_db(segment_to_numpy(segment)[0].T.astype(np.float64)))

    def test_the_window_comes_from_the_quiet_stretch(self) -> None:
        window = detect_noise_profile(self._loud_then_quiet())

        assert window is not None
        assert window.start_ms >= 800
        assert window.end_ms <= 3000
        assert window.rms_dbfs < -45.0
        assert 0.0 < window.flatness <= 1.0

    def test_equal_level_noise_beats_a_tone(self) -> None:
        """Quiet is the first filter; flatness decides between equally quiet.

        A held note and a hiss at the same level have the same power, so only
        the spectral shape can tell the gate which one is the floor.
        """
        tone = _sine_segment(freq_hz=440.0, duration_ms=1000, amplitude=0.0125)
        np.random.seed(11)
        hiss = _noise_segment(duration_ms=1000, amplitude=0.012)

        window = detect_noise_profile(tone + hiss + tone)

        assert window is not None
        assert 1000 <= window.start_ms < 2000
        assert window.flatness > 0.2

    def test_a_musical_rest_loses_to_the_hiss_beside_it(self) -> None:
        """The quietest window can still be music, and the trial says so.

        A rest in the arrangement is quieter than the hiss, so the old
        quietest-then-flattest rule took its profile; gating with that profile
        removes 23 dB from the rest itself and 0.04 dB from the hiss, which is
        the noise the run exists to remove.  The hiss sits 5 dB louder - inside
        the candidate range - and the profiles tie on music damage, so flatness
        chooses it.
        """
        tone = _sine_segment(freq_hz=440.0, duration_ms=1000, amplitude=0.25)
        rest = _sine_segment(freq_hz=330.0, duration_ms=2000, amplitude=0.02)
        rest = rest.overlay(
            _sine_segment(freq_hz=440.0, duration_ms=2000, amplitude=0.02)
        )
        np.random.seed(11)
        hiss = _noise_segment(duration_ms=2000, amplitude=0.035)

        window = detect_noise_profile(tone + rest + hiss)

        assert window is not None
        assert window.start_ms >= 3000
        assert window.flatness > 0.2
        assert window.trial_db < 1.0

    def test_the_trial_admits_both_quiet_candidates_so_flatness_decides(self) -> None:
        """The guard reads 0.00 dB for the rest and the hiss alike.

        Measured on this fixture, a profile taken from the musical rest and one
        taken from the hiss each remove 0.00 dB from the loudest stretch, so a
        ranking on that score would tie and the docs would be claiming a
        decision the trial does not make.  The guard passes both and the
        reading on the chosen window - near zero - is the evidence.
        """
        tone = _sine_segment(freq_hz=440.0, duration_ms=1000, amplitude=0.25)
        rest = _sine_segment(freq_hz=330.0, duration_ms=2000, amplitude=0.02)
        rest = rest.overlay(
            _sine_segment(freq_hz=440.0, duration_ms=2000, amplitude=0.02)
        )
        np.random.seed(11)
        hiss = _noise_segment(duration_ms=2000, amplitude=0.035)

        window = detect_noise_profile(tone + rest + hiss)

        assert window is not None
        assert window.start_ms >= 3000
        assert window.flatness > 0.8
        assert window.trial_db < 0.1

    def test_the_trial_guard_drops_a_window_that_would_cut_the_bed(self) -> None:
        """A candidate 10 dB under a noise bed would remove 2 dB of that bed.

        Without the ceiling the last bed window is the flattest in the
        shortlist and wins; the guard drops it as content-derived, and the
        quiet tail of the file - a floor 11 dB below the bed - is chosen.
        """
        np.random.seed(5)
        bed = _noise_segment(duration_ms=1000, amplitude=0.12)
        quiet = _noise_segment(duration_ms=1000, amplitude=0.03)

        window = detect_noise_profile(bed + quiet)

        assert window is not None
        assert window.start_ms >= 1000
        assert window.rms_dbfs < -29.0
        assert window.trial_db < 0.2

    def test_a_file_with_no_tame_candidate_keeps_the_flattest(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The documented fallback: no candidate meets the ceiling, none raises.

        A file of unbroken content has no floor to find, so the guard cannot be
        satisfied.  The detector keeps the flattest candidate and reports its
        reading rather than raising, which is what the docstring promises once
        the ceiling is unreachable.  The ceiling is lowered rather than relying
        on a fixture happening to produce an all-content shortlist, so the
        branch is exercised deterministically.
        """
        import noise_reduction.core.noise_reducer as reducer

        monkeypatch.setattr(reducer, "_PROFILE_TRIAL_MAX_DB", -1.0)
        np.random.seed(5)
        bed = _noise_segment(duration_ms=2000, amplitude=0.08)

        window = detect_noise_profile(bed)

        assert window is not None
        assert window.trial_db >= 0.0
        assert window.flatness > 0.5

    def test_a_file_too_short_to_measure_keeps_the_region(self) -> None:
        np.random.seed(3)
        assert detect_noise_profile(_noise_segment(duration_ms=200)) is None

    def test_the_window_describes_itself(self) -> None:
        window = NoiseWindow(
            start_ms=12400,
            end_ms=12800,
            rms_dbfs=-62.4,
            flatness=0.42,
            trial_db=0.84,
        )

        assert window.describe() == "auto 12.4-12.8 s at -62 dBFS, trial 0.8 dB"

    def test_auto_keeps_the_music_and_gates_the_floor(self) -> None:
        """Measured on the decoded segments: the default window was the defect."""
        audio = self._loud_then_quiet()
        auto = reduce_noise(audio, NoiseReductionParams(reduce_broadband=True))
        manual = reduce_noise(
            audio, NoiseReductionParams(reduce_broadband=True, profile_auto=False)
        )

        head_auto = self._rms(auto.audio[:800]) - self._rms(audio[:800])
        tail_auto = self._rms(auto.audio[800:]) - self._rms(audio[800:])
        head_manual = self._rms(manual.audio[:800]) - self._rms(audio[:800])

        assert auto.noise_window is not None
        # Measured on this file: auto 0.0 dB head / -4.1 dB tail,
        # manual -4.2 dB head / +1.9 dB tail.
        assert head_auto > -0.5  # the hot intro survives
        assert tail_auto < -3.0  # the real floor is gated
        assert head_manual < head_auto - 3.0  # first-500-ms profile eats it


class TestNoiseAnalysis:
    """The panel's Analyse action measures with the batch's own detectors.

    Read-only is the contract: it returns a report and nothing else.  The hum
    band and the profile window come from the same functions the run calls, so a
    preview cannot recommend a window the gate would not use.
    """

    def test_it_reports_hum_floor_and_a_recommended_region(self) -> None:
        hum = _sine_segment(freq_hz=50.0, duration_ms=2000, amplitude=0.3)
        np.random.seed(23)
        audio = hum.overlay(_noise_segment(duration_ms=2000, amplitude=0.01))

        analysis = analyse_noise(audio)

        assert analysis.hum is not None
        assert analysis.hum.fundamental_hz == 50
        assert analysis.window is not None
        assert analysis.noise_floor_dbfs == pytest.approx(analysis.window.rms_dbfs)
        report = analysis.describe("song.wav")
        assert "song.wav" in report
        assert "Hum: 50 Hz auto" in report
        assert "Noise floor:" in report
        assert f"{analysis.window.start_ms}-{analysis.window.end_ms} ms" in report
        assert "Recommended profile region: " in report

    def test_a_clean_file_reports_no_hum(self) -> None:
        """White noise is not hum, however far a high partial clears the floor.

        This seed measured 60 Hz order 6/7 at 9 and 7.6 dB before the detector
        required a fundamental or its octave; reporting a recommended 360 Hz
        notch on a clean file is the defect this locks.
        """
        np.random.seed(29)

        analysis = analyse_noise(_noise_segment(duration_ms=1000, amplitude=0.01))

        assert analysis.hum is None
        assert "Hum: none detected" in analysis.describe()

    def test_a_file_too_short_to_measure_says_so(self) -> None:
        np.random.seed(31)

        analysis = analyse_noise(_noise_segment(duration_ms=200, amplitude=0.01))

        assert analysis.window is None
        assert analysis.noise_floor_dbfs == pytest.approx(analysis.file_rms_dbfs)
        assert "too short to measure" in analysis.describe()


class TestGateMeasurement:
    """The gate reports what it removed and how much of the spectrum it touched.

    A gate that removes 20 dB from 2 % of the bins and one that thins every bin
    by 2 dB read the same in a single attenuation number, so the share is
    reported beside it.  Where hum also ran, the gate's own figure is measured
    on the audio the gate saw, not on the stage's totals.
    """

    def test_the_gate_measures_its_own_attenuation_and_share(self) -> None:
        np.random.seed(13)
        audio = _noise_segment(duration_ms=1000, amplitude=0.2)

        result = spectral_gate(audio, noise_start_ms=0, noise_end_ms=300)

        assert result.was_modified is True
        assert result.gate_attenuation_db is not None
        assert result.gate_attenuation_db > 0.5
        assert result.gated_bin_share is not None
        assert 0.2 < result.gated_bin_share < 1.0

    def test_silence_measures_a_zero_share(self) -> None:
        silence = AudioSegment.silent(duration=500, frame_rate=FS)

        result = spectral_gate(silence, noise_start_ms=0, noise_end_ms=300)

        assert result.was_modified is False
        assert result.gate_attenuation_db == 0.0
        assert result.gated_bin_share == 0.0

    def test_the_stage_keeps_the_gate_measurement_apart_from_hum(self) -> None:
        hum = _sine_segment(freq_hz=60.0, duration_ms=1500, amplitude=0.25)
        np.random.seed(19)
        audio = hum.overlay(_noise_segment(duration_ms=1500, amplitude=0.02))

        result = reduce_noise(
            audio, NoiseReductionParams(reduce_hum=True, reduce_broadband=True)
        )

        assert result.hum_profile is not None
        assert result.gate_attenuation_db is not None
        assert result.gated_bin_share is not None
        total = result.energy_before_db - result.energy_after_db
        assert total >= result.gate_attenuation_db - 0.1


class TestNeuralEngine:
    """The broadband half can run RNNoise instead of the STFT gate."""

    def test_the_spectral_gate_is_still_the_default(self) -> None:
        params = NoiseReductionParams()

        assert params.broadband_engine == "spectral"
        assert params.neural_amount == 1.0

    def test_the_neural_amount_defaults_to_the_shared_constant(self) -> None:
        """One default, declared where the model lives.

        Reusing ``DEFAULT_AMOUNT`` keeps the stage and the neural engine's
        engine in lockstep: a change there must reach this field, not leave two
        "defaults" that quietly disagree.
        """
        from noise_reduction.core.models import DEFAULT_AMOUNT

        assert NoiseReductionParams().neural_amount == DEFAULT_AMOUNT

    def test_the_spectral_engine_still_runs_the_gate_it_always_did(self) -> None:
        """Selecting the engine did not replace the gate; only its window moved.

        The spectral path is the one every existing preset relies on, so it is
        compared sample for sample against ``spectral_gate`` - called with the
        window the run itself reports - rather than merely "still attenuates
        something".  Detection decides where the floor is measured; it does not
        change what gating does with it.
        """
        np.random.seed(42)
        audio = _noise_segment(duration_ms=400)
        params = NoiseReductionParams(
            reduce_broadband=True,
            noise_start_ms=0,
            noise_end_ms=200,
            gate_threshold_db=6.0,
        )

        through_params = reduce_noise(audio, params)
        window = through_params.noise_window
        assert window is not None
        direct = spectral_gate(
            audio,
            noise_start_ms=window.start_ms,
            noise_end_ms=window.end_ms,
            gate_threshold_db=6.0,
        )

        assert through_params.was_modified is True
        assert np.array_equal(
            segment_to_numpy(through_params.audio)[0], segment_to_numpy(direct.audio)[0]
        )

    def test_a_manual_region_gates_exactly_that_region(self) -> None:
        """The override is the gate it was before detection existed."""
        np.random.seed(42)
        audio = _noise_segment(duration_ms=400)
        params = NoiseReductionParams(
            reduce_broadband=True,
            profile_auto=False,
            noise_start_ms=0,
            noise_end_ms=200,
            gate_threshold_db=6.0,
        )

        through_params = reduce_noise(audio, params)
        direct = spectral_gate(
            audio, noise_start_ms=0, noise_end_ms=200, gate_threshold_db=6.0
        )

        assert through_params.noise_window is None
        assert np.array_equal(
            segment_to_numpy(through_params.audio)[0], segment_to_numpy(direct.audio)[0]
        )

    def test_an_unused_neural_engine_imports_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A spectral run must never need the optional extra."""
        monkeypatch.setitem(sys.modules, "pyrnnoise", None)

        assert neural_dependency_reason(NoiseReductionParams()) is None
        result = reduce_noise(
            _noise_segment(duration_ms=400),
            NoiseReductionParams(reduce_broadband=True),
        )

        assert isinstance(result, NoiseReductionResult)

    def test_the_neural_engine_attenuates_the_measured_audio(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The fake model halves the signal, and the result measures that."""
        _install_fake_rnnoise(monkeypatch, gain=0.5)
        audio = _noise_segment(duration_ms=400, amplitude=0.2)

        result = reduce_noise(audio, _neural_params())

        assert result.was_modified is True
        before = np.asarray(segment_to_numpy(audio)[0], dtype=np.float64)
        after = np.asarray(segment_to_numpy(result.audio)[0], dtype=np.float64)
        rms_before = float(np.sqrt(np.mean(before**2)))
        rms_after = float(np.sqrt(np.mean(after**2)))
        assert rms_after == pytest.approx(rms_before * 0.5, rel=0.02)
        assert result.energy_after_db - result.energy_before_db == pytest.approx(
            -6.02, abs=0.3
        )

    def test_a_missing_model_is_a_named_dependency(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setitem(sys.modules, "pyrnnoise", None)
        params = _neural_params()

        assert neural_dependency_reason(params) is not None
        with pytest.raises(AudioMissingDependencyError) as excinfo:
            reduce_noise(_noise_segment(duration_ms=400), params)
        assert "pyrnnoise" in str(excinfo.value)

    def test_an_unknown_engine_is_refused(self) -> None:
        with pytest.raises(AudioConfigurationError) as excinfo:
            reduce_noise(
                _noise_segment(duration_ms=400),
                _neural_params(broadband_engine="magic"),
            )
        assert "broadband_engine" in str(excinfo.value)

    def test_a_source_wider_than_the_output_is_refused(self, tmp_path: Path) -> None:
        """The refusal names the file and the depth the file declares.

        pydub widens a 24-bit source to 32-bit samples, so the guard reads the
        file's own declaration - the reader REFINE's export pins the depth with.
        """
        source = tmp_path / "song.wav"
        _sine_segment(duration_ms=200).export(
            str(source), format="wav", parameters=["-c:a", "pcm_s24le"]
        )

        with pytest.raises(AudioConfigurationError) as excinfo:
            check_neural_bit_depth(
                AudioSegment.from_file(str(source)), _neural_params(), str(source)
            )
        message = str(excinfo.value)

        assert "song.wav" in message
        assert "24-bit" in message
        assert "16-bit" in message

    def test_a_source_with_no_path_still_reports_the_decoded_width(self) -> None:
        wide = _sine_segment(duration_ms=200).set_sample_width(4)

        with pytest.raises(AudioConfigurationError) as excinfo:
            check_neural_bit_depth(wide, _neural_params())

        assert "32-bit" in str(excinfo.value)

    def test_the_wide_source_runs_only_with_the_opt_in(self, tmp_path: Path) -> None:
        """A 16-bit source passes; a wider one needs the explicit opt-in.

        REFINE's export preserves the source's bit depth, so accepting the
        model's narrower output is a deliberate choice rather than a default:
        the refusal stands until the run asks for the downmix, and the guard
        then reports the depth it narrowed from so the report can name it.
        """
        wide = tmp_path / "wide.wav"
        _sine_segment(duration_ms=200).export(
            str(wide), format="wav", parameters=["-c:a", "pcm_s24le"]
        )
        decoded_wide = AudioSegment.from_file(str(wide))
        narrow = _sine_segment(duration_ms=200, sample_width=2)

        assert NoiseReductionParams().allow_16bit_output is False
        assert check_neural_bit_depth(narrow, _neural_params(), "a.flac") is None
        with pytest.raises(AudioConfigurationError):
            check_neural_bit_depth(decoded_wide, _neural_params(), str(wide))

        allowed = check_neural_bit_depth(
            decoded_wide, _neural_params(allow_16bit_output=True), str(wide)
        )

        assert allowed == 24
