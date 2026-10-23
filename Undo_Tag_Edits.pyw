"""
Undo_Tag_Edits.pyw — Launcher for the Undo Tag Edits window.

The .pyw extension causes Windows to run this via pythonw.exe, suppressing
the console window.  On macOS/Linux launch with::

    python Undo_Tag_Edits.pyw

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
configure_logging("undo_tag_edits")

from audio_suite_shared.undo_gui import main

if __name__ == "__main__":
    main()
