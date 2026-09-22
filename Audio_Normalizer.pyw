"""
Audio_Normalizer.pyw — Launcher for Audio Normalizer.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("audio_normalizer")

from audio_suite_shared.launcher import parse_cli_args
from audio_normalizer.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from audio_normalizer.app import AudioNormalizerApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    AudioNormalizerApp(root)
    root.mainloop()
