"""
analysis_loader.py — Shared audio loading for signal-analysis tools.

Part of audio_suite_shared. Provides a single consistent path for tools
(BPM analyser, key detector, mood analyser) to decode an audio file into a
mono, 64-bit float time series suitable for DSP, plus a silence / too-short
guard so analysis engines never receive degenerate input.

Decoding uses librosa (SoundFile-backed; on librosa <= 0.11 a corrupt
container can additionally fall back to audioread and decode to an empty
signal at ``sr == 0``, which the guard below rejects — librosa >= 1.0 removed
that fallback and raises the soundfile error instead). Samples are always
upcast to ``numpy.float64`` to avoid quantisation noise accumulation during
feature extraction.
"""

from __future__ import annotations

import logging

import numpy as np
import numpy.typing as npt

from .exceptions import AudioAnalysisError, AudioCodecError, map_to_audio_error

logger = logging.getLogger(f"audio_suite.{__name__}")

# Below this duration (seconds) the audio is too short for meaningful
# analysis — beat tracking and pitch-class correlation are undefined.
MIN_ANALYSIS_SECONDS = 0.5

# Fraction of full-scale that counts as "effectively silent" (~ -60 dBFS).
SILENCE_RMS_THRESHOLD = 1.0e-3


def load_analysis_audio(
    file_path: str, max_duration: int = 90, *, min_seconds: float = MIN_ANALYSIS_SECONDS
) -> tuple[npt.NDArray[np.float64], int]:
    """Decode an audio file into a mono float64 signal ready for analysis.

    Args:
        file_path:    Path to the audio file.
        max_duration: Cap on the decoded length (seconds), so slow tools
                      analyse a bounded window of each track. A positive
                      value truncates; ``0`` disables the cap.
        min_seconds:  Minimum usable audio duration. Shorter signals raise
                      AudioAnalysisError via ``check_min_duration``.

    Returns:
        Two-tuple ``(y, sr)`` where *y* is a mono float64 array in the
        range [-1, 1] and *sr* is the native sample rate in Hz.

    Raises:
        AudioCodecError:   The file cannot be decoded (unsupported codec or
                           corrupted container).
        AudioAnalysisError: The decoded signal is shorter than *min_seconds*.
    """
    import librosa

    try:
        if max_duration > 0:
            y_f32: npt.NDArray[np.float32]
            sample_rate: int | float
            y_f32, sample_rate = librosa.load(
                file_path, duration=max_duration, mono=True, sr=None
            )
        else:
            y_f32, sample_rate = librosa.load(file_path, mono=True, sr=None)
    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": file_path, "operation": "load_analysis_audio"}
        )
        logger.error(
            "[%s] failed to decode '%s': %s",
            type(mapped).__name__,
            file_path,
            mapped,
            exc_info=True,
        )
        raise AudioCodecError(
            f"Could not decode audio file '{file_path}'.",
            context={"file": file_path},
        ) from exc

    sr = int(sample_rate)
    y: npt.NDArray[np.float64] = y_f32.astype(np.float64)
    check_min_duration(y, sr, min_seconds=min_seconds)
    return y, sr


def check_min_duration(
    y: npt.NDArray[np.float64], sr: int, *, min_seconds: float = MIN_ANALYSIS_SECONDS
) -> None:
    """Raise if the signal is too short for meaningful analysis.

    Args:
        y:           Audio signal (mono float64).
        sr:          Sample rate in Hz.
        min_seconds: Minimum acceptable duration.

    Raises:
        AudioAnalysisError: If ``len(y) / sr < min_seconds``, or if the decoder
            reported a non-positive sample rate (a corrupt container can decode
            to an empty signal with ``sr == 0``).
    """
    if sr <= 0 or len(y) / sr < min_seconds:
        # A corrupt container can yield an empty signal with sr == 0, so the
        # duration is only computable once the rate is known to be positive.
        duration = len(y) / sr if sr > 0 else 0.0
        raise AudioAnalysisError(
            f"Audio is too short to analyse ({duration:.2f}s).",
            context={"min_seconds": min_seconds},
        )


def rms_energy_db(y: npt.NDArray[np.float64]) -> float:
    """Return the root-mean-square energy of a signal in dBFS.

    Args:
        y: Audio signal (mono float64).

    Returns:
        RMS level relative to full scale, e.g. ``-23.4``. Pure digital
        silence returns approximately ``-240`` (the epsilon floor).
    """
    if len(y) == 0:
        return -240.0
    rms: float = float(np.sqrt(np.mean(np.square(y), dtype=np.float64)))
    if rms <= 0.0:
        return -240.0
    return 20.0 * float(np.log10(rms))


def is_effectively_silent(y: npt.NDArray[np.float64]) -> bool:
    """Return True when the signal carries no perceptible energy.

    The check is against the global RMS level (~ -60 dBFS), not per-window
    energy, so it only rejects genuinely empty audio rather than sparse
    material with loud transients.

    Args:
        y: Audio signal (mono float64).

    Returns:
        True for a near-silent signal; False otherwise.
    """
    threshold_db: float = 20.0 * float(np.log10(SILENCE_RMS_THRESHOLD))
    return rms_energy_db(y) < threshold_db
