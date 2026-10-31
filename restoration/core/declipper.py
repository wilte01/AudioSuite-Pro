"""Declip: reconstruct the peaks a clipped recording lost.

Detection
---------
Clipping leaves a **flat top**: consecutive samples sit at (or within a hair of)
the same magnitude, because everything above the ceiling was truncated to it.
A peak that merely *touches* full scale is curved — its samples differ — and is
not clipping.

So detection works in three steps, and each one exists to keep a false positive
out of a repair that would make clean audio worse:

1. Candidates are the samples at or above ``threshold`` × the file's own peak.
   Measuring against the file's peak rather than full scale is what lets the
   repair find a ceiling a limiter left at ``-1.9 dBFS`` without the user having
   to know that number.
2. Inside a candidate region, only the samples within :data:`_PLATEAU_TOLERANCE`
   of its **highest** magnitude form the plateau.  A curved peak has exactly one
   sample at that height, so it yields a one-sample plateau and is rejected.
3. A plateau is only repaired when its own clean context can lift it: the
   samples immediately either side must sit below the ceiling (otherwise the
   "clipped" region is simply the waveform, as a square wave or a synth pad),
   there must be enough of them, and the reconstruction must rise above the
   plateau by :data:`_MIN_PEAK_LIFT` and stay inside full scale.  A run that
   cannot be improved is counted as skipped and **left byte-identical** — a
   repair that cannot beat the original is not a repair.

Reconstruction
--------------
The plateau is rebuilt by cubic-spline interpolation over the clean samples
either side of it.  A flat top under-estimates the true peak, so the spline's
natural overshoot *is* the restoration: for a clipped sine it returns the arc
the waveform had before the ceiling cut it.

The result is capped by refusing any reconstruction above full scale, so the
repair cannot introduce clipping of its own and a second pass finds nothing.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

import logging
from typing import NamedTuple

import numpy as np
import numpy.typing as npt
from pydub import AudioSegment
from scipy.interpolate import CubicSpline

from audio_suite_shared.audio_conversion import (
    clip_to_range,
    log_clip_event,
    measure_peak_db,
    numpy_to_segment,
    segment_to_numpy,
)
from audio_suite_shared.exceptions import AudioConfigurationError

logger = logging.getLogger(__name__)

#: A plateau shorter than this is an isolated sample at the ceiling (an edit
#: point, a digital impulse), not a clipped waveform.
_MIN_RUN_SAMPLES: int = 2

#: How flat a plateau's magnitudes must be.  Clipped samples are identical by
#: construction; dither or a first lossy encode moves them by a few 1e-5.  A
#: curved peak that touches the ceiling moves far more.
_PLATEAU_TOLERANCE: float = 1e-4

#: Clean samples either side used by the interpolating spline.
_CONTEXT_SAMPLES: int = 8

#: Minimum clean samples on each side before a run is reconstructible.
_MIN_CONTEXT: int = 3

#: How far above the plateau a reconstruction must rise to be worth writing.
#: ~0.1 % of full scale: -60 dBFS, well above reconstruction noise and well
#: below the lift a real clipped peak needs.
_MIN_PEAK_LIFT: float = 1e-3

#: A file whose peak is below this is not scooped for clipping: near-silence is
#: flat everywhere, and a "plateau" there is the noise floor.
_MIN_FILE_PEAK: float = 0.05

#: Fraction of the file's own peak at or above which a sample is a candidate.
DEFAULT_THRESHOLD: float = 0.98

#: Longest plateau the repair will reconstruct, in milliseconds.
DEFAULT_MAX_RUN_MS: int = 50


class DeclipResult(NamedTuple):
    """Outcome of one declip pass.

    Attributes:
        audio: The repaired segment; the input object when nothing was repaired.
        runs_found: Flat-topped runs that were reconstructed.
        runs_skipped: Runs that looked clipped but could not be improved (too
            wide, no clean context, or the reconstruction would have clipped).
        was_modified: Whether ``audio`` differs from the input.
        restored_peak_db: Peak of the returned audio in dBFS (``-120`` for
            silence), so the report states what the repair achieved.
    """

    audio: AudioSegment
    runs_found: int
    runs_skipped: int
    was_modified: bool
    restored_peak_db: float


def _contiguous_groups(mask: npt.NDArray[np.bool_]) -> list[tuple[int, int]]:
    """Return the inclusive ``(start, end)`` runs of True in *mask*.

    Args:
        mask: A boolean array.

    Returns:
        The runs, in order.
    """
    groups: list[tuple[int, int]] = []
    start: int | None = None
    for index in range(mask.size):
        if mask[index]:
            if start is None:
                start = index
        elif start is not None:
            groups.append((start, index - 1))
            start = None
    if start is not None:
        groups.append((start, mask.size - 1))
    return groups


def find_clipped_runs(
    samples: npt.NDArray[np.float64],
    threshold: float = DEFAULT_THRESHOLD,
    *,
    plateau_tolerance: float = _PLATEAU_TOLERANCE,
) -> list[tuple[int, int]]:
    """Return the ``(start, end)`` inclusive plateaus that look like a ceiling.

    Args:
        samples: One channel, normalised to ``[-1.0, 1.0]``.
        threshold: Fraction of the file's own peak a sample must reach to be a
            candidate.
        plateau_tolerance: Maximum spread of magnitudes inside a plateau.

    Returns:
        The runs, in order, each at least :data:`_MIN_RUN_SAMPLES` long.
    """
    if samples.size == 0:
        return []
    peak = float(np.max(np.abs(samples)))
    if peak < _MIN_FILE_PEAK:
        return []
    candidates = np.abs(samples) >= threshold * peak
    plateaus: list[tuple[int, int]] = []
    for group_start, group_end in _contiguous_groups(candidates):
        magnitudes = np.abs(samples[group_start : group_end + 1])
        level = float(magnitudes.max())
        # Only the samples at the group's highest magnitude form the plateau.
        flat = magnitudes >= level - plateau_tolerance
        top_index = int(np.argmax(flat))
        start = group_start + top_index
        end = start
        while end + 1 <= group_end and flat[end + 1 - group_start]:
            end += 1
        if end - start + 1 < _MIN_RUN_SAMPLES:
            continue
        plateaus.append((start, end))
    return plateaus


def _context_is_clean(
    samples: npt.NDArray[np.float64],
    start: int,
    end: int,
    level: float,
    context: int,
    plateau_tolerance: float,
) -> bool:
    """Return whether there is enough *clean* context around a plateau.

    Args:
        samples: One channel.
        start: Inclusive first plateau sample.
        end: Inclusive last plateau sample.
        level: The plateau's magnitude.
        context: Clean samples wanted either side.
        plateau_tolerance: How close to the ceiling still counts as clipped.

    Returns:
        True when at least :data:`_MIN_CONTEXT` samples on each side exist and
        none of them is itself at the ceiling.
    """
    left = samples[max(0, start - context) : start]
    right = samples[end + 1 : min(samples.size, end + 1 + context)]
    if left.size < _MIN_CONTEXT or right.size < _MIN_CONTEXT:
        return False
    ceiling = level - plateau_tolerance
    return bool(np.all(np.abs(left) < ceiling) and np.all(np.abs(right) < ceiling))


def reconstruct_run(
    samples: npt.NDArray[np.float64],
    start: int,
    end: int,
    *,
    peak: float,
    context: int = _CONTEXT_SAMPLES,
    plateau_tolerance: float = _PLATEAU_TOLERANCE,
) -> bool:
    """Rebuild ``samples[start:end + 1]`` in place when that improves the peak.

    Args:
        samples: One channel, modified in place.
        start: Inclusive first sample of the plateau.
        end: Inclusive last sample of the plateau.
        peak: The file's peak magnitude, used as the ceiling bound.
        context: Clean samples to use either side.
        plateau_tolerance: How close to the ceiling still counts as clipped.

    Returns:
        True when the plateau was replaced; False when it was left untouched
        (no clean context, no lift, or a reconstruction that would clip).
    """
    level = float(np.max(np.abs(samples[start : end + 1])))
    if not _context_is_clean(samples, start, end, level, context, plateau_tolerance):
        return False

    left_start = max(0, start - context)
    right_end = min(samples.size, end + 1 + context)
    left = samples[left_start:start].astype(np.float64)
    right = samples[end + 1 : right_end].astype(np.float64)
    x_context = np.concatenate(
        [
            np.arange(left_start, start, dtype=np.float64),
            np.arange(end + 1, right_end, dtype=np.float64),
        ]
    )
    y_context = np.concatenate([left, right])
    spline = CubicSpline(x_context, y_context, bc_type="not-a-knot")
    rebuilt = np.asarray(
        spline(np.arange(start, end + 1, dtype=np.float64)), dtype=np.float64
    )

    rebuilt_peak = float(np.max(np.abs(rebuilt))) if rebuilt.size else 0.0
    if rebuilt_peak <= level + _MIN_PEAK_LIFT:
        return False
    if rebuilt_peak > max(peak, 1.0) or rebuilt_peak > 1.0:
        return False
    samples[start : end + 1] = rebuilt
    return True


def declip_segment(
    audio: AudioSegment,
    threshold: float = DEFAULT_THRESHOLD,
    max_run_ms: int = DEFAULT_MAX_RUN_MS,
) -> DeclipResult:
    """Reconstruct clipped peaks in *audio*.

    Args:
        audio: Input audio, mono or multichannel, 16/24/32-bit PCM.
        threshold: Fraction of the file's own peak at or above which a sample
            is a clipping candidate.
        max_run_ms: Longest plateau to reconstruct, in milliseconds.  Wider
            plateaus are counted and reported, never invented.

    Returns:
        The outcome.  When nothing could be repaired the input segment object is
        returned unchanged with ``was_modified=False``, which is what keeps a
        clean file byte-identical.

    Raises:
        AudioConfigurationError: If *threshold* is outside ``(0.0, 1.0]`` or
            *max_run_ms* is not positive.
    """
    if not 0.0 < threshold <= 1.0:
        raise AudioConfigurationError(
            f"threshold must be in (0.0, 1.0], got {threshold}"
        )
    if max_run_ms < 1:
        raise AudioConfigurationError(f"max_run_ms must be >= 1, got {max_run_ms}")

    sample_rate = audio.frame_rate
    channels = audio.channels
    sample_width = audio.sample_width
    max_run_samples = max(2, int(round(max_run_ms * sample_rate / 1000.0)))

    decoded, _rate = segment_to_numpy(audio)
    samples = decoded.T.astype(np.float64)
    file_peak = float(np.max(np.abs(samples))) if samples.size else 0.0

    runs_found = 0
    runs_skipped = 0
    for channel in range(channels):
        column = samples[:, channel].copy()
        repaired_any = False
        for start, end in find_clipped_runs(column, threshold):
            if end - start + 1 > max_run_samples:
                runs_skipped += 1
                continue
            if reconstruct_run(column, start, end, peak=file_peak):
                runs_found += 1
                repaired_any = True
            else:
                runs_skipped += 1
        if repaired_any:
            samples[:, channel] = column

    if runs_found == 0:
        return DeclipResult(
            audio=audio,
            runs_found=0,
            runs_skipped=runs_skipped,
            was_modified=False,
            restored_peak_db=measure_peak_db(decoded),
        )

    clipped = clip_to_range(samples.T.astype(np.float32))
    log_clip_event(clipped, "declip", logger)
    repaired = numpy_to_segment(
        clipped,
        sample_rate,
        sample_width=sample_width,
        num_channels=channels,
    )
    return DeclipResult(
        audio=repaired,
        runs_found=runs_found,
        runs_skipped=runs_skipped,
        was_modified=True,
        restored_peak_db=measure_peak_db(clipped),
    )
