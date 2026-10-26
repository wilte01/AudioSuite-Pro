"""core/drive_control.py — open a CD tray and reveal a ripped file.

Both actions used to be raw ``subprocess.Popen`` calls inside
``cd_ripper/ui/results_tab.py``: the Windows eject built a **PowerShell command
string** by f-string interpolation, which is precisely the pattern SECURITY.md
says the suite does not contain, and neither call could be exercised without a
display.

They live here instead, with no Tk imports, so the argument list is assertable
and no shell is involved:

* **Windows eject** goes through MCI (``mciSendStringW``): a fixed command
  built from a validated single drive letter, and no process at all.
* **POSIX eject** runs ``eject <device>`` through
  ``audio_suite_shared.secure_subprocess``.
* **Reveal** runs ``explorer.exe /select,<file>`` on Windows and
  ``xdg-open <directory>`` elsewhere, both as fixed argument lists.

Every entry point validates its input before a command is built, so a
tag-derived or user-typed string never reaches an OS call.

Changed in 2.1.4: new module — replaces the PowerShell eject and the raw
Popen calls in the results tab (audit R-08, plan C3).
"""

from __future__ import annotations

import ctypes
import os
import re
import sys
from pathlib import Path
from typing import Any

from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.secure_subprocess import run_secure_subprocess

#: ``"D"``, ``"D:"`` - one letter, optionally followed by the colon.
_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:?$")

#: ``/dev/sr0``, ``/dev/cdrom``, ``/dev/disk/by-id/...`` - a device node only.
_POSIX_DEVICE = re.compile(r"^/dev/[A-Za-z0-9/_.-]+$")


def _drive_letter(drive: str) -> str:
    """Return the bare, upper-case letter of a Windows drive designator.

    Args:
        drive: ``"D"``, ``"D:"`` or ``"D:\\"``.

    Returns:
        The single letter, e.g. ``"D"``.

    Raises:
        AudioSuiteError: If *drive* is not a single drive letter.
    """
    cleaned = drive.strip().rstrip("\\/")
    if not _WINDOWS_DRIVE.match(cleaned):
        raise AudioSuiteError(f"Not a drive designator: {drive!r}")
    return cleaned.rstrip(":").upper()


def _device_path(drive: str) -> str:
    """Return *drive* unchanged if it is a POSIX CD device node.

    Args:
        drive: A device path such as ``"/dev/sr0"``.

    Returns:
        The validated path.

    Raises:
        AudioSuiteError: If *drive* is not a device node under ``/dev``.
    """
    path = drive.strip()
    # The character class allows dots (``/dev/disk/by-id/...``), so a ``..``
    # component is refused explicitly rather than by the pattern alone.
    if not _POSIX_DEVICE.match(path) or ".." in Path(path).parts:
        raise AudioSuiteError(f"Not a CD device path: {drive!r}")
    return path


def eject_drive(drive: str) -> None:
    """Open the tray of *drive*.

    Args:
        drive: Windows drive designator (``"D:"``) or POSIX device
            (``"/dev/sr0"``).

    Raises:
        AudioSuiteError: If *drive* is not a recognised designator, or Windows
            refuses the eject request.
        SubprocessSecurityError: If the POSIX ``eject`` call is refused by the
            wrapper.
    """
    if sys.platform == "win32":
        letter = _drive_letter(drive)
        # ``windll`` exists only on Windows; the local annotation keeps the
        # attribute access type-checkable on the POSIX legs, and the command is
        # a fixed string plus one validated letter - no user text, no shell.
        windll: Any = getattr(ctypes, "windll", None)
        if windll is None:  # pragma: no cover - nt without windll is impossible
            raise AudioSuiteError("Windows drive control is unavailable")
        result = windll.winmm.mciSendStringW(f"set {letter}: door open", None, 0, None)
        if result != 0:
            raise AudioSuiteError(
                f"Windows could not open the tray for {letter}: (MCI error {result})"
            )
        return

    run_secure_subprocess(
        "eject", [_device_path(drive)], capture_output=True, check=False
    )


def reveal_in_file_manager(path: str) -> None:
    """Show *path* selected in the platform file manager.

    Args:
        path: The ripped file to reveal.

    Raises:
        SubprocessSecurityError: If the wrapper refuses the call (for example
            a path containing a character it rejects).
    """
    if sys.platform == "win32":
        # A fixed argument list, not a command string: explorer's /select,
        # switch takes the file path as the remainder of this one argument.
        run_secure_subprocess(
            "explorer.exe", [f"/select,{path}"], capture_output=True, check=False
        )
        return

    run_secure_subprocess(
        "xdg-open", [os.path.dirname(path)], capture_output=True, check=False
    )
