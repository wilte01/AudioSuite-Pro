"""
AlbumGenre_Tagger.pyw — Launcher for Album Genre Tagger.
"""

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("album_genre_tagger")

from audio_suite_shared.launcher import parse_cli_args
from album_genre_tagger.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from album_genre_tagger.app import GenreConsolidatorApp

if __name__ == "__main__":
    parsed_args = parse_cli_args(parse)
    kwargs = {"cli_args_parsed": parsed_args} if parsed_args else {}
    root = tk.Tk()
    bootstrap_theme()
    GenreConsolidatorApp(root, **kwargs)
    root.mainloop()
