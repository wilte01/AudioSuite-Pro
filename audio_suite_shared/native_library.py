"""
native_library.py — Loads a native library the suite ships beside itself.

The CD Ripper pre-loads ``discid.dll`` before importing the ``discid`` wheel, so
the package finds its native library without any path configuration.  None of
that sequence is CD-Ripper-specific: it is "locate a file the suite ships, then
hand it to ctypes", and the launcher used to spell all of it itself.

Location goes through :func:`audio_suite_shared.suite_paths.suite_path`, the one
resolver for a suite-owned file, so a packaged build loads the copy it ships
rather than looking beside the entry point.  Loading is deliberately non-fatal:
a missing, wrong-architecture or truncated library must not stop the caller,
because the dependent package may still find its own copy through the system
linker.  The failure is logged at DEBUG — the outcome is not an error, but the
record is what turns a later opaque "could not load" into a traceable cause.

Changed in 2.5.0: new module. ``CD_Ripper.pyw`` located ``discid.dll`` and called
``ctypes`` inline; that pair is now here, and a second tool that ships a native
library asks for it instead of copying the sequence.
"""

from __future__ import annotations

import ctypes
import logging

from .suite_paths import suite_path

__all__ = ["load_shipped_library"]

_log = logging.getLogger(f"audio_suite.{__name__}")


def load_shipped_library(filename: str) -> bool:
    """Load a native library the suite ships at its installation root.

    The file's presence is the only gate: there is no platform check, because a
    library that is installed is the one to load, and one that is absent is
    simply not there.  A Windows DLL sitting in a Linux checkout fails to load
    and reports False, which is the same outcome a ``sys.platform`` test would
    have produced.

    Args:
        filename: The library's file name at the suite root, e.g.
            ``"discid.dll"``.  It is resolved with
            :func:`audio_suite_shared.suite_paths.suite_path`, so the working
            directory cannot change which installation answers.

    Returns:
        True when the library was loaded, False when it is absent or fails to
        load.  Callers treat False as "the package will try to locate it
        itself", never as a fatal condition.
    """
    path = suite_path(filename)
    if not path.is_file():
        _log.debug("Shipped library %s is not installed at %s", filename, path)
        return False
    try:
        ctypes.CDLL(str(path))
    except OSError:
        _log.debug(
            "Could not load %s; the dependent package will try to locate the "
            "library itself",
            path,
            exc_info=True,
        )
        return False
    return True
