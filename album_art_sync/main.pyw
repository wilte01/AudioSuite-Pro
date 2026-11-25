"""
main.pyw — Entry point for Album Art Synchronizer v6.0.
"""

import tkinter as tk

from album_art_sync.app import AudioSuiteV6
from audio_suite_shared.app_bootstrap import configure_logging

if __name__ == "__main__":
    configure_logging("album_art_sync")
    root = tk.Tk()
    AudioSuiteV6(root)
    root.mainloop()
