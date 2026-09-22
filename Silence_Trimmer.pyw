"""
Silence_Trimmer.pyw — Launcher for Silence Trimmer.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("silence_trimmer")

from audio_suite_shared.launcher import parse_cli_args
from silence_trimmer.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from silence_trimmer.app import SilenceTrimmerApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    SilenceTrimmerApp(root)
    root.mainloop()
