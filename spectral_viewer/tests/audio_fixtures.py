"""Synthetic WAV fixtures shared by the Spectral Viewer tests.

Written with the stdlib ``wave`` module rather than pydub/ffmpeg so the signal
is exactly known (a pure tone at a stated frequency and level) and the tests can
assert where the energy landed.

Changed in 1.3.0: initial version.
"""

from __future__ import annotations

import math
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 22050


def write_tone_wav(
    path: Path,
    *,
    frequency: float = 440.0,
    seconds: float = 1.0,
    amplitude: float = 0.5,
    sample_rate: int = SAMPLE_RATE,
    silent: bool = False,
) -> Path:
    """Write a mono 16-bit WAV holding a pure tone (or digital silence).

    Args:
        path: Destination path; parent directories must exist.
        frequency: Tone frequency in Hz.
        seconds: Length in seconds.
        amplitude: Peak level as a fraction of full scale (0.5 = -6 dBFS).
        sample_rate: Sample rate in Hz.
        silent: Write zeros instead of a tone.

    Returns:
        The written path.
    """
    frames = int(sample_rate * seconds)
    if silent:
        samples = np.zeros(frames, dtype=np.float64)
    else:
        time_axis = np.arange(frames) / sample_rate
        samples = amplitude * np.sin(2.0 * math.pi * frequency * time_axis)
    # 16-bit PCM stores full scale as 32767; scaling here is what makes the
    # tone audible at all (an unscaled 0.5 truncates to zero).
    pcm = np.clip(samples * 32767.0, -32768, 32767).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(pcm.tobytes())
    return path
