"""
Genre_Sync.pyw — Launcher for Genre Sync.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("genre_sync")

from audio_suite_shared.launcher import parse_cli_args
from genre_sync.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from genre_sync.app import GenreSetterApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    GenreSetterApp(root)
    root.mainloop()
