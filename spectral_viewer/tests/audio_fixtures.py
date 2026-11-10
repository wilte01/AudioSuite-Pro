"""Synthetic WAV fixtures shared by the Spectral Viewer tests.

Written with the stdlib ``wave`` module rather than pydub/ffmpeg so the signal
is exactly known (a pure tone at a stated frequency and level) and the tests can
assert where the energy landed.

Changed in 1.3.0: initial version.

Changed in 2.6.0: ``write_two_tone_wav`` adds a 24-bit fixture whose quiet tone
is -100 dB below the loud one, so a test can prove the spectrogram reports a
level below the default 80 dB colour range instead of clamping it.
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


def write_two_tone_wav(
    path: Path,
    *,
    loud_frequency: float = 1000.0,
    loud_amplitude: float = 0.5,
    quiet_frequency: float = 8000.0,
    quiet_amplitude: float = 5e-6,
    seconds: float = 2.0,
    sample_rate: int = SAMPLE_RATE,
) -> Path:
    """Write a mono 24-bit WAV holding a loud tone and a very quiet one.

    24-bit PCM is required: the quiet tone is 5e-6 of full scale (-106 dBFS,
    -100 dB relative to the 0.5 tone), which 16-bit cannot represent at all.
    The pair is what lets a test prove the spectrogram does not clip its dB
    values at the default 80 dB colour range.

    Args:
        path: Destination path; parent directories must exist.
        loud_frequency: Loud tone frequency in Hz.
        loud_amplitude: Loud tone peak as a fraction of full scale.
        quiet_frequency: Quiet tone frequency in Hz.
        quiet_amplitude: Quiet tone peak as a fraction of full scale.
        seconds: Length in seconds.
        sample_rate: Sample rate in Hz.

    Returns:
        The written path.
    """
    frames = int(sample_rate * seconds)
    time_axis = np.arange(frames) / sample_rate
    samples = loud_amplitude * np.sin(2.0 * math.pi * loud_frequency * time_axis)
    samples = samples + quiet_amplitude * np.sin(
        2.0 * math.pi * quiet_frequency * time_axis
    )
    ints = np.clip(np.rint(samples * 8_388_607.0), -8_388_608, 8_388_607).astype(
        np.int32
    )
    # Two's complement in 24 bits: ``& 0xFFFFFF`` turns a negative sample into
    # the little-endian three-byte form WAV expects.
    unsigned = ints.astype(np.uint32) & np.uint32(0xFFFFFF)
    packed = np.empty(frames * 3, dtype=np.uint8)
    packed[0::3] = (unsigned & np.uint32(0xFF)).astype(np.uint8)
    packed[1::3] = ((unsigned >> np.uint32(8)) & np.uint32(0xFF)).astype(np.uint8)
    packed[2::3] = ((unsigned >> np.uint32(16)) & np.uint32(0xFF)).astype(np.uint8)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(3)
        handle.setframerate(sample_rate)
        handle.writeframes(packed.tobytes())
    return path
