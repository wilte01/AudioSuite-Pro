"""The Audio Normalizer's 2.4.2 loudness measurement, frozen verbatim.

``PLAN_2026-11-03_2.4.2_audio_foundation.md`` WP-5.2.  The migration onto
``audio_suite_shared.audio_probe`` is behaviour-neutral or it is a defect, so
the shipped implementation is kept here — a copy of ``core/loudness.py`` as it
stood at 2.4.2, before the probes landed — and every real-file measurement is
taken twice: once through the adapter, once through this.  Comparing the probe
with the probe would prove nothing, which is why the reference is a frozen copy
and not the module under test.

Changed in 2.4.2: new file (WP-5.2).  Do not modernise it: its job is to keep
saying what the old code said.
"""

import json
import math
import re
from typing import Any, Optional

from audio_suite_shared.error_logger import get_logger

# Changed in 2.5.0: the resolver moved to audio_suite_shared.ffmpeg (D-38).
from audio_suite_shared.ffmpeg import FFMPEG_PATH
from audio_suite_shared.secure_subprocess import run_secure_subprocess

logger = get_logger("audio_normalizer")

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
    """The 2.4.2 measurement: one FFmpeg pass, parsed here."""
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
    """The 2.4.2 achieved-peak parser, frozen."""
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
