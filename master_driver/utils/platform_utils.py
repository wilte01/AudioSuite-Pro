"""
platform_utils.py — Cross-platform helpers for Master Driver.
"""

import logging
import os
import subprocess
import sys
from tkinter import messagebox

from audio_suite_shared.exceptions import map_to_audio_error, user_message_for

logger = logging.getLogger(__name__)


def open_help(script_file: str, guide_filename: str) -> None:
    """Open a plain-text or HTML user guide using the OS default viewer."""
    script_dir = os.path.dirname(os.path.abspath(script_file))
    help_file = os.path.join(script_dir, guide_filename)
    if not os.path.exists(help_file):
        messagebox.showwarning(
            "Help File Not Found",
            f"Could not find:\n{help_file}\n\n"
            f"Please ensure '{guide_filename}' is in the same folder.",
        )
        return
    try:
        if sys.platform == "win32":
            os.startfile(help_file)
        elif sys.platform == "darwin":
            subprocess.run(["open", help_file], check=False)
        else:
            subprocess.run(["xdg-open", help_file], check=False)
    except (OSError, subprocess.CalledProcessError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        messagebox.showerror(
            "Error Opening Help",
            f"Could not open the user guide:\n{user_message_for(mapped)}",
        )
