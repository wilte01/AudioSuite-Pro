"""
ASX_Playlist_Extractor.pyw — Launcher for ASX Playlist Extractor.
"""

import os

_script_dir = os.path.dirname(os.path.abspath(__file__))

from audio_suite_shared.preflight import guard_or_exit
guard_or_exit(_script_dir)

from audio_suite_shared.app_bootstrap import configure_logging
configure_logging("asx_extractor")

from audio_suite_shared.launcher import parse_cli_args
from asx_extractor.utils.cli_args import parse
import tkinter as tk
from audio_suite_shared.styles import bootstrap_theme
from asx_extractor.app import ASXExtractorTool

if __name__ == "__main__":
    parsed = parse_cli_args(parse)
    if parsed is not None:
        kwargs = {
            "initial_directory": parsed.directory,
            "initial_mode": parsed.mode,
            "auto_start": parsed.auto_start,
            "auto_end": parsed.auto_end,
            "clear_logs": parsed.clear_logs,
            "parallel_run": parsed.parallel_run,
        }
    else:
        kwargs = {}
    root = tk.Tk()
    bootstrap_theme()
    ASXExtractorTool(root, **kwargs)
    root.mainloop()
