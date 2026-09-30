"""
CD_Ripper.pyw — Launcher for CD Ripper.

Pre-loads ``discid.dll`` on Windows so that the ``discid`` package
can find it without path configuration.
"""

import sys
import os
import ctypes
import logging

_suite_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("cd_ripper")

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    # discid.dll is the Windows-specific shared library for the discid package.
    # On macOS/Linux the package finds its own library (libdiscid.so/.dylib) via
    # the system linker, so manual pre-loading is neither needed nor correct.
    if sys.platform == "win32":
        _discid_dll = os.path.join(_suite_dir, "discid.dll")
        if os.path.exists(_discid_dll):
            try:
                ctypes.CDLL(_discid_dll)
            except OSError:
                # Pre-loading is a convenience, not a requirement: a
                # wrong-architecture or corrupt discid.dll must not stop the
                # launcher, and discid may still resolve the library itself.
                # Debug level matches the non-fatal outcome, but the record is
                # what turns a later opaque "could not load discid" into a
                # traceable cause.
                logger.debug(
                    "Could not preload %s; discid will try to locate the "
                    "library itself",
                    _discid_dll,
                    exc_info=True,
                )

    import tkinter as tk
    from audio_suite_shared.styles import bootstrap_theme
    from cd_ripper.app import CDRipperApp

    root = tk.Tk()
    bootstrap_theme()
    CDRipperApp(root)
    root.mainloop()
