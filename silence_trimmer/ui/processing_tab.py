"""processing_tab.py — Processing tab for Silence Trimmer."""

import tkinter as tk
from typing import Any

from audio_suite_shared.ui_common import build_processing_tab


def build(parent: tk.Frame, slot_vars: list[Any] | None = None) -> dict[str, Any]:
    """Populate the Processing tab.

    Args:
        parent: Parent frame for the tab contents.
        slot_vars: List of tk.StringVar instances for worker slot status display.

    Returns:
        Dict of named widgets: overall_status, progress, stats_label, file_listbox.
    """
    return build_processing_tab(parent, slot_vars)
