"""results_tab.py — Results tab for Silence Trimmer."""

import tkinter as tk
from typing import Any, Callable, Optional

from audio_suite_shared.ui_common import build_results_tab


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
    on_play_original: Optional[Callable[[], None]] = None,
    on_play_result: Optional[Callable[[], None]] = None,
) -> dict[str, Any]:
    """Populate the Results tab.

    Args:
        parent: Parent frame for the tab contents.
        on_open_log: Callback invoked when the Open Log button is clicked.
        on_open_folder: Callback invoked when the Open Folder button is clicked.

    Returns:
        Dict of named widgets: completion_label, time_label, summary_label.
    """
    return build_results_tab(
        parent,
        completion_text="Silence Trimming Complete!",
        on_open_log=on_open_log,
        on_open_folder=on_open_folder,
        on_play_original=on_play_original,
        on_play_result=on_play_result,
    )
