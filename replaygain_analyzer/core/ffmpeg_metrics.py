"""
ffmpeg_metrics.py
Measures integrated loudness (LUFS) and true peak (dBFS) of an audio
file using FFmpeg's ebur128 filter.

Pure function — no tkinter imports, no global state.
Also owns get_resource_path() for PyInstaller compatibility.

FFmpeg resolution order (Windows)
----------------------------------
1. Beside this file: replaygain_analyzer/core/ffmpeg.exe  (legacy local copy)
2. System PATH: 'ffmpeg'  (consistent with cd_ripper/ui/setup_tab.py fallback)

On non-Windows the system 'ffmpeg' is always used.
"""

import logging
import os
import re
import subprocess
import sys

from audio_suite_shared.constants import WORKER_TIMEOUT_SECS
from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    run_secure_subprocess,
)
from audio_suite_shared.subprocess_utils import get_startupinfo

# Re-export the canonical Windows STARTUPINFO helper under this module's
# historical private name so existing callers and tests keep working.
_get_startupinfo = get_startupinfo

logger = logging.getLogger(__name__)


def get_resource_path(relative_path: str) -> str:
    """
    Return the absolute path to a bundled resource.

    Works in normal dev mode and when frozen by PyInstaller.

    Args:
        relative_path: Path relative to the package or PyInstaller bundle root.

    Returns:
        Absolute filesystem path to the resource.
    """
    if hasattr(sys, "_MEIPASS"):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)


def _get_ffmpeg_exe() -> str:
    """
    Resolve the FFmpeg executable path for the current platform.

    On Windows, checks for a local ffmpeg.exe beside this file first,
    then falls back to the system PATH.

    Returns:
        Path to the ffmpeg executable (may be a bare name relying on PATH).
    """
    if os.name == "nt":
        local = get_resource_path("ffmpeg.exe")
        return local if os.path.exists(local) else "ffmpeg"
    return "ffmpeg"


def get_metrics(file_path: str) -> tuple[float | None, float]:
    """
    Analyse one audio file with FFmpeg ebur128 and return measurements.

    Args:
        file_path: Absolute path to the audio file.

    Returns:
        (integrated_lufs, true_peak_dbfs).
        integrated_lufs is None if measurement failed.
        true_peak_dbfs defaults to 0.0 on failure.
    """
    ffmpeg = _get_ffmpeg_exe()

    cmd = [
        ffmpeg,
        "-hide_banner",
        "-i",
        os.path.normpath(file_path),
        "-af",
        "ebur128=peak=true",
        "-f",
        "null",
        "-",
    ]

    try:
        result = run_secure_subprocess(
            ffmpeg,
            cmd[1:],
            capture_output=True,
            encoding="utf-8",
            errors="ignore",
            timeout=WORKER_TIMEOUT_SECS,
            check=False,
        )

        lufs_matches = re.findall(r"I:\s+([-+]?\d+\.?\d*)\s+LUFS", result.stderr)
        peak_matches = re.findall(r"Peak:\s+([-+]?\d+\.?\d*)\s+dBFS", result.stderr)

        lufs: float | None = float(lufs_matches[-1]) if lufs_matches else None
        peak: float = float(peak_matches[-1]) if peak_matches else 0.0

        if lufs is None:
            logger.warning(
                "ffmpeg returned no LUFS measurement for %s (exit code %d).\n"
                "ffmpeg stderr: %s",
                file_path,
                result.returncode,
                result.stderr[-500:] if result.stderr else "(empty)",
            )

        return lufs, peak

    except (FileNotFoundError, SubprocessSecurityError):
        logger.error(
            "ffmpeg executable not found at '%s'. "
            "Install ffmpeg and ensure it is on the system PATH, "
            "or place the ffmpeg binary alongside the "
            "replaygain_analyzer/core/ module.",
            ffmpeg,
        )
        return None, 0.0

    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg timed out processing: %s", file_path)
        return None, 0.0

    except (OSError, subprocess.CalledProcessError) as exc:
        logger.error("Unexpected error measuring %s: %s", file_path, exc, exc_info=True)
        return None, 0.0
