"""
Audio_Enhancer.pyw — Launcher for Audio Enhancer.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("audio_enhancer")

from audio_enhancer.app import main

if __name__ == "__main__":
    main()
