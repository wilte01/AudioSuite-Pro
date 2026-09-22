"""
processing_tab.py — Processing tab for Album Art Normalizer.

Reuses shared build_processing_tab infrastructure.
No worker slots are shown (single-threaded tool).
"""

from __future__ import annotations

import tkinter as tk

from audio_suite_shared.ui_common import build_processing_tab


def build(parent: tk.Frame) -> dict[str, object]:
    """Populate the Processing tab using shared infrastructure.

    Args:
        parent: The tab Frame to populate.

    Returns:
        Dict of widget references (overall_status, progress, stats_label, file_listbox).
    """
    return build_processing_tab(parent)
