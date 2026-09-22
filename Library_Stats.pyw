"""
Library_Stats.pyw — Launcher for Library Statistics Dashboard.

Scans your music library by reading existing tags (BPM, key, genre, mood, etc.)
and displays the aggregated data in an interactive GUI dashboard.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("library_stats")

import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from library_stats.app import LibraryStatsApp

if __name__ == "__main__":
    root = tk.Tk()
    bootstrap_theme()
    LibraryStatsApp(root)
    root.mainloop()
