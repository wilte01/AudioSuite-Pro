"""
ffmpeg_metrics.py
ReplayGain's Loudness (LUFS), true peak (dBFS) and duration figures.

Pure function — no tkinter imports, no global state.
Also owns get_resource_path() for PyInstaller compatibility.

FFmpeg resolution order (Windows)
----------------------------------
1. Beside this file: replaygain_analyzer/core/ffmpeg.exe  (legacy local copy)
2. System PATH: 'ffmpeg'  (consistent with cd_ripper/ui/setup_tab.py fallback)

On non-Windows the system 'ffmpeg' is always used.

Changed in 2.4.2: the measurement moved to
``audio_suite_shared.audio_probe``; ``get_metrics`` and
``measure_album_loudness`` are now adapters that keep this tool's return shapes
and failure contract (``None`` loudness, ``0.0`` peak, ``None`` duration) while
the FFmpeg argument lists and the stderr parsing live in one place.  The
equality lock against the previous implementation is
``replaygain_analyzer/tests/_legacy_metrics.py``.

Changed in 2.1.7: ``measure_album_loudness`` measures a folder as one
concatenated signal in a single pass — ReplayGain 2.0's actual album definition
— and returns ``None`` so the caller falls back to the duration-weighted formula
only when that read fails (A1).

Changed in 2.1.2: returns the file's duration as a third measurement. Album
ReplayGain is the loudness of the album's combined signal, so it needs each
track's length, not just its integrated loudness (audit R-01).
"""

import logging
import os
import subprocess
import sys

from audio_suite_shared import audio_probe
from audio_suite_shared.exceptions import AudioExternalToolError, AudioSuiteError
from audio_suite_shared.secure_subprocess import SubprocessSecurityError
from audio_suite_shared.subprocess_utils import get_startupinfo

# Re-export the canonical Windows STARTUPINFO helper under this module's
# historical private name so existing callers and tests keep working.
_get_startupinfo = get_startupinfo

logger = logging.getLogger(__name__)

#: The one warning FFmpeg's absence deserves: it names the binary, the two
#: places it is looked for, and what the user can do about it.
_FFMPEG_MISSING_HINT = (
    "Install ffmpeg and ensure it is on the system PATH, "
    "or place the ffmpeg binary alongside the "
    "replaygain_analyzer/core/ module."
)


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


def measure_album_loudness(paths: list[str]) -> float | None:
    """Measure a folder's tracks as one combined signal, in a single pass.

    The album figure is the integrated loudness of the concatenated album,
    which is ReplayGain 2.0's definition. This is a second decode of the album
    (Phase 1 already decodes each track for its own measurement), which is the
    cost the approximation traded away; A1's benchmark measured it 2.33 dB out on
    a silent-tail album and 3.00 dB out on a 20 s loud + 20 s quiet pair
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
    try:
        combined = audio_probe.measure_album_loudness(paths, ffmpeg=_get_ffmpeg_exe())
    except AudioSuiteError as exc:
        logger.warning(
            "ffmpeg returned no combined album loudness for %d tracks (%s); "
            "falling back to duration weighting",
            len(paths),
            exc.message,
        )
        return None
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("Could not measure the combined album signal: %s", exc)
        return None
    return combined.integrated_lufs


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
    try:
        metrics = audio_probe.measure_loudness(file_path, ffmpeg=ffmpeg)
    except AudioExternalToolError as exc:
        if isinstance(exc.original, FileNotFoundError):
            logger.error(
                "ffmpeg executable not found at '%s'. %s", ffmpeg, _FFMPEG_MISSING_HINT
            )
        elif isinstance(exc.original, subprocess.TimeoutExpired):
            logger.warning("ffmpeg timed out processing: %s", file_path)
        else:
            logger.error(
                "Unexpected error measuring %s: %s", file_path, exc, exc_info=True
            )
        return None, 0.0, None
    except AudioSuiteError as exc:
        logger.warning(
            "ffmpeg returned no LUFS measurement for %s: %s", file_path, exc.message
        )
        return None, 0.0, None
    except (
        OSError,
        ValueError,
        SubprocessSecurityError,
        subprocess.TimeoutExpired,
        subprocess.CalledProcessError,
    ) as exc:
        logger.error("Unexpected error measuring %s: %s", file_path, exc, exc_info=True)
        return None, 0.0, None

    return (
        metrics.integrated_lufs,
        metrics.true_peak_dbtp if metrics.true_peak_dbtp is not None else 0.0,
        metrics.duration_sec,
    )
