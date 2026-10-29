"""
loudness.py
FFmpeg loudnorm analysis pass — measures the current loudness of an audio
file and returns the data needed for the second (normalisation) pass.

Pure function: no tkinter imports, no global state.

Changed in 2.1.7: the true-peak ceiling and LRA target are parameters instead
of the literal ``TP=-1.5:LRA=11`` every delivery target used to get, and
``parse_output_true_peak`` reads the peak the second pass actually achieved.
"""

import json
import math
import re
from typing import Any, Optional

from audio_suite_shared.error_logger import get_logger
from audio_suite_shared.secure_subprocess import run_secure_subprocess

from ..utils.ffmpeg_finder import FFMPEG_PATH

# Add suite root to path for ErrorLogger


logger = get_logger("audio_normalizer")

# Named dict type for clarity in calling code
# keys: input_i, input_tp, input_lra, input_thresh, target_offset
LoudnessData = dict[str, Any]


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
    Run the FFmpeg loudnorm filter in analysis mode and parse the JSON output.

    Args:
        file_path:   Absolute path to the audio file.
        target_lufs: The target integrated loudness (e.g. -16.0).
        true_peak:   True-peak ceiling in dBTP (default -1.5, the shipped
            behaviour before the ceiling became configurable).
        lra:         Target loudness range in LU (default 11).

    Returns:
        A dict with loudness measurements, or None if detection failed.
    """
    cmd = [
        FFMPEG_PATH,
        "-hide_banner",
        "-i",
        file_path,
        "-af",
        f"loudnorm=I={target_lufs}:TP={true_peak}:LRA={lra}:print_format=json",
        "-f",
        "null",
        "-",
    ]

    result = run_secure_subprocess(
        cmd[0],
        cmd[1:],
        capture_output=True,
        errors="ignore",
        check=False,
    )

    # FFmpeg stderr can contain earlier {…} blocks (stream info, metadata)
    # before the loudnorm JSON.  Take the LAST match, which is always the
    # loudnorm output block.
    json_matches = re.findall(r"\{[^{}]*\}", result.stderr)
    if not json_matches:
        logger.log_error(
            "INFO", f"FFmpeg returned no JSON for: {file_path}", show_gui=False
        )
        logger.log_error(
            "DEBUG", f"stderr tail: {result.stderr[-400:]}", show_gui=False
        )
        return None

    try:
        data = json.loads(json_matches[-1])
        # Verify it looks like loudnorm output
        if "input_i" not in data:
            logger.log_error(
                "WARNING",
                f"Last JSON block is not loudnorm data for: {file_path}",
                show_gui=False,
            )
            return None
        return {
            "input_i": _safe_float(data.get("input_i"), -70.0),
            "input_tp": _safe_float(data.get("input_tp"), -70.0),
            "input_lra": _safe_float(data.get("input_lra"), 0.0),
            "input_thresh": _safe_float(data.get("input_thresh"), -70.0),
            "target_offset": _safe_float(data.get("target_offset"), 0.0),
        }

    except (json.JSONDecodeError, ValueError, KeyError) as exc:
        logger.log_error(
            "ERROR", f"JSON parse error for {file_path}: {exc}", show_gui=False
        )
        logger.log_error(
            "DEBUG", f"Attempted to parse: {json_matches[-1][:200]}", show_gui=False
        )
        return None


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
    if not isinstance(stderr, str):
        return None

    text_match = re.search(
        r"Output True Peak:\s*(-?(?:\d+(?:\.\d+)?|inf))\s*dBTP", stderr
    )
    if text_match:
        return _safe_float(text_match.group(1), -70.0)

    for block in reversed(re.findall(r"\{[^{}]*\}", stderr)):
        try:
            data = json.loads(block)
        except (json.JSONDecodeError, ValueError):
            continue
        if "output_tp" in data:
            return _safe_float(data.get("output_tp"), -70.0)
    return None
