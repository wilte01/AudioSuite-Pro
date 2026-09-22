"""processing_tab.py — Processing tab for Tempo Analyzer."""

import tkinter as tk
from typing import Any

from audio_suite_shared.ui_common import build_processing_tab


def build(parent: tk.Frame, slot_vars: list[Any] | None = None) -> dict[str, Any]:
    """
    Build and return the processing tab widgets.

    Args:
        parent:    Parent tkinter Frame to populate.
        slot_vars: Optional list of tk.StringVar objects for worker slots.

    Returns:
        Dict of named widget references produced by build_processing_tab.
    """
    return build_processing_tab(parent, slot_vars)
