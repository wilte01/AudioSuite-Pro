"""
AlbumGenre_Tagger.pyw — Launcher for Album Genre Tagger.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.venv_bootstrap import ensure_venv_interpreter

ensure_venv_interpreter(_script_dir)

from audio_suite_shared.preflight import guard_or_exit

guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging

configure_logging("album_genre_tagger")

import tkinter as tk

from album_genre_tagger.app import GenreConsolidatorApp
from album_genre_tagger.utils.cli_args import parse
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.styles import bootstrap_theme

if __name__ == "__main__":
    parsed_args = parse_cli_args(parse)
    kwargs = {"cli_args_parsed": parsed_args} if parsed_args else {}
    root = tk.Tk()
    bootstrap_theme()
    GenreConsolidatorApp(root, **kwargs)
    root.mainloop()
