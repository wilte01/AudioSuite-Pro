"""
Master_Driver.pyw — Central orchestrator for the Audio Suite.

Changes working directory to the suite root so that subprocess-launched
tools resolve paths correctly.  ``bootstrap_theme()`` MUST run before the
``master_driver.app`` import, because the app module creates ttk widgets
at import time and the ``clam`` theme must already be locked in.

``guard_or_exit()`` runs before any tool import: it byte-compiles every
first-party source file so a syntax/indentation error in the tool chain
surfaces as a clear blocking dialog instead of an opaque log traceback.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))
os.chdir(_script_dir)

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("master_driver")

from audio_suite_shared.styles import bootstrap_theme
import tkinter as tk

root = tk.Tk()
bootstrap_theme()

from master_driver.app import AudioSuiteDriver
AudioSuiteDriver(root)
root.mainloop()
