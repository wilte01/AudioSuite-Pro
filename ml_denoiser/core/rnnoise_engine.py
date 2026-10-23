"""
core/rnnoise_engine.py
Adapter around RNNoise (``pyrnnoise``), kept behind a lazy import.

``pyrnnoise`` is part of the optional ``ml`` extra, so nothing here imports it
at module import time.  A machine without the extra can open the GUI, validate a
run and read this module's error message; only a live *or measured* run needs
the model, and that is the moment the import is attempted.

The API this adapter targets was measured, not assumed (PLAN_feature_expansion
D116): ``RNNoise(sample_rate)`` takes the source rate and resamples to 48 kHz
internally, and ``denoise_chunk(chunk, partial=True)`` yields
``(speech_probabilities, denoised_frame)`` for a ``(channels, samples)`` int16
array, returning frames at both the input rate and — within one sample — the
input length.  Two consequences shape this file:

* **The length is forced.**  A 573-sample 44.1 kHz input came back one sample
  *longer*, and a dropped final frame would lose up to 10 ms of audio, so the
  adapter trims an overshoot and pads an undershoot with the source's own tail
  samples.  Silence would be a repair the user never asked for.
* **The model is not transparent.**  RNNoise is trained on speech; it attenuated
  a 220 Hz tone by ~24 dB.  ``amount`` blends its output with the dry signal and
  the caller reports the measured before/after level, so the tool says what it
  did rather than claiming a clean denoise.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).

Changed in 2.1.0: the missing-dependency message no longer tells a GUI user to
    run ``uv sync --extra ml``; the tool installs RNNoise on first use and the
    hint remains only for a headless run.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import numpy.typing as npt
from pydub import AudioSegment

from audio_suite_shared.exceptions import AudioMissingDependencyError

from .models import (
    DEFAULT_AMOUNT,
    MIN_AMOUNT,
    MIN_CHANGE_DB,
    SILENCE_FLOOR_DBFS,
    DenoiseResult,
)

logger = logging.getLogger(__name__)

#: The extra a user has to install to run a denoise.
ML_EXTRA_HINT = "uv sync --extra ml"

#: 16-bit full scale, the model's own sample format.
_FULL_SCALE = 32768.0


def missing_dependency_reason() -> str | None:
    """Return why RNNoise cannot be used, or None when it is importable.

    The import is attempted, not guessed from metadata: a broken wheel fails
    here with the real reason instead of at the first file.
    """
    try:
        import pyrnnoise  # noqa: F401
    except ImportError as exc:
        return (
            f"RNNoise is not installed ({exc}). The ML Denoiser installs it on "
            f"first use; a headless run needs the 'ml' extra: {ML_EXTRA_HINT}."
        )
    except Exception as exc:  # pragma: no cover - broken installs only
        return f"RNNoise is installed but failed to import: {exc}"
    return None


def require_rnnoise() -> None:
    """Raise :class:`AudioMissingDependencyError` when RNNoise is unavailable."""
    reason = missing_dependency_reason()
    if reason:
        raise AudioMissingDependencyError(reason, dependency="pyrnnoise")


def rms_dbfs(samples: npt.NDArray[Any]) -> float:
    """Return the global RMS of *samples* in dBFS, floored at -120.

    Args:
        samples: An int16 (or float) array, any shape.
    """
    if samples.size == 0:
        return SILENCE_FLOOR_DBFS
    values = np.asarray(samples, dtype=np.float64) / _FULL_SCALE
    rms = float(np.sqrt(np.mean(np.square(values))))
    if rms <= 0.0:
        return SILENCE_FLOOR_DBFS
    return max(20.0 * float(np.log10(rms)), SILENCE_FLOOR_DBFS)


def _model_output(
    chunk: npt.NDArray[np.int16], sample_rate: int
) -> npt.NDArray[np.int16]:
    """Run one ``(channels, samples)`` int16 chunk through RNNoise.

    The returned array is the model's own length, which is not guaranteed to
    match the input (see the module docstring); :func:`denoise_samples` fixes
    that.  A fresh denoiser per call keeps one file's recurrent state out of
    the next one's.
    """
    from pyrnnoise import RNNoise

    denoiser = RNNoise(sample_rate)
    frames = [frame for _probs, frame in denoiser.denoise_chunk(chunk, partial=True)]
    if not frames:
        return np.zeros_like(chunk)
    joined = np.concatenate([np.atleast_2d(frame) for frame in frames], axis=1)
    shaped: npt.NDArray[np.int16] = np.ascontiguousarray(joined, dtype=np.int16)
    return shaped


def denoise_samples(
    chunk: npt.NDArray[np.int16], sample_rate: int, amount: float = DEFAULT_AMOUNT
) -> npt.NDArray[np.int16]:
    """Denoise *chunk* and return an int16 array with exactly its shape.

    Args:
        chunk: ``(channels, samples)`` int16 audio.
        sample_rate: The chunk's rate; RNNoise resamples from it internally.
        amount: Blend of the model's output with the dry signal, 0-1.

    Returns:
        The processed chunk, same dtype and shape as *chunk*.

    Raises:
        ValueError: The array is not two-dimensional or *amount* is out of range.
    """
    if chunk.ndim != 2:
        raise ValueError(f"expected a (channels, samples) array, got {chunk.shape}")
    if not (MIN_AMOUNT < amount <= 1.0):
        raise ValueError(f"amount must be above 0 and at most 1; got {amount}")
    if chunk.size == 0:
        return chunk.copy()

    wet = _model_output(chunk, sample_rate)
    samples = int(chunk.shape[1])

    # The model's resampler can overshoot by a sample, and a short tail frame is
    # returned with zero padding.  Either way the written file must last exactly
    # as long as the source, so the tail is trimmed or restored from the source.
    if wet.shape[0] != chunk.shape[0]:
        raise ValueError(f"model returned {wet.shape[0]} channels for {chunk.shape[0]}")
    if wet.shape[1] > samples:
        wet = wet[:, :samples]
    elif wet.shape[1] < samples:
        wet = np.concatenate([wet, chunk[:, wet.shape[1] :]], axis=1)

    blended = amount * wet.astype(np.float32) + (1.0 - amount) * chunk.astype(
        np.float32
    )
    rounded: npt.NDArray[np.int16] = np.clip(
        np.rint(blended), -_FULL_SCALE, _FULL_SCALE - 1
    ).astype(np.int16)
    return rounded


def denoise_segment(
    audio: AudioSegment, amount: float = DEFAULT_AMOUNT
) -> DenoiseResult:
    """Denoise one decoded segment, measuring the level before and after.

    Args:
        audio: The source segment; it is not modified.
        amount: Blend of the model's output with the source, 0-1.

    Returns:
        A :class:`DenoiseResult` whose audio keeps the source's rate, channel
        count and length.  A level change smaller than ``MIN_CHANGE_DB`` is
        reported with ``was_modified=False``.

    Raises:
        AudioMissingDependencyError: RNNoise is not installed.
        ValueError: *amount* is out of range.
    """
    if not (MIN_AMOUNT < amount <= 1.0):
        raise ValueError(f"amount must be above 0 and at most 1; got {amount}")
    require_rnnoise()

    segment = audio.set_sample_width(2)
    channels = segment.channels
    raw = np.asarray(segment.get_array_of_samples(), dtype=np.int16)
    if raw.size == 0:
        return DenoiseResult(
            audio=segment,
            rms_before_db=SILENCE_FLOOR_DBFS,
            rms_after_db=SILENCE_FLOOR_DBFS,
            was_modified=False,
        )

    chunk = raw.reshape(-1, channels).T
    before = rms_dbfs(chunk)
    processed = denoise_samples(chunk, segment.frame_rate, amount)
    after = rms_dbfs(processed)

    denoised = AudioSegment(
        data=processed.T.tobytes(),
        sample_width=2,
        frame_rate=segment.frame_rate,
        channels=channels,
    )
    return DenoiseResult(
        audio=denoised,
        rms_before_db=before,
        rms_after_db=after,
        was_modified=(before - after) >= MIN_CHANGE_DB,
    )
