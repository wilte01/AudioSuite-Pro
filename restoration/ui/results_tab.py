"""Results tab for the Restoration (declip) tool.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
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
    """Populate the Results tab and return its widget references.

    Args:
        parent: The notebook frame to build into.
        on_open_log: Callback for View Log.
        on_open_folder: Callback for Open Folder.
        on_play_original: Callback for the before/after audition row.
        on_play_result: Callback for the after half of that row.

    Returns:
        The widget dict from the shared Results-tab builder.
    """
    return ui_common.build_results_tab(
        parent,
        "Declip Complete!",
        on_open_log,
        on_open_folder,
        on_play_original=on_play_original,
        on_play_result=on_play_result,
    )
