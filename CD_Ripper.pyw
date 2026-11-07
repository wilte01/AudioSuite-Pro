"""
CD_Ripper.pyw — Launcher for CD Ripper.

Loads the shipped ``discid.dll`` through the shared native-library
helper so the ``discid`` package finds it without configuration.

Changed in 1.0.1: routes the launcher through ``cd_ripper.app.main`` so the driver's
argv is parsed.
Changed in 2.5.0: ``discid.dll`` is located through the shared suite-root
resolver, so a packaged build finds the copy it ships (plan D-44).
Changed in 2.5.0: the locate-and-load pair is
``audio_suite_shared.native_library`` - this launcher names the file
and nothing else.
"""

import os

_suite_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_suite_dir)

from audio_suite_shared.preflight import guard_or_exit

guard_or_exit(_suite_dir)

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("cd_ripper")

from audio_suite_shared.native_library import load_shipped_library

if __name__ == "__main__":
    # discid finds its own library through the system linker on macOS
    # and Linux; the Windows wheel needs this copy, and loading it first
    # is what makes an install work without path configuration.
    load_shipped_library("discid.dll")

    from cd_ripper.app import main

    main()
