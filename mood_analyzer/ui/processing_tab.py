"""processing_tab.py — Processing tab for Mood Analyzer."""

import tkinter as tk
from typing import Any

from audio_suite_shared.ui_common import build_processing_tab


def build(
    parent: tk.Frame, slot_vars: list[tk.StringVar] | None = None
) -> dict[str, Any]:
    return build_processing_tab(parent, slot_vars)
