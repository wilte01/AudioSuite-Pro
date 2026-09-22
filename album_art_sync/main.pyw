"""
main.pyw — Entry point for Album Art Synchronizer v6.0.
"""

import tkinter as tk
from album_art_sync.app import AudioSuiteV6

if __name__ == "__main__":
    root = tk.Tk()
    AudioSuiteV6(root)
    root.mainloop()
