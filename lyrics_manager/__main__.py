"""
Entry point for Lyrics Manager package.

Usage:
    python -m lyrics_manager
"""

import tkinter as tk

from audio_suite_shared.app_bootstrap import configure_logging
from audio_suite_shared.styles import bootstrap_theme

from .app import LyricsManagerApp


def main() -> None:
    """Main entry point for the Lyrics Manager GUI."""
    configure_logging("lyrics_manager")
    root = tk.Tk()
    bootstrap_theme()
    LyricsManagerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
