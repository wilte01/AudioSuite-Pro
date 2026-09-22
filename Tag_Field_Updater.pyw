#!/usr/bin/env python3
"""
Tag_Field_Updater.pyw - Launcher for Tag Field Updater.

Imports directly from the tag_field_updater package.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("tag_field_updater")

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
            pass
