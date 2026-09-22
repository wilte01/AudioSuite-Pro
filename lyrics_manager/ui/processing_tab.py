"""processing_tab.py — Processing tab for Lyrics Manager."""

from __future__ import annotations

import tkinter as tk
from typing import Optional

from audio_suite_shared.ui_common import build_processing_tab


def build(
    parent: tk.Frame,
    slot_vars: Optional[list[tk.StringVar]] = None,
) -> dict[str, object]:
    """
    Populate the Processing tab using shared infrastructure.

    Args:
        parent:    The tab Frame to populate.
        slot_vars: Optional list of StringVars for worker-slot status labels.

    Returns:
        Dict of widget references keyed by name (overall_status, progress,
        stats_label, file_listbox).
    """
    return build_processing_tab(parent, slot_vars)
