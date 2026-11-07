"""
Audio_Joiner.pyw — Launcher for the Audio Joiner.

Joins a folder's segments end to end, optionally with a silence gap or an
equal-power crossfade at every boundary, and copies the first segment's tags
onto the result.

Changed in 2.5.0: new tool (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("audio_joiner")

if __name__ == "__main__":
    from audio_joiner.app import main
    main()
