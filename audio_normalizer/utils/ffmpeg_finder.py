"""
ffmpeg_finder.py
Locates the FFmpeg executable used by the audio normalizer.

Replaces the mutable global FFMPEG_PATH from the original monolith with a
clean module-level singleton initialised once at import time.  Windows
console suppression for subprocess calls is provided by
``audio_suite_shared.subprocess_utils.get_startupinfo``.
"""

import os
import shutil
import sys


def _find_ffmpeg() -> str:
    """
    Search for ffmpeg in order of preference:
      1. System PATH
      2. Alongside this script / frozen executable
      3. Windows fallback location C:\\ffmpeg\\bin\\ (Windows only)
    Returns the resolved absolute path, or "ffmpeg" as a last resort
    (letting the OS raise a clear error if it truly isn't installed).
    """
    # 1 — system PATH
    found = shutil.which("ffmpeg")
    if found:
        return os.path.abspath(found)

    # 2 — next to the script / frozen exe
    base = os.path.dirname(
        sys.executable if getattr(sys, "frozen", False) else os.path.abspath(__file__)
    )
    # Binary name differs by platform (Windows uses .exe extension)
    local_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
    local = os.path.join(base, local_name)
    # Existence alone would also accept a *directory* named like the binary,
    # handing every caller an argv[0] that can only ever fail at exec time
    # with an opaque error, so the copy must be a real executable file.
    if os.path.isfile(local) and os.access(local, os.X_OK):
        return os.path.abspath(local)

    # 3 — Windows common install location (Windows only)
    if sys.platform == "win32":
        fallback = r"C:\ffmpeg\bin\ffmpeg.exe"
        if os.path.exists(fallback):
            return fallback

    # Not found — return bare name and let callers surface the error naturally
    return "ffmpeg"


# Module-level singletons - resolved once, reused everywhere
FFMPEG_PATH: str = _find_ffmpeg()
