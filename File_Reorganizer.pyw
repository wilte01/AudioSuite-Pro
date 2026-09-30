#!/usr/bin/env python3
"""
File_Reorganizer.pyw - Launcher for Tag-Based File Reorganizer.
"""

import logging

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("file_reorganizer")

logger = logging.getLogger(__name__)

if __name__ == "__main__":
    try:
        from file_reorganizer import main

        main()
    except ImportError as e:
        try:
            import tkinter as tk
            from tkinter import messagebox

            _root = tk.Tk()
            _root.withdraw()
            messagebox.showerror(
                "Import Error",
                f"Error importing file_reorganizer:\n{e}\n\n"
                "Please ensure file_reorganizer/ is in the same directory.",
            )
            _root.destroy()
        except Exception:
            # The error dialog is best-effort: a broken Tk cannot be reported
            # through Tk. Without this the original failure vanishes entirely.
            logger.exception(
                "Could not show the import-error dialog; the underlying "
                "ImportError was %s",
                e,
            )
    except Exception as e:
        try:
            import tkinter as tk
            from tkinter import messagebox

            _root = tk.Tk()
            _root.withdraw()
            messagebox.showerror(
                "Startup Error",
                f"Error starting File Reorganizer:\n{e}",
            )
            _root.destroy()
        except Exception:
            # See above: the dialog failing must not hide the startup error.
            logger.exception(
                "Could not show the startup-error dialog; the underlying "
                "startup failure was %s",
                e,
            )
