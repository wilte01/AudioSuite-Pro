"""
main.pyw — Entry point for Audio Suite Master Driver.
"""

import tkinter as tk

from audio_suite_shared.app_bootstrap import configure_logging
from master_driver.app import AudioSuiteDriver

if __name__ == "__main__":
    configure_logging("master_driver")
    root = tk.Tk()
    AudioSuiteDriver(root)
    root.mainloop()
