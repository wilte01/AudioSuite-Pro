"""
Music_Format_Converter.pyw — Launcher for Music Format Converter.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("music_format_converter")

from audio_suite_shared.launcher import parse_cli_args
from music_format_converter.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from music_format_converter.app import MusicFormatConverterApp

if __name__ == "__main__":
    parse_cli_args(parse)
    root = tk.Tk()
    bootstrap_theme()
    MusicFormatConverterApp(root)
    root.mainloop()
