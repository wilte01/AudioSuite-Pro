"""subprocess_utils.py — Cross-platform subprocess helpers for AudioSuite-Pro."""

from __future__ import annotations

import os
import subprocess


def get_startupinfo() -> subprocess.STARTUPINFO | None:
    """Return a STARTUPINFO that hides console windows on Windows."""
    if os.name == "nt":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        return si
    return None


def creation_flags() -> int:
    """Return CREATE_NO_WINDOW on Windows, 0 otherwise (for Popen)."""
    if os.name == "nt":
        return subprocess.CREATE_NO_WINDOW
    return 0
