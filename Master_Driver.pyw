"""
Master_Driver.pyw — Central orchestrator for the Audio Suite.

Launches each tool with an absolute script path, the root coming from
``suite_paths.suite_root``, so it does not change the working directory.
``bootstrap_theme()`` MUST run before the ``master_driver.app`` import,
because the app module creates ttk widgets at import time and the
``clam`` theme must already be locked in.

Changed in 2.5.0: dropped the ``os.chdir(_script_dir)`` workaround; a
relative script path is joined with the installation root instead.

``guard_or_exit()`` runs before any tool import: it byte-compiles every
first-party source file so a syntax/indentation error in the tool chain
surfaces as a clear blocking dialog instead of an opaque log traceback.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit

guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("master_driver")

import tkinter as tk

from audio_suite_shared.styles import bootstrap_theme

root = tk.Tk()
bootstrap_theme()

from master_driver.app import AudioSuiteDriver

AudioSuiteDriver(root)
root.mainloop()
