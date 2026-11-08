"""
Channel_Tools.pyw — Launcher for Channel Tools.

Applies one channel rule (mono downmix, dual mono, phase invert, mid/side,
stereo width) to every audio file in a folder, rewriting them in place.

Changed in 2.5.0: new tool (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit

guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("channel_tools")

if __name__ == "__main__":
    from channel_tools.app import main

    main()
