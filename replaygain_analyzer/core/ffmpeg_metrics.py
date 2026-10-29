"""
ffmpeg_metrics.py
Measures integrated loudness (LUFS), true peak (dBFS) and duration of an
audio file using FFmpeg's ebur128 filter.

Pure function — no tkinter imports, no global state.
Also owns get_resource_path() for PyInstaller compatibility.

FFmpeg resolution order (Windows)
----------------------------------
1. Beside this file: replaygain_analyzer/core/ffmpeg.exe  (legacy local copy)
2. System PATH: 'ffmpeg'  (consistent with cd_ripper/ui/setup_tab.py fallback)

On non-Windows the system 'ffmpeg' is always used.

Changed in 2.1.7: ``measure_album_loudness`` measures a folder as one
concatenated signal in a single pass — ReplayGain 2.0's actual album definition
— and returns ``None`` so the caller falls back to the duration-weighted formula
only when that read fails (A1).

Changed in 2.1.2: returns the file's duration as a third measurement. Album
ReplayGain is the loudness of the album's combined signal, so it needs each
track's length, not just its integrated loudness (audit R-01). The duration is
parsed from the same ebur128 run's stderr; only a missing Duration line costs a
second `ffprobe` call, and a probe failure is reported as None (the caller
counts that file as an error rather than weighting it with a guessed length).
"""

import logging
import os
import re
import subprocess
import sys
import tempfile

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


def _duration_from_stderr(stderr: str) -> float | None:
    """Return the input duration FFmpeg printed in its banner, in seconds.

    Args:
        stderr: FFmpeg's stderr from the ebur128 run.

    Returns:
        The duration in seconds, or ``None`` when no ``Duration:`` line was
        printed (a pipe input or an unreadable container).
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

    FFmpeg's demuxer uses single-quoted entries and doubles nothing: a literal
    quote is written as ``'\\''``. Paths use forward slashes so the directive
    is identical on Windows and POSIX hosts.

    Args:
        path: Absolute path to the audio file.

    Returns:
        One ``file '<path>'`` line, newline-terminated.
    """
    escaped = os.path.normpath(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{escaped}'\n"


def measure_album_loudness(paths: list[str]) -> float | None:
    """Measure a folder's tracks as one combined signal, in a single pass.

    ReplayGain 2.0 defines album loudness as the integrated loudness of the
    album's combined signal, so the FFmpeg concat demuxer feeds every track
    through ``ebur128`` as one stream. This is a second decode of the album
    (Phase 1 already decodes each track for its own measurement), which is the
    cost the approximation traded away; A1's benchmark measured the accuracy it
    bought and found the weighted formula 2.33 dB out on a silent-tail album and
    3.00 dB out on a 20 s loud + 20 s quiet pair
    (``tests/test_file_processor.py::TestAlbumGainBenchmark``).

    Args:
        paths: Absolute paths of the folder's tracks, in album order.

    Returns:
        The combined integrated loudness in LUFS, or ``None`` when FFmpeg could
        not measure it (the caller then falls back to the duration-weighted
        formula rather than failing the folder's tag write).
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
        ffmpeg = _get_ffmpeg_exe()
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
    """
    Analyse one audio file with FFmpeg ebur128 and return measurements.

    Args:
        file_path: Absolute path to the audio file.

    Returns:
        ``(integrated_lufs, true_peak_dbfs, duration_seconds)``.
        ``integrated_lufs`` is None if measurement failed.
        ``true_peak_dbfs`` defaults to 0.0 on failure.
        ``duration_seconds`` is None when neither FFmpeg's input banner nor
        ffprobe reported one; callers must treat that as a failed measurement,
        never as zero.
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
