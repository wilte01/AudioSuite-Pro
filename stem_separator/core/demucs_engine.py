"""
core/demucs_engine.py
Adapter around Demucs, kept behind a lazy import.

Demucs (and torch) are an optional dependency — the ``ml`` extra — so nothing
here imports them at module import time.  A machine without the extra can open
the GUI, validate a run and read this module's error message; only a *live*
separation needs the model, and that is the moment the import is attempted.

Two measured behaviours shape the code (PLAN_feature_expansion.md D116):

* ``demucs.api.Separator.separate_tensor(wav, sr)`` takes a ``(channels,
  samples)`` torch tensor and returns ``(origin, {stem: tensor})``.  It is the
  cheap seam for a decoded file, so the audio is decoded once here rather than
  letting ``separate_audio_file`` decode it again.
* Demucs operates at 44.1 kHz stereo.  Inputs are resampled to that rate first,
  so the stems and their durations are predictable and a mono source is
  duplicated to two channels rather than rejected.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
from pydub import AudioSegment

from audio_suite_shared.exceptions import AudioMissingDependencyError
from audio_suite_shared.gpu_utils import CUDA, DeviceInfo, resolve_device

from .models import (
    DEFAULT_MODEL,
    MODEL_CHOICES,
    MODEL_SAMPLE_RATE,
    SeparatedTrack,
    normalise_stems,
)

logger = logging.getLogger(__name__)

#: The extra a user has to install to run a separation.
ML_EXTRA_HINT = "uv sync --extra ml"

#: Loaded separators, keyed by ``(model, device)``.  Loading a model takes
#: ~0.6 s from the HuggingFace cache and downloads ~80 MB on first use, so a
#: batch of tracks must not pay that per file.  Guarded because the pool has
#: several workers.
_SEPARATORS: dict[tuple[str, str], Any] = {}
_SEPARATOR_LOCK = threading.Lock()


def missing_dependency_reason() -> str | None:
    """Return why Demucs cannot be used, or None when it is importable.

    The import is attempted, not guessed from metadata: a half-installed torch
    (a missing CUDA DLL, for instance) fails here with the real reason instead
    of at the first track.
    """
    try:
        import demucs.api  # noqa: F401
    except ImportError as exc:
        return (
            f"Demucs is not installed ({exc}). Install the 'ml' extra: {ML_EXTRA_HINT}."
        )
    except Exception as exc:  # pragma: no cover - broken installs only
        return f"Demucs is installed but failed to import: {exc}"
    return None


def require_demucs() -> None:
    """Raise :class:`AudioMissingDependencyError` when Demucs is unavailable."""
    reason = missing_dependency_reason()
    if reason:
        raise AudioMissingDependencyError(reason, dependency="demucs")


def _separator(model: str, device: str) -> Any:
    """Return the cached ``demucs.api.Separator`` for *model* and *device*."""
    key = (model, device)
    with _SEPARATOR_LOCK:
        separator = _SEPARATORS.get(key)
        if separator is None:
            from demucs.api import Separator

            logger.info("Loading Demucs model %s on %s", model, device)
            separator = Separator(model=model, device=device)
            _SEPARATORS[key] = separator
        return separator


def clear_separator_cache() -> None:
    """Forget every loaded model (used by tests and by a device change)."""
    with _SEPARATOR_LOCK:
        _SEPARATORS.clear()


def device_for(device: str) -> DeviceInfo:
    """Resolve a run's device string to a :class:`DeviceInfo`.

    Raises:
        ValueError: The device string is unknown, or CUDA was requested and is
            not usable.
    """
    return resolve_device(device)


def _load_audio(path: str) -> npt.NDArray[np.float32]:
    """Decode *path* to a ``(2, samples)`` float32 array at the model's rate.

    The source is resampled to :data:`MODEL_SAMPLE_RATE` and forced to stereo,
    because that is the shape Demucs' model accepts.  Samples are normalised by
    the decoded sample width, so a 24-bit source is not scaled 256× too far.
    """
    segment = (
        AudioSegment.from_file(path)
        .set_channels(2)
        .set_frame_rate(MODEL_SAMPLE_RATE)
        .set_sample_width(2)
    )
    raw = np.asarray(segment.get_array_of_samples(), dtype=np.float32)
    interleaved: npt.NDArray[np.float32] = raw.reshape(-1, 2)
    samples: npt.NDArray[np.float32] = interleaved.T / 32768.0
    return samples


def separate(
    path: str,
    *,
    model: str = DEFAULT_MODEL,
    device: str = "auto",
    stems: Sequence[str] | None = None,
) -> SeparatedTrack:
    """Separate *path* into its stems with Demucs.

    Args:
        path: Source audio file.
        model: Demucs model name, one of ``MODEL_CHOICES``.
        device: ``"auto"``, ``"cpu"`` or ``"cuda"``.
        stems: Stems to keep; ``None`` keeps all four.

    Returns:
        A :class:`SeparatedTrack` whose arrays are float32 in -1..1.

    Raises:
        AudioMissingDependencyError: Demucs (or torch) is not installed.
        ValueError: The model or stem selection is invalid.
    """
    require_demucs()
    if model not in MODEL_CHOICES:
        raise ValueError(f"unknown model {model!r}; choose from {list(MODEL_CHOICES)}")
    selected = normalise_stems(tuple(stems) if stems else None)
    info = device_for(device)

    import torch

    separator = _separator(model, info.device)
    samples = _load_audio(path)
    tensor = torch.from_numpy(samples)
    _origin, separated = separator.separate_tensor(tensor, MODEL_SAMPLE_RATE)

    kept: dict[str, Any] = {}
    for stem in selected:
        if stem not in separated:
            raise ValueError(
                f"model {model!r} returned no {stem!r} stem (got {sorted(separated)})"
            )
        value = separated[stem]
        array = value.detach().cpu().numpy() if hasattr(value, "detach") else value
        kept[stem] = np.ascontiguousarray(array, dtype=np.float32)
    return SeparatedTrack(sample_rate=MODEL_SAMPLE_RATE, stems=kept)


def mix_stems(
    stems: Mapping[str, Any], names: Sequence[str] | None = None
) -> npt.NDArray[np.float32]:
    """Return the sample-wise sum of *names*, clipped to -1..1.

    Args:
        stems: Stem name to a ``(channels, samples)`` float array.
        names: Stems to include; ``None`` includes every stem present.

    Returns:
        The summed mix, same shape as the inputs.

    Raises:
        ValueError: No stem was selected, or the shapes disagree.
    """
    chosen = list(names) if names is not None else list(stems)
    if not chosen:
        raise ValueError("a mix needs at least one stem")
    missing = [name for name in chosen if name not in stems]
    if missing:
        raise ValueError(f"no audio for stem(s) {missing}")
    first = np.asarray(stems[chosen[0]], dtype=np.float32)
    total = np.zeros_like(first)
    for name in chosen:
        array = np.asarray(stems[name], dtype=np.float32)
        if array.shape != total.shape:
            raise ValueError(
                f"stem {name!r} has shape {array.shape}, expected {total.shape}"
            )
        np.add(total, array, out=total)
    clipped: npt.NDArray[np.float32] = np.clip(total, -1.0, 1.0).astype(
        np.float32, copy=False
    )
    return clipped


def write_stem(
    audio: npt.NDArray[np.float32] | Any, sample_rate: int, path: Path
) -> None:
    """Write one stem array to *path* as 16-bit PCM WAV.

    Args:
        audio: ``(channels, samples)`` or ``(samples,)`` float array in -1..1.
        sample_rate: Sample rate of *audio*.
        path: Destination file; its parent directory is created.

    Raises:
        OSError: The destination cannot be created or written.
    """
    array = np.asarray(audio, dtype=np.float32)
    if array.ndim == 1:
        array = np.stack([array, array], axis=0)
    channels = int(array.shape[0])
    clipped = np.clip(array, -1.0, 1.0)
    pcm: npt.NDArray[np.int16] = (clipped * 32767.0).T.astype(np.int16)
    segment = AudioSegment(
        data=pcm.tobytes(),
        sample_width=2,
        frame_rate=sample_rate,
        channels=channels,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    segment.export(str(path), format="wav")


def describe_device(info: DeviceInfo) -> str:
    """Return the short device caption for progress and completion lines."""
    if info.device == CUDA:
        return f"CUDA ({info.name})"
    return "CPU"
