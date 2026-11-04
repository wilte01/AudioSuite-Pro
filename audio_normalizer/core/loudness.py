"""
loudness.py
FFmpeg loudnorm analysis pass — measures the current loudness of an audio
file and returns the data needed for the second (normalisation) pass.

Pure function: no tkinter imports, no global state.

Changed in 2.1.7: the true-peak ceiling and LRA target are parameters instead
of the literal ``TP=-1.5:LRA=11`` every delivery target used to get, and
``parse_output_true_peak`` reads the peak the second pass actually achieved.

Changed in 2.4.2: the analysis pass runs through
:func:`audio_suite_shared.audio_probe.loudnorm_inputs` and the achieved peak
through :func:`audio_suite_shared.audio_probe.achieved_true_peak`, so the suite
parses loudnorm once instead of once per tool.  Both functions keep their
published contract: ``measure`` returns the same keys with the same floor
defaults (and ``None`` when FFmpeg printed no analysis), and
``parse_output_true_peak`` returns the same figure, including the ``-70.0``
floor it has always reported for a non-finite peak.
"""

import math
from typing import Any, Optional

from audio_suite_shared.audio_probe import achieved_true_peak, loudnorm_inputs
from audio_suite_shared.error_logger import get_logger
from audio_suite_shared.exceptions import AudioFormatError

from ..utils.ffmpeg_finder import FFMPEG_PATH

logger = get_logger("audio_normalizer")

# Named dict type for clarity in calling code
# keys: input_i, input_tp, input_lra, input_thresh, target_offset
LoudnessData = dict[str, Any]

#: What loudnorm's ``-inf`` becomes.  The filter prints ``-inf`` for digital
#: silence, and this adapter has always published the floor rather than a figure
#: it did not measure — which matters, because the second pass receives these
#: values as its ``measured_*`` parameters.
_SILENCE_FLOOR_DB = -70.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Convert a loudnorm JSON value to float, handling '-inf' and 'inf'."""
    try:
        f = float(value)
        return default if math.isinf(f) or math.isnan(f) else f
    except (TypeError, ValueError):
        return default


def measure(
    file_path: str,
    target_lufs: float,
    true_peak: float = -1.5,
    lra: float = 11,
) -> Optional[LoudnessData]:
    """
    Run the FFmpeg loudnorm filter in analysis mode and return its figures.

    Args:
        file_path:   Absolute path to the audio file.
        target_lufs: The target integrated loudness (e.g. -16.0).
        true_peak:   True-peak ceiling in dBTP (default -1.5, the shipped
            behaviour before the ceiling became configurable).
        lra:         Target loudness range in LU (default 11).

    Returns:
        A dict with loudness measurements, or None if detection failed.
    """
    try:
        figures = loudnorm_inputs(
            file_path,
            target=target_lufs,
            true_peak=true_peak,
            lra=lra,
            ffmpeg=FFMPEG_PATH,
        )
    # A container the capability matrix cannot read is a measurement that did
    # not happen, which is what this function has always reported as ``None``.
    # A missing or failing FFmpeg stays an exception, as it was before.
    except AudioFormatError as exc:
        logger.log_error(
            "WARNING", f"No loudness measurement for {file_path}: {exc}", show_gui=False
        )
        return None

    if figures is None:
        logger.log_error(
            "INFO", f"FFmpeg returned no JSON for: {file_path}", show_gui=False
        )
        return None

    return {
        "input_i": _safe_float(figures.get("input_i"), _SILENCE_FLOOR_DB),
        "input_tp": _safe_float(figures.get("input_tp"), _SILENCE_FLOOR_DB),
        "input_lra": _safe_float(figures.get("input_lra"), 0.0),
        "input_thresh": _safe_float(figures.get("input_thresh"), _SILENCE_FLOOR_DB),
        "target_offset": _safe_float(figures.get("target_offset"), 0.0),
    }


def parse_output_true_peak(stderr: str) -> Optional[float]:
    """Read the true peak FFmpeg reports after the normalisation pass.

    The second pass runs with ``print_format=summary``, which prints either a
    ``Output True Peak: -1.3 dBTP`` line (current FFmpeg) or a JSON block with
    ``output_tp`` (some builds), so both forms are read. Two passes with
    different ceilings can measure the same input, so this is the only
    evidence that the requested ceiling was reached and retained.

    Args:
        stderr: FFmpeg's stderr from the encode pass.

    Returns:
        The achieved true peak in dBTP, or ``None`` when FFmpeg reported no
        output peak (a build without loudnorm's summary).
    """
    return achieved_true_peak(stderr)
