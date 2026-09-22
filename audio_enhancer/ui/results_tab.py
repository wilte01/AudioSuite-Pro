"""
ui/results_tab.py
Results tab for Audio Enhancer.

Delegates to audio_suite_shared.ui_common.build_results_tab() to match
the suite's established results-tab layout, then returns the widget
references that app.py needs to populate after processing completes.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable, Optional

from audio_suite_shared import ui_common


def build(
    parent: tk.Frame,
    on_open_log: Callable[..., Any],
    on_open_folder: Callable[..., Any],
    on_play_original: Optional[Callable[[], None]] = None,
    on_play_result: Optional[Callable[[], None]] = None,
) -> dict[str, Any]:
    """
    Populate the Results tab.

    Returns
    -------
    dict with keys:
        completion_label : tk.Label
        time_label       : tk.Label
        summary_label    : tk.Label
    """
    return ui_common.build_results_tab(
        parent,
        "Enhancement Complete!",
        on_open_log,
        on_open_folder,
        on_play_original=on_play_original,
        on_play_result=on_play_result,
    )
