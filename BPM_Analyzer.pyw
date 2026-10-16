"""
BPM_Analyzer.pyw — Launcher for BPM Analyzer.

``bootstrap_theme()`` is called before *every* ``tk.Tk()`` creation so that
the ``clam`` theme is locked in before any ttk widgets are created,
preventing the Windows ``vista`` theme from taking over.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("bpm_analyzer")

from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.styles import bootstrap_theme
from bpm_analyzer.utils.cli_args import parse
import tkinter as tk
from bpm_analyzer.app import BPMAnalyzerApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    BPMAnalyzerApp(root)
    root.mainloop()
