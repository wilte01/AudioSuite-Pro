"""
ui/processing_tab.py
Processing tab for Audio Enhancer.

Delegates to audio_suite_shared.ui_common.build_processing_tab() to match
the suite's established processing-tab layout exactly, then returns the
widget references that app.py needs for live updates.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any

from audio_suite_shared import ui_common


def build(parent: tk.Frame, slot_vars: list[Any]) -> dict[str, Any]:
    """
    Populate the Processing tab.

    Returns
    -------
    dict with keys:
        overall_status  : tk.StringVar
        progress        : ttk.Progressbar
        stats_label     : tk.Label
        file_listbox    : tk.Listbox
    """
    return ui_common.build_processing_tab(parent, slot_vars)
