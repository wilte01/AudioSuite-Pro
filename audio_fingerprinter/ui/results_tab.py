"""
results_tab.py
Results tab for Audio Fingerprinter.

Delegates entirely to the shared build_results_tab factory; this thin
wrapper exists to maintain tool-specific import isolation and to satisfy
the standard UI module contract.

Changed in 1.2.0: requests the ``isrc_label`` extra label so the ISRC
submission outcome (accepted, rejected, not authorised, offline) is on the
Results tab instead of only in the run log.
"""

import tkinter as tk
from typing import Callable

from audio_suite_shared.ui_common import build_results_tab


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
) -> dict[str, object]:
    """
    Populate the Results tab widgets.

    Args:
        parent:         Container frame provided by the notebook.
        on_open_log:    Callback invoked when Open Log button is clicked.
        on_open_folder: Callback invoked when Open Folder button is clicked.

    Returns:
        Dictionary of result widget references as returned by
        build_results_tab (keys: 'completion_label', 'time_label',
        'summary_label', 'isrc_label').
    """
    return build_results_tab(
        parent,
        completion_text="Fingerprinting Complete!",
        on_open_log=on_open_log,
        on_open_folder=on_open_folder,
        extra_labels=["isrc_label"],
    )
