"""Results tab UI for the ML Denoiser.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from audio_suite_shared import ui_common


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
    on_play_original: Optional[Callable[[], None]] = None,
    on_play_result: Optional[Callable[[], None]] = None,
) -> dict[str, object]:
    """Populate the Results tab and return widget references."""
    return ui_common.build_results_tab(
        parent,
        "ML Denoising Complete!",
        on_open_log,
        on_open_folder,
        on_play_original=on_play_original,
        on_play_result=on_play_result,
    )
