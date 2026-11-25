"""
main.pyw
Entry point for BPM Analyzer & Tagger.
Nothing lives here except the minimal bootstrap.
"""

import tkinter as tk

from audio_suite_shared.app_bootstrap import configure_logging
from bpm_analyzer.app import BPMAnalyzerApp

if __name__ == "__main__":
    configure_logging("bpm_analyzer")
    root = tk.Tk()
    BPMAnalyzerApp(root)
    root.mainloop()
