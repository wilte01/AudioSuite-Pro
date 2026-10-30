"""processing_tab.py — Processing tab for the Tag Editor.

Changed in 2.2.1: the tab has its own module, as it does in every package that
builds the suite's three tabs (maintenance item U5).  It delegates to
``audio_suite_shared.ui_common.build_processing_tab``: the load walk and each
apply run stream their per-file lines here.
"""

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
                   Both runs are single-threaded, so none are passed.

    Returns:
        Dict of widget references keyed by name (overall_status, progress,
        stats_label, file_listbox).
    """
    return build_processing_tab(parent, slot_vars)
