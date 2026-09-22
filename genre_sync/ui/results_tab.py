"""results_tab.py — Results tab for Genre Sync."""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared.ui_common import build_results_tab


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
) -> dict[str, Any]:
    return build_results_tab(
        parent,
        completion_text="Processing Complete!",
        on_open_log=on_open_log,
        on_open_folder=on_open_folder,
    )
