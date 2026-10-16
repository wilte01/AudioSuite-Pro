"""
Audio_Refinery.pyw — Launcher for Audio Refinery.

The .pyw extension causes Windows to run this via pythonw.exe,
suppressing the console window.  On macOS/Linux launch with::

    python Audio_Refinery.pyw
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("audio_refinery")

from audio_refinery.app import main

if __name__ == "__main__":
    main()
