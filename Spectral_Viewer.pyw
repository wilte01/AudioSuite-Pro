"""Spectral_Viewer.pyw — Launcher for the Spectral Viewer.

Renders FFT spectrograms for an audio file or folder and exports them as PNG.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1).
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("spectral_viewer")

if __name__ == "__main__":
    from spectral_viewer.app import main
    main()
