"""
Key_Detector.pyw — Launcher for Key Detector.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("key_detector")

from audio_suite_shared.launcher import parse_cli_args
from key_detector.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from key_detector.app import KeyDetectorApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    KeyDetectorApp(root)
    root.mainloop()
