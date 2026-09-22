"""
processing_tab.py
Processing tab for Audio Fingerprinter.

Delegates entirely to the shared build_processing_tab factory, surfacing the
per-worker status panel plus the standard progress bar and stats label.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any

from audio_suite_shared.ui_common import build_processing_tab


def build(parent: tk.Frame, slot_vars: list[tk.StringVar]) -> dict[str, Any]:
    """
    Populate the Processing tab widgets.

    Args:
        parent:    Container frame provided by the notebook.
        slot_vars: List of Tk StringVars, one per worker slot.

    Returns:
        Dict with keys: overall_status, progress, stats_label, file_listbox.
    """
    widgets = build_processing_tab(
        parent,
        slot_vars=slot_vars,
        stats_text="Processed: 0 | Identified: 0 | Errors: 0",
    )
    return {
        "overall_status": widgets["overall_status"],
        "progress": widgets["progress"],
        "stats_label": widgets["stats_label"],
        "file_listbox": widgets["file_listbox"],
    }
