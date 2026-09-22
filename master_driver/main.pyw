"""
main.pyw — Entry point for Audio Suite Master Driver.
"""

import tkinter as tk
from master_driver.app import AudioSuiteDriver

if __name__ == "__main__":
    root = tk.Tk()
    AudioSuiteDriver(root)
    root.mainloop()
