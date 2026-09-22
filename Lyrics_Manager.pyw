"""
Lyrics_Manager.pyw — Launcher for the Lyrics Manager window.

The .pyw extension causes Windows to run this via pythonw.exe, suppressing
the console window.  On macOS/Linux launch with::

    python Lyrics_Manager.pyw

``guard_or_exit()`` runs before any tool import: it byte-compiles every
first-party source file so a syntax/indentation error in the tool chain
surfaces as a clear blocking dialog instead of an opaque log traceback.

``bootstrap_theme()`` is called before *every* ``tk.Tk()`` creation so that
the ``clam`` theme is locked in before any ttk widgets are created,
preventing the Windows ``vista`` theme from taking over.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("lyrics_manager")

from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.styles import bootstrap_theme
from lyrics_manager.utils.cli_args import parse
import tkinter as tk
from lyrics_manager.app import LyricsManagerApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    LyricsManagerApp(root)
    root.mainloop()