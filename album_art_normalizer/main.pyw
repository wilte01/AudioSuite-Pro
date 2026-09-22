"""
main.pyw
Entry point for Album Art Normalizer.
Nothing lives here except the minimal bootstrap.
"""

import tkinter as tk
from album_art_normalizer.app import ArtNormalizerApp

if __name__ == "__main__":
    root = tk.Tk()
    ArtNormalizerApp(root)
    root.mainloop()
