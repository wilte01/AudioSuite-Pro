"""
core/models.py
Data classes for the ML Denoiser.

``DenoiseParams`` is the single source of truth for a run: the GUI, the CLI and
the Master Driver all build one, and the processor reads only this object.

Three measured facts are constants here rather than magic numbers buried in the
engine (PLAN_feature_expansion.md D116):

* RNNoise processes 10 ms frames of **48 kHz** audio.  It resamples internally
  and its own resampler can return one sample more or less than it was given, so
  the engine trims (or pads) the result back to the exact input length.
* The model is **speech-oriented**.  A 220 Hz tone was attenuated by ~24 dB in
  the measurement, so a run reports the level it measured instead of promising a
  transparent denoise, and ``amount`` blends the model's output back toward the
  original.
* Its output is 16-bit, so a run's fidelity is 16-bit: the adapter works in the
  model's own sample format rather than pretending otherwise.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from pydub import AudioSegment

#: RNNoise's frame size: 10 ms at its internal 48 kHz rate.
FRAME_SIZE: int = 480

#: The rate RNNoise works at internally (it resamples in and back out).
MODEL_SAMPLE_RATE: int = 48000

#: Default blend: the model's output, unmodified.  A lower value keeps part of
#: the original signal, which is what a music file needs from a speech model.
DEFAULT_AMOUNT: float = 1.0

#: A run at 0% would write the source back unchanged, so it is refused.
MIN_AMOUNT: float = 0.0

#: Attenuation below this is measurement noise, not a repair: the file is
#: reported clean and is not rewritten.
MIN_CHANGE_DB: float = 0.1

#: Floor used when an RMS of exactly zero would make the dB value -inf.
SILENCE_FLOOR_DBFS: float = -120.0


@dataclass
class DenoiseParams:
    """Everything an ML-denoising run needs.

    Attributes:
        amount: How much of the model's output to keep, ``0.0``-``1.0``; 1.0 is
            the model's own result and 0.5 is an equal blend with the source.
        dry_run: Measure every file and report what would be written, without
            writing anything.  The model still runs: a dry run that did not
            measure could not report the attenuation.
    """

    amount: float = DEFAULT_AMOUNT
    dry_run: bool = False

    def validate(self) -> list[str]:
        """Return the problems that make this run impossible, as messages."""
        problems: list[str] = []
        if not (MIN_AMOUNT < self.amount <= 1.0):
            problems.append(
                f"Denoise amount must be above 0% and at most 100%; got "
                f"{self.amount * 100:.0f}%."
            )
        return problems


class DenoiseResult(NamedTuple):
    """The outcome of one file's denoise pass.

    Attributes:
        audio: The processed segment, at the source's rate and channel count,
            with the same number of samples as the source.
        rms_before_db: Global RMS of the source, in dBFS.
        rms_after_db: Global RMS of ``audio``, in dBFS.
        was_modified: Whether the level moved by at least
            :data:`MIN_CHANGE_DB`.  A file the model left alone is reported
            clean and is never rewritten.
    """

    audio: AudioSegment
    rms_before_db: float
    rms_after_db: float
    was_modified: bool

    def attenuation_db(self) -> float:
        """Return how much the level dropped, in dB (never negative)."""
        return max(self.rms_before_db - self.rms_after_db, 0.0)
