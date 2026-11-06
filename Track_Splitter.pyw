"""
Track_Splitter.pyw — Launcher for the Track Splitter.

Splits one long recording into tracks at its silent gaps, naming them from a
pattern and optionally writing a CUE sheet beside the outputs.

Changed in 2.5.0: new tool (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E4).
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("track_splitter")

if __name__ == "__main__":
    from track_splitter.app import main
    main()
