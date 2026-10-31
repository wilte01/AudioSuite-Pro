"""Shared audio builders and measurements for the restoration suite.

Every number this suite asserts is measured on the audio itself -- a windowed
FFT for harmonic distortion, the segment's own peak for level -- because a
declipper that reports success while making the audio worse is the failure this
item exists to catch (``AGENTS.md``, *Defects and failing checks*).

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pytest
from pydub import AudioSegment

from audio_suite_shared.audio_conversion import numpy_to_segment

#: Everything is built at the suite's own working rate.
SR = 44100

#: The test tone.  One kilohertz puts twenty harmonics below Nyquist at 44.1 kHz,
#: so the distortion floor is measured on the same terms a listener hears.
F0 = 1000.0


def sine(amplitude: float, seconds: float = 1.0) -> npt.NDArray[np.float64]:
    """Return a mono sine at :data:`F0`.

    Args:
        amplitude: Peak amplitude in ``[-1, 1]``.
        seconds: Length in seconds.

    Returns:
        The waveform.
    """
    t = np.arange(int(SR * seconds)) / SR
    return amplitude * np.sin(2 * np.pi * F0 * t)


def to_segment(mono: npt.NDArray[np.float64], sample_width: int = 2) -> AudioSegment:
    """Wrap a mono waveform as a stereo segment.

    Args:
        mono: The waveform.
        sample_width: Output bit depth in bytes (2 = 16-bit, 3 = 24-bit).

    Returns:
        The segment.
    """
    frames = np.vstack([mono, mono]).astype(np.float32)
    return numpy_to_segment(frames, SR, sample_width=sample_width, num_channels=2)


def thd_db(mono: npt.NDArray[np.float64], harmonics: int = 20) -> float:
    """Return the harmonic-to-fundamental energy ratio in dB.

    Args:
        mono: One channel of the signal.
        harmonics: How many harmonics above the fundamental to sum.

    Returns:
        ``10·log10(Σ harmonics² / fundamental²)``; very negative for a clean
        sine, around ``-20 dB`` for a hard-clipped one.
    """
    window = np.hanning(mono.size)
    spectrum = np.abs(np.fft.rfft(mono * window))
    freqs = np.fft.rfftfreq(mono.size, 1.0 / SR)
    fundamental = float(spectrum[np.argmin(np.abs(freqs - F0))])
    energy = 0.0
    for k in range(2, harmonics + 1):
        if k * F0 >= SR / 2:
            break
        energy += float(spectrum[np.argmin(np.abs(freqs - k * F0))]) ** 2
    return 10 * np.log10(energy / (fundamental**2) + 1e-20)


def peak(mono: npt.NDArray[np.float64]) -> float:
    """Return the waveform's absolute peak.

    Args:
        mono: One channel.

    Returns:
        The peak magnitude.
    """
    return float(np.max(np.abs(mono)))


def channel(segment: AudioSegment) -> npt.NDArray[np.float64]:
    """Return one channel of *segment* as floats.

    Args:
        segment: Any decoded audio.

    Returns:
        The left channel, normalised to ``[-1, 1]``.
    """
    from audio_suite_shared.audio_conversion import segment_to_numpy

    decoded, _rate = segment_to_numpy(segment)
    return decoded[0].astype(np.float64)


@pytest.fixture()
def clipped_pair() -> tuple[npt.NDArray[np.float64], AudioSegment]:
    """Return the known-clipped reference: the original and the clipped take.

    A ``-0.1 dBFS`` sine squeezed through a ``0.8`` ceiling.  The ceiling is
    deliberately *not* full scale, which is the case a detector comparing
    against ``1.0`` would miss.

    Returns:
        ``(unclipped, clipped_segment)``.
    """
    original = sine(0.9886)
    clipped = np.clip(original, -0.8, 0.8)
    return original, to_segment(clipped)
