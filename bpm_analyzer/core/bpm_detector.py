"""
bpm_detector.py
Pure audio analysis logic — no tkinter dependencies.
Accepts plain Python values; returns plain Python values.
"""

from __future__ import annotations

import logging

import librosa
import numpy as np
import numpy.typing as npt

from audio_suite_shared.exceptions import map_to_audio_error

logger = logging.getLogger(__name__)


class BPMDetectionError(Exception):
    """Raised when BPM detection fails for any reason (IO, corrupt audio,
    librosa error)."""


def detect_bpm(
    file_path: str,
    max_duration: int = 90,
    min_bpm: int = 75,
    max_bpm: int = 175,
) -> int:
    """
    Detect the BPM of an audio file using librosa beat tracking.

    Audio is loaded as 64-bit float (np.float64) for internal processing
    to prevent quantization noise accumulation.

    Args:
        file_path:    Absolute path to the audio file.
        max_duration: Maximum seconds of audio to analyse
        (trade-off: speed vs accuracy).
        min_bpm:      Lower bound for the returned BPM value.
        max_bpm:      Upper bound for the returned BPM value.

    Returns:
        Detected BPM rounded to the nearest integer, constrained to [min_bpm, max_bpm].

    Raises:
        BPMDetectionError: Wraps any librosa / IO error with a descriptive message.
                           The original exception is available as __cause__.
    """
    try:
        # Load as float32 (librosa default) then upcast to float64 for DSP precision.
        y_f32: npt.NDArray[np.float32]
        y_f32, sr = librosa.load(file_path, duration=max_duration, mono=True)
        y: npt.NDArray[np.float64] = y_f32.astype(np.float64)

        logger.debug(
            "Loaded '%s': %d samples @ %d Hz (%.1f s)",
            file_path,
            len(y),
            sr,
            len(y) / sr,
        )

        tempo_raw, _ = librosa.beat.beat_track(y=y, sr=sr)

        # librosa may return a numpy array; normalise to a scalar float.
        tempo: float
        if isinstance(tempo_raw, np.ndarray):
            tempo = float(tempo_raw[0]) if len(tempo_raw) > 0 else 120.0
        else:
            tempo = float(tempo_raw)

        logger.debug("Raw tempo estimate for '%s': %.2f BPM", file_path, tempo)

        # A non-positive tempo (e.g. digital silence, or audio with no
        # detectable beat) can never be doubled into range — doubling zero
        # stays zero. Skip octave correction entirely so the hard clamp
        # below can resolve it; otherwise the loop never terminates.
        if tempo > 0:
            # Octave-correct: double/halve until inside the requested range.
            while tempo < min_bpm and tempo * 2 <= max_bpm:
                tempo *= 2
            while tempo > max_bpm and tempo / 2 >= min_bpm:
                tempo /= 2

        # Hard clamp as a final safety net.
        tempo = max(float(min_bpm), min(float(max_bpm), tempo))
        result: int = round(tempo)

        logger.info("BPM detected for '%s': %d", file_path, result)
        return result

    except Exception as exc:
        mapped = map_to_audio_error(
            exc, context={"file": file_path, "operation": "detect_bpm"}
        )
        logger.error(
            "[%s] BPM detection failed for '%s': %s",
            type(mapped).__name__,
            file_path,
            mapped,
            exc_info=True,
        )
        raise BPMDetectionError(
            f"BPM detection failed for '{file_path}': {exc}"
        ) from exc
