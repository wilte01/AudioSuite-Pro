"""
main.pyw
Entry point for BPM Analyzer & Tagger.
Nothing lives here except the minimal bootstrap.
"""

import tkinter as tk
from bpm_analyzer.app import BPMAnalyzerApp

if __name__ == "__main__":
    root = tk.Tk()
    BPMAnalyzerApp(root)
    root.mainloop()
