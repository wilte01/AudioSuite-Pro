"""results_tab.py — Results tab for Tempo Analyzer."""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared.ui_common import build_results_tab


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
) -> dict[str, Any]:
    """
    Build and return the results tab widgets.

    Args:
        parent:         Parent tkinter Frame to populate.
        on_open_log:    Callback to open the log file.
        on_open_folder: Callback to open the source folder.

    Returns:
        Dict of named widget references produced by build_results_tab.
    """
    return build_results_tab(
        parent,
        completion_text="Tempo Analysis Complete!",
        on_open_log=on_open_log,
        on_open_folder=on_open_folder,
    )
