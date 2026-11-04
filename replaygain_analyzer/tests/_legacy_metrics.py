"""A frozen copy of the 2.4.1 measurement implementation.

``PLAN_2026-11-03_2.4.2_audio_foundation.md`` WP-5.1 migrates ReplayGain's
measurement onto ``audio_suite_shared.audio_probe`` and must prove the numbers
did not move.  The reference must be a copy that lives beside the test, never
the code read back from git history: an equality test that fetches the old
module at run time stops meaning anything as soon as the module moves, and one
that re-reads the probe's own output proves nothing at all.

This file is therefore deliberately a verbatim freeze of the functions that
existed in ``replaygain_analyzer/core/ffmpeg_metrics.py`` at 2.4.1:
``get_metrics``, ``measure_album_loudness`` and the three private helpers they
use.  Do not "improve" it, do not route it through the probe, and do not add
features: its only job is to answer "what did the shipped tool report?".

Changed in 2.4.2: added as the WP-5.1 equality reference.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import tempfile

from audio_suite_shared.constants import WORKER_TIMEOUT_SECS
from audio_suite_shared.secure_subprocess import (
    SubprocessSecurityError,
    run_secure_subprocess,
)

logger = logging.getLogger(__name__)


def _ffmpeg_exe() -> str:
    """Resolve FFmpeg exactly as 2.4.1 did.

    Returns:
        A path to an ``ffmpeg.exe`` shipped beside this file on Windows, or the
        bare ``ffmpeg`` name that relies on ``PATH``.
    """
    if os.name == "nt":
        local = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ffmpeg.exe")
        return local if os.path.exists(local) else "ffmpeg"
    return "ffmpeg"


def _duration_from_stderr(stderr: str) -> float | None:
    """Return the input duration FFmpeg printed in its banner, in seconds.

    Args:
        stderr: FFmpeg's stderr from the ebur128 run.

    Returns:
        The duration in seconds, or ``None`` when no ``Duration:`` line was
        printed.
    """
    match = re.search(r"Duration:\s+(\d+):(\d+):(\d+(?:\.\d+)?)", stderr)
    if match is None:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def _probe_duration_seconds(file_path: str) -> float | None:
    """Ask ffprobe for the container duration when FFmpeg printed none.

    Args:
        file_path: Absolute path to the audio file.

    Returns:
        The duration in seconds, or ``None`` when the probe cannot supply one.
    """
    try:
        result = run_secure_subprocess(
            "ffprobe",
            [
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                os.path.normpath(file_path),
            ],
            capture_output=True,
            timeout=WORKER_TIMEOUT_SECS,
            check=False,
            log_failure=False,
        )
        text = (result.stdout or "").strip()
        return float(text) if text else None
    except (
        FileNotFoundError,
        SubprocessSecurityError,
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
    ) as exc:
        logger.warning("Could not read the duration of %s: %s", file_path, exc)
        return None


def _concat_list_line(path: str) -> str:
    """Format one FFmpeg concat-demuxer ``file`` directive.

    Args:
        path: Absolute path to the audio file.

    Returns:
        One ``file '<path>'`` line, newline-terminated.
    """
    escaped = os.path.normpath(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped}'\n"


def measure_album_loudness(paths: list[str]) -> float | None:
    """Measure a folder's tracks as one combined signal, in a single pass.

    Args:
        paths: Absolute paths of the folder's tracks, in album order.

    Returns:
        The combined integrated loudness in LUFS, or ``None`` when FFmpeg could
        not measure it.
    """
    if not paths:
        return None

    handle = tempfile.NamedTemporaryFile(
        "w", suffix=".concat.txt", delete=False, encoding="utf-8"
    )
    try:
        with handle as stream:
            for path in paths:
                stream.write(_concat_list_line(path))
        ffmpeg = _ffmpeg_exe()
        result = run_secure_subprocess(
            ffmpeg,
            [
                "-hide_banner",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                handle.name,
                "-af",
                "ebur128=peak=true",
                "-f",
                "null",
                "-",
            ],
            capture_output=True,
            encoding="utf-8",
            errors="ignore",
            timeout=WORKER_TIMEOUT_SECS,
            check=False,
        )
        matches = re.findall(r"I:\s+([-+]?\d+\.?\d*)\s+LUFS", result.stderr)
        if not matches:
            logger.warning(
                "ffmpeg returned no combined album loudness for %d tracks "
                "(exit code %d); falling back to duration weighting",
                len(paths),
                result.returncode,
            )
            return None
        return float(matches[-1])
    except (
        FileNotFoundError,
        SubprocessSecurityError,
        OSError,
        ValueError,
        subprocess.TimeoutExpired,
    ) as exc:
        logger.warning("Could not measure the combined album signal: %s", exc)
        return None
    finally:
        try:
            os.unlink(handle.name)
        except OSError:
            pass


def get_metrics(file_path: str) -> tuple[float | None, float, float | None]:
    """Analyse one audio file with FFmpeg ebur128 and return measurements.

    Args:
        file_path: Absolute path to the audio file.

    Returns:
        ``(integrated_lufs, true_peak_dbfs, duration_seconds)``; ``None`` for
        the loudness when measurement failed, ``0.0`` for an absent peak and
        ``None`` for an unknown duration.
    """
    ffmpeg = _ffmpeg_exe()

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
        duration_s = _duration_from_stderr(result.stderr)
        if duration_s is None:
            duration_s = _probe_duration_seconds(file_path)

        if lufs is None:
            logger.warning(
                "ffmpeg returned no LUFS measurement for %s (exit code %d).\n"
                "ffmpeg stderr: %s",
                file_path,
                result.returncode,
                result.stderr[-500:] if result.stderr else "(empty)",
            )

        return lufs, peak, duration_s

    except (FileNotFoundError, SubprocessSecurityError):
        logger.error(
            "ffmpeg executable not found at '%s'. "
            "Install ffmpeg and ensure it is on the system PATH, "
            "or place the ffmpeg binary alongside the "
            "replaygain_analyzer/core/ module.",
            ffmpeg,
        )
        return None, 0.0, None

    except subprocess.TimeoutExpired:
        logger.warning("ffmpeg timed out processing: %s", file_path)
        return None, 0.0, None

    except (OSError, subprocess.CalledProcessError) as exc:
        logger.error("Unexpected error measuring %s: %s", file_path, exc, exc_info=True)
        return None, 0.0, None
