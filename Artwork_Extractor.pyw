"""Artwork_Extractor.pyw — Launcher for the Artwork Extractor."""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit

guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("artwork_extractor")

from artwork_extractor.app import main

if __name__ == "__main__":
    main()
