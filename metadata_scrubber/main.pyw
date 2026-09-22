"""
main.pyw — Entry point for Metadata Scrubber & Tagger.
"""

import tkinter as tk
from metadata_scrubber.app import MetadataScrubberApp

if __name__ == "__main__":
    root = tk.Tk()
    MetadataScrubberApp(root)
    root.mainloop()
