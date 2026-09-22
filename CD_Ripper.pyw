"""
CD_Ripper.pyw — Launcher for CD Ripper.

Pre-loads ``discid.dll`` on Windows so that the ``discid`` package
can find it without path configuration.
"""

import sys
import os
import ctypes

_suite_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("cd_ripper")

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
                pass

    import tkinter as tk
    from audio_suite_shared.styles import bootstrap_theme
    from cd_ripper.app import CDRipperApp

    root = tk.Tk()
    bootstrap_theme()
    CDRipperApp(root)
    root.mainloop()
