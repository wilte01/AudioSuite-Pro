"""processing_tab.py — Processing tab for Genre Sync."""

import tkinter as tk
from typing import Any, Optional

from audio_suite_shared.ui_common import build_processing_tab


def build(
    parent: tk.Frame, slot_vars: Optional[list[tk.StringVar]] = None
) -> dict[str, Any]:
    return build_processing_tab(
        parent,
        slot_vars,
        stats_text="Processed: 0 | Updated: 0 | Skipped: 0 | Errors: 0",
    )
