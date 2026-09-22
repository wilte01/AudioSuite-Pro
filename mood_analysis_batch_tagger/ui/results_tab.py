"""results_tab.py — Results tab for Mood Analysis Batch Tagger."""

import tkinter as tk
from collections.abc import Callable
from typing import Any

from audio_suite_shared.ui_common import build_results_tab


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
) -> dict[str, Any]:
    """Build the Results tab using the shared completion-summary layout.

    Returns:
        Dict with keys: completion_label, time_label, summary_label, and the
        open-log / open-folder buttons.
    """
    return build_results_tab(
        parent,
        completion_text="Batch Mood Analysis Complete!",
        on_open_log=on_open_log,
        on_open_folder=on_open_folder,
        log_btn_text="View Log",
    )
