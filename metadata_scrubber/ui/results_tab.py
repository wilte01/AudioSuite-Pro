"""results_tab.py - Results tab for Metadata Scrubber."""

import tkinter as tk
from collections.abc import Callable
from typing import Any

from audio_suite_shared.ui_common import build_results_tab


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
) -> dict[str, Any]:
    return build_results_tab(
        parent,
        completion_text="Metadata Scrubbing Complete!",
        on_open_log=on_open_log,
        on_open_folder=on_open_folder,
    )
