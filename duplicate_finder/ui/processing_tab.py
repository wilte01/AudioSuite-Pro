"""Processing tab for the Duplicate Finder.

The scan is single-threaded — fpcalc is already fast and its output order is what
makes the report reproducible — so the shared tab is built without a worker-slot
grid.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import tkinter as tk

from audio_suite_shared import ui_common


def build(parent: tk.Frame) -> dict[str, object]:
    """Populate the Processing tab and return its widget references.

    Args:
        parent: The notebook frame to build into.

    Returns:
        Keys ``overall_status``, ``progress``, ``stats_label`` and
        ``file_listbox``.
    """
    return ui_common.build_processing_tab(parent)
