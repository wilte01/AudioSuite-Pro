"""
main.pyw — Entry point for Metadata Scrubber & Tagger.
"""

import tkinter as tk

from audio_suite_shared.app_bootstrap import configure_logging
from metadata_scrubber.app import MetadataScrubberApp

if __name__ == "__main__":
    configure_logging("metadata_scrubber")
    root = tk.Tk()
    MetadataScrubberApp(root)
    root.mainloop()
