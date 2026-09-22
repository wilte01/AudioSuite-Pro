"""
Mood_Analyzer.pyw — Launcher for Mood Analyzer.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("mood_analyzer")

from audio_suite_shared.launcher import parse_cli_args
from mood_analyzer.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from mood_analyzer.app import MoodAnalyzerApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    MoodAnalyzerApp(root)
    root.mainloop()