"""
ReplayGain_Analyzer.pyw — Launcher for ReplayGain Analyzer.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("replaygain_analyzer")

from audio_suite_shared.launcher import parse_cli_args
from replaygain_analyzer.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from replaygain_analyzer.app import ReplayGainAnalyzerApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    ReplayGainAnalyzerApp(root)
    root.mainloop()
