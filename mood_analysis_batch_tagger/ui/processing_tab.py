"""processing_tab.py — Processing tab for Mood Analysis Batch Tagger."""

import tkinter as tk
from typing import Any

from audio_suite_shared.ui_common import build_processing_tab


def build(
    parent: tk.Frame,
    slot_vars: list[tk.StringVar] | None = None,
) -> dict[str, Any]:
    """Build the Processing tab using the shared multi-worker layout.

    Returns:
        Dict with keys: overall_status, progress, stats_label, file_listbox,
        and per-slot status StringVars (when slot_vars is provided).
    """
    return build_processing_tab(parent, slot_vars)
