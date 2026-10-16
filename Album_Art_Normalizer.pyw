"""
Album_Art_Normalizer.pyw — Launcher for Album Art Normalizer.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("album_art_normalizer")

from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.styles import bootstrap_theme
from album_art_normalizer.utils.cli_args import parse
import tkinter as tk
from album_art_normalizer.app import ArtNormalizerApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    ArtNormalizerApp(root)
    root.mainloop()
