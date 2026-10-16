#!/usr/bin/env python3
"""
Tag_Field_Updater.pyw - Launcher for Tag Field Updater.

Imports directly from the tag_field_updater package.
"""

import logging
import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("tag_field_updater")

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        from tag_field_updater.ui.app import main

        main()
    except Exception as e:
        try:
            import tkinter as tk
            from tkinter import messagebox

            _root = tk.Tk()
            _root.withdraw()
            messagebox.showerror(
                "Startup Error",
                f"Error starting Tag Field Updater:\n{e}",
            )
            _root.destroy()
        except Exception:
            # The error dialog is best-effort: a broken Tk cannot be reported
            # through Tk. Without this the original failure vanishes entirely.
            logger.exception(
                "Could not show the startup-error dialog; the underlying "
                "startup failure was %s",
                e,
            )
