"""
Tag_Editor.pyw — Launcher for the Tag Editor window.

The .pyw extension causes Windows to run this via pythonw.exe, suppressing
the console window.  On macOS/Linux launch with::

    python Tag_Editor.pyw

``guard_or_exit()`` runs before any tool import: it byte-compiles every
first-party source file so a syntax/indentation error in the tool chain
surfaces as a clear blocking dialog instead of an opaque log traceback.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_script_dir)

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("tag_editor")

from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.styles import bootstrap_theme
from tag_editor.utils.cli_args import parse
import tkinter as tk
from tag_editor.ui.app import TagEditorApp

if __name__ == "__main__":
    args = parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    TagEditorApp(root, directory=args.folder_path, live_mode=args.live_mode)
    root.mainloop()
