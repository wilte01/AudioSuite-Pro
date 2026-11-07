"""ffmpeg.py
Locates the FFmpeg and FFprobe executables the suite runs.

One resolver for every tool. The Audio Normalizer, Audio Joiner, Audio
Refinery, Track Splitter, the Audio Enhancer's Opus/MPEG-4 lane and the
shared analysis loader all import these values instead of searching ``PATH``
themselves; a second lookup can only ever disagree with this one, because the
binaries are chosen from the same three sources but cached at a different
moment.

Search order, per binary:

  1. the system ``PATH``
  2. beside this module, or beside the frozen executable
  3. ``C:\\ffmpeg\\bin`` on Windows

``find_ffmpeg``/``find_ffprobe`` answer ``None`` when every source misses, so
a caller that can degrade (the analysis loader's decode fallback) asks a
question instead of parsing a sentinel. The argv[0] singletons fall back to
the bare name, letting the OS raise ``FileNotFoundError`` with the name the
user has to install.

Changed in 2.5.0: new module. The resolver moved here from
``audio_normalizer/utils/ffmpeg_finder.py`` (plan D-38) because two tools
imported it from a third tool's package and three more re-implemented it; the
reuse lock ``tests/test_shared_code_reuse.py`` now fails on a new copy.
"""

from __future__ import annotations

import os
import shutil
import sys

from audio_suite_shared.exceptions import AudioMissingDependencyError

#: The executable names, and the bare fallback each singleton uses.
FFMPEG: str = "ffmpeg"
FFPROBE: str = "ffprobe"

#: The Windows location FFmpeg's own installer uses, probed last.
WINDOWS_FALLBACK_DIR: str = r"C:\ffmpeg\bin"


def _binary_name(name: str) -> str:
    """Return *name* with the platform's executable extension."""
    return f"{name}.exe" if sys.platform == "win32" else name


def _search(name: str) -> str | None:
    """Return the absolute path of *name*, or None when no source has it.

    Args:
        name: The bare executable name, e.g. ``"ffmpeg"``.

    Returns:
        The absolute path of the first hit, or None. The copy found beside
        the module must be a real executable file: existence alone would also
        accept a *directory* named like the binary, handing callers an argv[0]
        that can only fail at exec time with an opaque error.
    """
    found = shutil.which(name)
    if found:
        return os.path.abspath(found)

    base = os.path.dirname(
        sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    )
    local = os.path.join(base, _binary_name(name))
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return os.path.abspath(local)

    if sys.platform == "win32":
        fallback = os.path.join(WINDOWS_FALLBACK_DIR, _binary_name(name))
        if os.path.exists(fallback):
            return fallback

    return None


def find_ffmpeg() -> str | None:
    """Return the FFmpeg binary's path, or None when it is not installed."""
    return _search(FFMPEG)


def find_ffprobe() -> str | None:
    """Return the FFprobe binary's path, or None when it is not installed."""
    return _search(FFPROBE)


def require_ffmpeg() -> str:
    """Return the FFmpeg binary's path, or raise if it is not installed.

    Raises:
        AudioMissingDependencyError: If no source has FFmpeg. Raised
            explicitly rather than letting a subprocess's
            ``FileNotFoundError`` propagate, because the suite maps a missing
            *file* to ``AudioFileNotFoundError`` — which tools treat as a
            silent skip. The audio file is fine here; the tool is missing.
    """
    path = find_ffmpeg()
    if path is None:
        raise AudioMissingDependencyError(
            "ffmpeg is not installed or not on PATH — the suite needs it to "
            "decode and encode audio. Install ffmpeg and ensure it is on PATH.",
            dependency=FFMPEG,
        )
    return path


def require_ffprobe() -> str:
    """Return the FFprobe binary's path, or raise if it is not installed.

    Raises:
        AudioMissingDependencyError: If no source has FFprobe.
    """
    path = find_ffprobe()
    if path is None:
        raise AudioMissingDependencyError(
            "ffprobe is not installed or not on PATH — the suite needs it to "
            "read stream metadata. Install ffmpeg (which includes ffprobe) "
            "and ensure it is on PATH.",
            dependency=FFPROBE,
        )
    return path


# Module-level singletons - resolved once, reused everywhere.
FFMPEG_PATH: str = find_ffmpeg() or FFMPEG
FFPROBE_PATH: str = find_ffprobe() or FFPROBE
