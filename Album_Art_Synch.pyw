"""
Album_Art_Synch.pyw — Launcher for Album Art Sync.

Does not change the working directory: the config file and every
suite-owned path resolve from the installation root, so the folder the
icon was double-clicked in cannot decide what this tool reads or writes.

Changed in 2.5.0: dropped the ``os.chdir(_script_dir)`` workaround. It
existed so ``open_help`` could find the guides from a rooted working
directory; help now resolves from ``suite_paths.suite_root``.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit

guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("album_art_sync")

import tkinter as tk

from album_art_sync.app import AudioSuiteV6
from album_art_sync.utils.cli_args import parse
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.styles import bootstrap_theme

if __name__ == "__main__":
    pre_parsed = parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    AudioSuiteV6(root, pre_parsed=pre_parsed)
    root.mainloop()
