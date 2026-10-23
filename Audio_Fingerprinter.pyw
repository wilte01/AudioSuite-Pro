"""
Audio_Fingerprinter.pyw — Launcher for Audio Fingerprinter.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("audio_fingerprinter")

from audio_suite_shared.launcher import parse_cli_args
from audio_fingerprinter.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from audio_fingerprinter.app import FingerprinterApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    FingerprinterApp(root)
    root.mainloop()