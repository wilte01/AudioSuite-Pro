"""Results tab UI for the Stem Separator.

Changed in 2.0.0: created for the Stem Separator (PLAN_feature_expansion.md Item 6.1).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from audio_suite_shared import ui_common


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
) -> dict[str, object]:
    """Populate the Results tab and return widget references."""
    return ui_common.build_results_tab(
        parent,
        "Stem Separation Complete!",
        on_open_log,
        on_open_folder,
    )
