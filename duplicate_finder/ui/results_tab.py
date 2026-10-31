"""Results tab for the Duplicate Finder.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
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
        on_open_log: Callback for View Log — opens the report this run wrote.
        on_open_folder: Callback for Open Folder.
        on_play_original: Unused; present so the signature matches the shared
            builder every peer calls.
        on_play_result: Unused, as above.

    Returns:
        Keys ``completion_label``, ``time_label`` and ``summary_label``.
    """
    del on_play_original, on_play_result
    return ui_common.build_results_tab(
        parent,
        "Duplicate Scan Complete!",
        on_open_log,
        on_open_folder,
    )
