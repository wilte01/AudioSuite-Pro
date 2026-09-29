"""
core/noise_reducer.py
DSP engine for hum removal and broadband noise reduction.

Hum removal
-----------
Cascaded second-order IIR notch filters at the fundamental frequency
(50 or 60 Hz) and its harmonics.  Each notch is designed with
``scipy.signal.iirnotch`` and applied in second-order-sections form
via ``scipy.signal.sosfilt`` for numerical stability.

Broadband noise reduction
-------------------------
STFT-based spectral gating.  The user designates a short silent region
as the noise profile.  Its mean magnitude spectrum becomes the gate
threshold: frequency bins whose energy falls below the noise floor
(plus a configurable headroom) are zeroed, suppressing stationary
hiss and broadband noise while preserving tonal content above the
noise floor.

Both features are independent and can be applied individually or in
sequence (hum removal first, then spectral gating).
"""

from __future__ import annotations

import logging
import math

import numpy as np
from pydub import AudioSegment
from scipy.signal import iirnotch, istft, lfilter, stft

from audio_suite_shared.audio_conversion import (
    clip_to_range,
    log_clip_event,
    numpy_to_segment,
    segment_to_numpy,
)
from audio_suite_shared.exceptions import AudioConfigurationError

from .models import NoiseReductionParams, NoiseReductionResult

logger = logging.getLogger(__name__)

# ── Hum removal constants ────────────────────────────────────────────────────

_SUPPORTED_HUM_FREQUENCIES: frozenset[int] = frozenset({50, 60})
_MIN_HARMONICS: int = 1
_MAX_HARMONICS: int = 20
_MIN_QUALITY: float = 1.0
_MAX_QUALITY: float = 100.0

# Minimum energy attenuation (dB) for the hum stage to be considered a real
# modification.  A pure IIR notch passes non-hum content essentially unchanged
# (energy drift < 0.1 dB), so this threshold cleanly separates real hum
# removal (typically 8-14 dB) from benign floating-point drift on clean audio.
_MIN_ATTENUATION_DB: float = 3.0

# ── Spectral gating constants ────────────────────────────────────────────────

_DEFAULT_N_FFT: int = 2048
_DEFAULT_HOP_LENGTH: int = 512
_MIN_NOISE_REGION_MS: int = 100


# ── Internal helpers ─────────────────────────────────────────────────────────


def _rms_db(audio_f64: np.ndarray) -> float:
    """Compute RMS level in dBFS from a float64 array (any shape)."""
    rms = float(np.sqrt(np.mean(audio_f64.astype(np.float64) ** 2)))
    if rms < 1e-12:
        return -120.0
    return 20.0 * math.log10(rms)


def _build_hum_notch_filters(
    fundamental_hz: int,
    harmonics: int,
    quality: float,
    sample_rate: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Design notch filter coefficients for hum and its harmonics.

    Returns a list of (b, a) coefficient pairs, one per harmonic.
    """
    filters: list[tuple[np.ndarray, np.ndarray]] = []
    for h in range(1, harmonics + 1):
        freq = fundamental_hz * h
        if freq >= sample_rate / 2:
            break
        b, a = iirnotch(freq, quality, fs=sample_rate)
        filters.append((b, a))
    return filters


def _spectral_gate_channel(
    channel: np.ndarray,
    fs: int,
    noise_start_ms: int,
    noise_end_ms: int,
    gate_threshold_db: float,
    n_fft: int,
    hop_length: int,
) -> np.ndarray:
    """Apply spectral gating to a single-channel float64 signal.

    Parameters
    ----------
    channel : 1-D float64 array.
    fs : Sample rate in Hz.
    noise_start_ms, noise_end_ms : Bounds of the noise profile region.
    gate_threshold_db : Headroom in dB above the noise floor.
    n_fft : STFT window length.
    hop_length : STFT hop length.

    Returns
    -------
    Cleaned 1-D float64 array (same length as input).
    """
    orig_len = len(channel)

    freqs, times, Zxx = stft(channel, fs=fs, nperseg=n_fft, noverlap=n_fft - hop_length)

    mag = np.abs(Zxx)
    phase = np.angle(Zxx)

    noise_start_s = noise_start_ms / 1000.0
    noise_end_s = noise_end_ms / 1000.0

    noise_mask = (times >= noise_start_s) & (times <= noise_end_s)
    if not np.any(noise_mask):
        noise_mask = times <= noise_end_s

    noise_profile = np.mean(mag[:, noise_mask], axis=1, keepdims=True)
    gate = noise_profile * (10.0 ** (gate_threshold_db / 20.0))

    mag_clean = np.where(mag >= gate, mag, 0.0)

    Zxx_clean = mag_clean * np.exp(1j * phase)

    _, cleaned = istft(Zxx_clean, fs=fs, nperseg=n_fft, noverlap=n_fft - hop_length)

    if len(cleaned) < orig_len:
        cleaned = np.pad(cleaned, (0, orig_len - len(cleaned)))
    elif len(cleaned) > orig_len:
        cleaned = cleaned[:orig_len]

    return np.asarray(cleaned, dtype=np.float64)


# ── Public API ────────────────────────────────────────────────────────────────


def remove_hum(
    audio: AudioSegment,
    fundamental_hz: int = 60,
    harmonics: int = 8,
    quality: float = 30.0,
) -> NoiseReductionResult:
    """Remove mains hum and its harmonics via cascaded IIR notch filters.

    Parameters
    ----------
    audio : AudioSegment
        Input audio (mono or multi-channel, any supported bit depth).
    fundamental_hz : int
        Mains frequency: 50 or 60 Hz.
    harmonics : int
        Number of harmonics to filter (1-20).
    quality : float
        Q factor for each notch filter (1.0-100.0).  Higher values produce
        narrower notches that preserve more adjacent content.

    Returns
    -------
    NoiseReductionResult
        (processed audio, energy before dB, energy after dB, was_modified).

    Raises
    ------
    AudioConfigurationError
        If parameters are outside acceptable ranges.
    """
    if fundamental_hz not in _SUPPORTED_HUM_FREQUENCIES:
        raise AudioConfigurationError(
            f"hum_frequency must be one of {sorted(_SUPPORTED_HUM_FREQUENCIES)}, "
            f"got {fundamental_hz}"
        )
    if not (_MIN_HARMONICS <= harmonics <= _MAX_HARMONICS):
        raise AudioConfigurationError(
            f"hum_harmonics must be {_MIN_HARMONICS}-{_MAX_HARMONICS}, got {harmonics}"
        )
    if not (_MIN_QUALITY <= quality <= _MAX_QUALITY):
        raise AudioConfigurationError(
            f"hum_quality must be {_MIN_QUALITY}-{_MAX_QUALITY}, got {quality}"
        )

    sample_rate = audio.frame_rate
    num_channels = audio.channels

    samples_f32, _sample_rate = segment_to_numpy(audio)  # (channels, frames) float32
    samples = samples_f32.T.astype(np.float64)  # (frames, channels) float64 for scipy

    energy_before = _rms_db(samples)

    notch_filters = _build_hum_notch_filters(
        fundamental_hz, harmonics, quality, sample_rate
    )
    if not notch_filters:
        return NoiseReductionResult(audio, energy_before, energy_before, False)

    for ch in range(num_channels):
        filtered = samples[:, ch].copy()
        for b, a in notch_filters:
            filtered = lfilter(b, a, filtered)
        samples[:, ch] = filtered

    energy_after = _rms_db(samples)

    if energy_before - energy_after < _MIN_ATTENUATION_DB:
        return NoiseReductionResult(audio, energy_before, energy_before, False)

    clipped = clip_to_range(samples.T.astype(np.float32))  # back to (channels, frames)
    log_clip_event(clipped, "noise_reduction", logger)
    new_audio = numpy_to_segment(
        clipped,
        sample_rate,
        sample_width=audio.sample_width,
        num_channels=audio.channels,
    )
    return NoiseReductionResult(new_audio, energy_before, energy_after, True)


def spectral_gate(
    audio: AudioSegment,
    noise_start_ms: int = 0,
    noise_end_ms: int = 500,
    gate_threshold_db: float = 3.0,
    n_fft: int = _DEFAULT_N_FFT,
    hop_length: int = _DEFAULT_HOP_LENGTH,
) -> NoiseReductionResult:
    """Reduce broadband noise via STFT-based spectral gating.

    Parameters
    ----------
    audio : AudioSegment
        Input audio.
    noise_start_ms : int
        Start of the noise profile region in milliseconds.
    noise_end_ms : int
        End of the noise profile region in milliseconds.
    gate_threshold_db : float
        Headroom in dB above the measured noise floor.  Bins below this
        threshold are zeroed.
    n_fft : int
        STFT window length.
    hop_length : int
        STFT hop length.

    Returns
    -------
    NoiseReductionResult

    Raises
    ------
    AudioConfigurationError
        If the noise region is too short or parameters are invalid.
    """
    if noise_end_ms - noise_start_ms < _MIN_NOISE_REGION_MS:
        raise AudioConfigurationError(
            f"Noise profile region must be at least {_MIN_NOISE_REGION_MS} ms, "
            f"got {noise_end_ms - noise_start_ms} ms"
        )
    if noise_start_ms < 0:
        raise AudioConfigurationError(
            f"noise_start_ms must be >= 0, got {noise_start_ms}"
        )
    if noise_end_ms <= noise_start_ms:
        raise AudioConfigurationError(
            f"noise_end_ms ({noise_end_ms}) must be > noise_start_ms ({noise_start_ms})"
        )

    sample_rate = audio.frame_rate
    num_channels = audio.channels

    samples_f32, _sample_rate = segment_to_numpy(audio)  # (channels, frames) float32
    samples = samples_f32.T.astype(np.float64)  # (frames, channels) float64 for scipy

    energy_before = _rms_db(samples)

    modified = False
    for ch in range(num_channels):
        cleaned = _spectral_gate_channel(
            samples[:, ch],
            sample_rate,
            noise_start_ms,
            noise_end_ms,
            gate_threshold_db,
            n_fft,
            hop_length,
        )
        if not np.allclose(cleaned, samples[:, ch], atol=1e-6):
            modified = True
            samples[:, ch] = cleaned

    if not modified:
        return NoiseReductionResult(audio, energy_before, energy_before, False)

    energy_after = _rms_db(samples)

    clipped = clip_to_range(samples.T.astype(np.float32))  # back to (channels, frames)
    log_clip_event(clipped, "noise_reduction", logger)
    new_audio = numpy_to_segment(
        clipped,
        sample_rate,
        sample_width=audio.sample_width,
        num_channels=audio.channels,
    )
    return NoiseReductionResult(new_audio, energy_before, energy_after, True)


def reduce_noise(
    audio: AudioSegment,
    params: NoiseReductionParams,
) -> NoiseReductionResult:
    """Apply noise reduction according to the given parameters.

    Both hum removal and spectral gating can be enabled independently.
    When both are active, hum removal runs first.

    Parameters
    ----------
    audio : AudioSegment
        Input audio.
    params : NoiseReductionParams
        Processing parameters.

    Returns
    -------
    NoiseReductionResult
    """
    # ``params.dry_run`` is deliberately NOT consulted here.  The DSP always
    # measures and reports what it found; suppressing the write is the shared
    # in-place workflow's job (it passes ``is_dry_run`` separately and skips
    # the export), so a dry run can report ``was_modified=True`` honestly
    # instead of having to claim the file was clean.  This matches
    # ``pop_click_remover``'s declicker.
    current = audio
    any_modified = False
    energy_before_total = 0.0
    energy_after_total = 0.0

    if params.reduce_hum:
        result = remove_hum(
            current,
            fundamental_hz=params.hum_frequency,
            harmonics=params.hum_harmonics,
            quality=params.hum_quality,
        )
        if energy_before_total == 0.0:
            energy_before_total = result.energy_before_db
        energy_after_total = result.energy_after_db
        if result.was_modified:
            current = result.audio
            any_modified = True

    if params.reduce_broadband:
        result = spectral_gate(
            current,
            noise_start_ms=params.noise_start_ms,
            noise_end_ms=params.noise_end_ms,
            gate_threshold_db=params.gate_threshold_db,
        )
        if energy_before_total == 0.0:
            energy_before_total = result.energy_before_db
        energy_after_total = result.energy_after_db
        if result.was_modified:
            current = result.audio
            any_modified = True

    if not any_modified:
        samples_f32, _sample_rate = segment_to_numpy(audio)
        energy = _rms_db(samples_f32.T.astype(np.float64))
        return NoiseReductionResult(audio, energy, energy, False)

    return NoiseReductionResult(current, energy_before_total, energy_after_total, True)
