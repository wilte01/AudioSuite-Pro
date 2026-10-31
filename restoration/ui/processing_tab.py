"""Processing tab for the Restoration (declip) tool.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

import tkinter as tk

from audio_suite_shared import ui_common


def build(
    parent: tk.Frame, slot_vars: list[tk.StringVar] | None = None
) -> dict[str, object]:
    """Populate the Processing tab and return its widget references.

    Args:
        parent: The notebook frame to build into.
        slot_vars: Per-worker slot label variables managed by the window.

    Returns:
        Keys ``overall_status``, ``progress``, ``stats_label`` and
        ``file_listbox``.
    """
    return ui_common.build_processing_tab(parent, slot_vars)
