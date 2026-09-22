"""processing_tab.py — Processing tab for Album Genre Tagger."""

import tkinter as tk
from tkinter import ttk
from typing import TypedDict, cast

from audio_suite_shared.ui_common import build_processing_tab


class ProcessingTabWidgets(TypedDict):
    """Widgets returned by :func:`build`, matching ``build_processing_tab``."""

    overall_status: tk.StringVar
    progress: ttk.Progressbar
    stats_label: tk.Label
    file_listbox: tk.Listbox


def build(
    parent: tk.Frame, slot_vars: list[tk.StringVar] | None = None
) -> ProcessingTabWidgets:
    """Build the Processing tab UI.

    Args:
        parent: The notebook tab frame to populate.
        slot_vars: List of per-worker-thread StringVars. Album Genre Tagger
            is single-threaded, so this is always omitted (``None``), which
            means the Active Workers panel is simply not shown.

    Returns:
        A dict with keys ``overall_status``, ``progress``, ``stats_label``,
        and ``file_listbox``.
    """
    return cast(ProcessingTabWidgets, build_processing_tab(parent, slot_vars))
