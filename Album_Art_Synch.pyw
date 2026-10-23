"""
Album_Art_Synch.pyw — Launcher for Album Art Sync.

Changes working directory to the suite root so that relative config paths
(art_cache/, config files) resolve correctly regardless of how the script
was launched.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_script_dir)

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("album_art_sync")

from audio_suite_shared.launcher import parse_cli_args
from album_art_sync.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from album_art_sync.app import AudioSuiteV6

if __name__ == "__main__":
    pre_parsed = parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    AudioSuiteV6(root, pre_parsed=pre_parsed)
    root.mainloop()
