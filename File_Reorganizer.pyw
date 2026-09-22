#!/usr/bin/env python3
"""
File_Reorganizer.pyw - Launcher for Tag-Based File Reorganizer.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("file_reorganizer")

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
            pass
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
            pass
