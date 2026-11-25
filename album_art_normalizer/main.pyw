"""
main.pyw
Entry point for Album Art Normalizer.
Nothing lives here except the minimal bootstrap.
"""

import tkinter as tk

from album_art_normalizer.app import ArtNormalizerApp
from audio_suite_shared.app_bootstrap import configure_logging

if __name__ == "__main__":
    configure_logging("album_art_normalizer")
    root = tk.Tk()
    ArtNormalizerApp(root)
    root.mainloop()
