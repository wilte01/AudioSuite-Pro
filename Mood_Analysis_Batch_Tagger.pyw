"""
Mood_Analysis_Batch_Tagger.pyw — Launcher for Mood Analysis Batch Tagger.
"""

import os
import tkinter as tk

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("mood_analysis_batch_tagger")

from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.styles import bootstrap_theme
from mood_analysis_batch_tagger.utils.cli_args import parse
from mood_analysis_batch_tagger.app import MoodAnalysisBatchTaggerApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    MoodAnalysisBatchTaggerApp(root)
    root.mainloop()
