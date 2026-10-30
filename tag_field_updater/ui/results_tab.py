"""results_tab.py — Results tab for Tag Field Updater.

Changed in 2.2.1: the tab has its own module, as it does in every package
that builds the suite's three tabs (maintenance item U4).  View Log opens the
run report the scan writes into the scanned folder.
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable

from audio_suite_shared.ui_common import build_results_tab


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
    *,
    completion_text: str = "Scan Complete!",
) -> dict[str, object]:
    """
    Populate the Results tab using shared infrastructure.

    Args:
        parent:          The tab Frame to populate.
        on_open_log:     Callback for the View Log button.  It opens the run
                         report written in the scanned folder.
        on_open_folder:  Callback for the Open Folder button.
        completion_text: Heading shown before a run finishes; the shared base
                         replaces it with the mode-specific caption on
                         completion.

    Returns:
        Dict of widget references keyed by name (completion_label,
        time_label, summary_label).
    """
    return build_results_tab(
        parent,
        completion_text=completion_text,
        on_open_log=on_open_log,
        on_open_folder=on_open_folder,
    )
