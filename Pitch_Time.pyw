"""
Pitch_Time.pyw — Launcher for the Pitch / Time tool.

Changes each file's playback speed (pitch kept) or its pitch (length kept),
writing the result beside its source under a name that carries the setting.

Changed in 2.7.0: new tool (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit

guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("pitch_time")

if __name__ == "__main__":
    from pitch_time.app import main

    main()
