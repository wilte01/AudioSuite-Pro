"""results_tab.py - Results tab for Audio Normalizer."""

import tkinter as tk
from collections.abc import Callable
from typing import Any, Optional

from audio_suite_shared.ui_common import build_results_tab


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
    on_play_original: Optional[Callable[[], None]] = None,
    on_play_result: Optional[Callable[[], None]] = None,
) -> dict[str, Any]:
    return build_results_tab(
        parent,
        completion_text="Normalization Complete!",
        on_open_log=on_open_log,
        on_open_folder=on_open_folder,
        log_btn_text="View Log File",
        on_play_original=on_play_original,
        on_play_result=on_play_result,
    )
