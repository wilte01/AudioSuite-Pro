"""Processing tab UI for Pop & Click Remover."""

from __future__ import annotations

import tkinter as tk

from audio_suite_shared import ui_common


def build(
    parent: tk.Frame, slot_vars: list[tk.StringVar] | None = None
) -> dict[str, object]:
    """
    Populate the Processing tab and return its widget references.

    Parameters
    ----------
    parent : tk.Frame
        The notebook frame to build into.
    slot_vars : list[tk.StringVar] | None
        Per-worker slot label variables managed by the app orchestrator.

    Returns
    -------
    dict
        Keys: ``overall_status``, ``progress``, ``stats_label``, ``file_listbox``.
    """
    return ui_common.build_processing_tab(parent, slot_vars)
