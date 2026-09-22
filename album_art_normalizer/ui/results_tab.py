"""
results_tab.py — Results tab for Album Art Normalizer.

Reuses shared build_results_tab infrastructure.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from audio_suite_shared.ui_common import build_results_tab


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
) -> dict[str, object]:
    """Populate the Results tab using shared infrastructure.

    Args:
        parent: The tab Frame to populate.
        on_open_log: Callback for the View Log button.
        on_open_folder: Callback for the Open Folder button.

    Returns:
        Dict of widget references (completion_label, time_label, summary_label).
    """
    return build_results_tab(
        parent,
        completion_text="Artwork Normalization Complete!",
        on_open_log=on_open_log,
        on_open_folder=on_open_folder,
    )
