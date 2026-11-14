"""dsp_time_pitch.py — tempo (time-stretch) and pitch transforms.

One implementation of each transform, over a decoded signal: librosa's phase
vocoder.  A stretch changes the length and leaves the pitch where it was; a
shift moves the pitch and leaves the length where it was.  Both functions
report the length they actually produced, so a caller never recomputes a
duration from the request it made.

Why librosa and not pedalboard: both are dependencies, and both were measured
on the acceptance fixture (a 1.000 s 440 Hz tone).  ``librosa.effects
.time_stretch(rate=1.25)`` returned 0.800 s at 440.0 Hz (0.0 cents) and
``librosa.effects.pitch_shift(n_steps=12)`` returned 1.000 s at 880.0 Hz
(0.0 cents); ``pedalboard.time_stretch`` returned the same length and pitch but
returns a ``(1, n)`` array for a mono input and is the same transform, so
keeping it would be a second implementation of one capability.  The choice and
its numbers are recorded in the plan's Decision Log (D-29).

The sample rate is the *file's own* rate, never the analysis rate: these
functions change the material, so resampling it to 22 050 Hz first would be an
unrequested conversion of the user's audio.

Changed in 2.7.0: new module
(PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
import numpy.typing as npt

from .exceptions import AudioConfigValueError

logger = logging.getLogger(f"audio_suite.{__name__}")

#: Slowest and fastest stretch the tool offers.  Outside this band the phase
#: vocoder's artefacts dominate the material, so a setting is refused rather
#: than rendered into a file nobody asked for.
MIN_RATE = 0.25
MAX_RATE = 4.0

#: Widest shift the tool offers, in semitones (two octaves either way).
MIN_SEMITONES = -24.0
MAX_SEMITONES = 24.0


@dataclass(frozen=True)
class TimePitchResult:
    """What one transform produced.

    Attributes:
        audio: The processed signal, ``(n,)`` mono or ``(channels, n)``, float32
            in the range [-1, 1].
        original_seconds: The input's measured length.
        processed_seconds: The output's measured length, so a report quotes the
            render rather than the request.
    """

    audio: npt.NDArray[np.float32]
    original_seconds: float
    processed_seconds: float


def _as_channels_first(audio: npt.ArrayLike) -> npt.NDArray[np.float32]:
    """Return *audio* as a 1-D or ``(channels, n)`` float32 array.

    Args:
        audio: Mono ``(n,)`` or multichannel ``(channels, n)`` samples.

    Returns:
        The signal as float32, unchanged in layout.

    Raises:
        AudioConfigValueError: The array is empty or has more than two
            dimensions, neither of which is a signal this renderer can stretch.
    """
    array = np.asarray(audio, dtype=np.float32)
    if array.ndim not in (1, 2):
        raise AudioConfigValueError(
            f"A signal has one dimension (mono) or two (channels, samples), "
            f"got {array.ndim}.",
            context={"dimensions": int(array.ndim)},
        )
    if array.size == 0:
        raise AudioConfigValueError(
            "The signal is empty, so there is nothing to process.",
            context={"samples": 0},
        )
    return array


def _seconds(samples: npt.NDArray[np.float32], sample_rate: int) -> float:
    """Return the length of *samples* in seconds at *sample_rate*."""
    return float(samples.shape[-1]) / float(sample_rate)


def _check_sample_rate(sample_rate: int) -> int:
    """Return *sample_rate* as a positive int, refusing anything else."""
    if sample_rate <= 0:
        raise AudioConfigValueError(
            f"The sample rate must be positive, got {sample_rate}.",
            context={"sample_rate": sample_rate},
        )
    return int(sample_rate)


def time_stretch(
    audio: npt.ArrayLike, rate: float, *, sample_rate: int
) -> TimePitchResult:
    """Play *audio* *rate* times faster without changing its pitch.

    Args:
        audio: Mono ``(n,)`` or ``(channels, n)`` samples.
        rate: Speed factor; ``1.25`` plays a 1.000 s file in 0.800 s.  Must lie
            within :data:`MIN_RATE`-:data:`MAX_RATE`.
        sample_rate: The signal's own rate, used for the reported lengths.

    Returns:
        The stretched signal and both measured lengths.

    Raises:
        AudioConfigValueError: The rate is not finite or outside the range, the
            sample rate is not positive, or the signal is empty.
    """
    if not math.isfinite(rate) or not MIN_RATE <= rate <= MAX_RATE:
        raise AudioConfigValueError(
            f"The rate must be between {MIN_RATE:g} and {MAX_RATE:g}, got {rate:g}.",
            context={"rate": rate},
        )
    checked_rate = _check_sample_rate(sample_rate)
    signal = _as_channels_first(audio)

    import librosa

    stretched = np.asarray(
        librosa.effects.time_stretch(y=signal, rate=float(rate)), dtype=np.float32
    )
    return TimePitchResult(
        audio=stretched,
        original_seconds=_seconds(signal, checked_rate),
        processed_seconds=_seconds(stretched, checked_rate),
    )


def pitch_shift(
    audio: npt.ArrayLike, semitones: float, *, sample_rate: int
) -> TimePitchResult:
    """Move *audio* by *semitones* without changing its length.

    Args:
        audio: Mono ``(n,)`` or ``(channels, n)`` samples.
        semitones: Shift in semitones; ``12`` is an octave up.  Must lie within
            :data:`MIN_SEMITONES`-:data:`MAX_SEMITONES`.
        sample_rate: The signal's own rate, which the phase vocoder needs to
            map bins to frequencies.

    Returns:
        The shifted signal and both measured lengths.

    Raises:
        AudioConfigValueError: The shift is not finite or outside the range,
            the sample rate is not positive, or the signal is empty.
    """
    if not math.isfinite(semitones) or not MIN_SEMITONES <= semitones <= MAX_SEMITONES:
        raise AudioConfigValueError(
            f"The semitones must be between {MIN_SEMITONES:g} and "
            f"{MAX_SEMITONES:g}, got {semitones:g}.",
            context={"semitones": semitones},
        )
    checked_rate = _check_sample_rate(sample_rate)
    signal = _as_channels_first(audio)

    import librosa

    shifted = np.asarray(
        librosa.effects.pitch_shift(y=signal, sr=checked_rate, n_steps=semitones),
        dtype=np.float32,
    )
    return TimePitchResult(
        audio=shifted,
        original_seconds=_seconds(signal, checked_rate),
        processed_seconds=_seconds(shifted, checked_rate),
    )
