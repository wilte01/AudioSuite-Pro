"""
audio_conversion.py — Shared audio format conversion and clipping protection.

Canonical data representation:
  - float32, range [-1.0, 1.0], shape (channels, frames)
  - Matches pedalboard and FFmpeg conventions
  - float64 used only inside scipy/numpy DSP (upcast at tool boundary)

All DSP tools should import from this module rather than implementing
their own int→float decode or clip-to-int logic.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt
from pydub import AudioSegment


def segment_to_numpy(audio: AudioSegment) -> tuple[np.ndarray, int]:
    """
    Convert a pydub AudioSegment to a float32 numpy array.

    Returns
    -------
    audio_f32 : np.ndarray, shape (channels, frames), dtype float32, range [-1, 1]
    sample_rate : int
    """
    sample_width = audio.sample_width  # bytes per sample (2 = 16-bit)
    num_channels = audio.channels
    sample_rate = audio.frame_rate

    # Raw interleaved integer samples
    raw = np.frombuffer(audio.raw_data, dtype=int_dtype(sample_width))

    # De-interleave: (frames * channels,) → (frames, channels) → (channels, frames)
    frames = raw.reshape(-1, num_channels).T.astype(np.float32)

    # Normalise to [-1.0, 1.0]
    scale = float(2 ** (8 * sample_width - 1))
    frames /= scale

    return frames, sample_rate


def numpy_to_segment(
    audio_f32: np.ndarray,
    sample_rate: int,
    sample_width: int = 2,  # bytes; 2 = 16-bit, keep source depth
    num_channels: int = 2,
) -> AudioSegment:
    """
    Convert a float32 numpy array back to a pydub AudioSegment.

    Parameters
    ----------
    audio_f32    : shape (channels, frames), dtype float32, range [-1, 1]
    sample_rate  : sample rate in Hz
    sample_width : output bit depth in bytes (match source file)
    num_channels : number of output channels
    """
    scale = float(2 ** (8 * sample_width - 1))
    dtype = int_dtype(sample_width)
    min_val, max_val = clip_bounds(sample_width)

    # Channels-first → interleaved integers, clamped to prevent overflow
    interleaved = audio_f32.T  # (frames, channels)
    scaled = interleaved * scale
    clipped = np.clip(scaled, min_val, max_val)
    int_samples = np.round(clipped).astype(np.int32).flatten()

    if sample_width == 3:
        raw_bytes = pack_24bit(int_samples)
    else:
        raw_bytes = int_samples.astype(dtype).tobytes()

    return AudioSegment(
        data=raw_bytes,
        sample_width=sample_width,
        frame_rate=sample_rate,
        channels=num_channels,
    )


def load_as_float32(audio: AudioSegment) -> tuple[np.ndarray, int]:
    """
    Alias for :func:`segment_to_numpy`.

    Semantically clearer for callers that only need the normalized float32
    array and do not care about the pydub conversion path.
    """
    return segment_to_numpy(audio)


def clip_to_range(
    audio: npt.NDArray[np.floating[Any]], hard_limit: float = 1.0
) -> npt.NDArray[np.floating[Any]]:
    """Hard-clip a float array to ``[-hard_limit, hard_limit]``.

    Returns a NEW array; the input is never mutated.

    Parameters
    ----------
    audio : np.ndarray
        Float array in any shape.
    hard_limit : float
        Symmetric absolute bound to clip to (default 1.0).

    Returns
    -------
    np.ndarray
        A new array clipped to the requested range.
    """
    clipped: npt.NDArray[np.floating[Any]] = np.clip(
        audio, -hard_limit, hard_limit
    ).astype(audio.dtype, copy=True)
    return clipped


def measure_peak_db(audio: npt.NDArray[np.floating[Any]]) -> float:
    """Return the peak level in dBFS of a normalized float array.

    Silence (peak of zero) is reported as -120 dBFS.
    """
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    if peak < 1e-12:
        return -120.0
    return 20.0 * float(np.log10(peak))


def measure_rms_db(audio: npt.NDArray[np.floating[Any]]) -> float:
    """Return the RMS level in dBFS of a normalized float array.

    Silence (RMS of zero) is reported as -120 dBFS.
    """
    rms = float(np.sqrt(np.mean(audio**2))) if audio.size else 0.0
    if rms < 1e-12:
        return -120.0
    return 20.0 * float(np.log10(rms))


def check_headroom(
    audio: npt.NDArray[np.floating[Any]], target_db: float = -0.5
) -> tuple[bool, float]:
    """Check whether the peak of *audio* is at or below *target_db* dBFS.

    Returns
    -------
    tuple[bool, float]
        ``(ok, actual_peak_db)`` where *ok* is True when the measured peak is
        at or below the target, and *actual_peak_db* is the measured peak.
    """
    peak_db = measure_peak_db(audio)
    return peak_db <= target_db, peak_db


def log_clip_event(
    audio: npt.NDArray[np.floating[Any]], stage_name: str, logger: Any
) -> None:
    """Log a warning if any sample in *audio* exceeds ±1.0.

    Call AFTER DSP and BEFORE int conversion.
    """
    if audio.size and bool(np.any(np.abs(audio) > 1.0)):
        peak_db = measure_peak_db(audio)
        logger.warning(
            "[%s] Clipping detected: peak at %.1f dBFS (exceeds full scale)",
            stage_name,
            peak_db,
        )


_INT_WIDTHS: dict[int, type[np.integer[Any]]] = {
    1: np.int8,
    2: np.int16,
    3: np.int32,
    4: np.int32,
}


def int_dtype(sample_width: int) -> type[np.integer[Any]]:
    """Return the numpy integer dtype for a pydub sample_width (bytes)."""
    return _INT_WIDTHS.get(sample_width, np.int32)


def clip_bounds(sample_width: int) -> tuple[int, int]:
    """Return (min, max) clip bounds for the given sample width in bytes."""
    if sample_width == 3:
        return -(2**23), 2**23 - 1
    return int(np.iinfo(int_dtype(sample_width)).min), int(
        np.iinfo(int_dtype(sample_width)).max
    )


def pack_24bit(int32_array: np.ndarray) -> bytes:
    """Pack an int32 array into 3-bytes-per-sample little-endian PCM."""
    arr = np.clip(int32_array, -(2**23), 2**23 - 1).astype(np.int32)
    lo = (arr & 0xFF).astype(np.uint8)
    mid = ((arr >> 8) & 0xFF).astype(np.uint8)
    hi = ((arr >> 16) & 0xFF).astype(np.uint8)
    interleaved = np.column_stack([lo, mid, hi]).flatten()
    return interleaved.tobytes()
