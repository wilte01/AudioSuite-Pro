"""ffmpeg_check.py — Probe whether FFmpeg is installed and on PATH.

Changed in 2.7.0: the blind-``except`` boundary is named for the BLE001 triage
(WP-7 of ``PLAN_2026-11-03_2.4.1_stop_the_drift.md``, section 10).
"""

import logging

from audio_suite_shared.secure_subprocess import run_secure_subprocess

logger = logging.getLogger(__name__)


def check_ffmpeg() -> bool:
    """
    Return True if 'ffmpeg -version' exits cleanly, False otherwise.
    Never raises.
    """
    try:
        result = run_secure_subprocess(
            "ffmpeg",
            ["-version"],
            capture_output=True,
            timeout=5,
            check=False,
        )
        return result.returncode == 0
    except Exception as exc:  # noqa: BLE001 - availability check is a bool
        logger.warning("ffmpeg check failed: %s", exc, exc_info=True)
        return False
