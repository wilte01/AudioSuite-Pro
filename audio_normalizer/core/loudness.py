"""
loudness.py
FFmpeg loudnorm analysis pass — measures the current loudness of an audio
file and returns the data needed for the second (normalisation) pass.

Pure function: no tkinter imports, no global state.
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


def measure(file_path: str, target_lufs: float) -> Optional[LoudnessData]:
    """
    Run the FFmpeg loudnorm filter in analysis mode and parse the JSON output.

    Args:
        file_path:   Absolute path to the audio file.
        target_lufs: The target integrated loudness (e.g. -16.0).

    Returns:
        A dict with loudness measurements, or None if detection failed.
    """
    cmd = [
        FFMPEG_PATH,
        "-hide_banner",
        "-i",
        file_path,
        "-af",
        f"loudnorm=I={target_lufs}:TP=-1.5:LRA=11:print_format=json",
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
