"""
Library_Stats.pyw — Launcher for Library Statistics Dashboard.

Scans your music library by reading existing tags (BPM, key, genre, mood, etc.)
and displays the aggregated data in an interactive GUI dashboard.

Changed in 1.0.1: routes the launcher through ``library_stats.app.main`` so the driver's
argv is parsed.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("library_stats")

if __name__ == "__main__":
    from library_stats.app import main
    main()