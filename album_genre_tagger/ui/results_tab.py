"""results_tab.py — Results tab for Album Genre Tagger."""

import tkinter as tk
from typing import Callable

from audio_suite_shared.ui_common import build_results_tab


def build(
    parent: tk.Frame,
    on_open_log: Callable[[], None],
    on_open_folder: Callable[[], None],
) -> dict[str, tk.Label]:
    """Build the Results tab UI.

    Args:
        parent: The notebook tab frame to populate.
        on_open_log: Callback invoked when the "View Log" button is pressed.
        on_open_folder: Callback invoked when the "Open Folder" button is
            pressed.

    Returns:
        A dict with keys ``completion_label``, ``time_label``,
        ``summary_label``, and ``genre_label`` (the genre-specific extra
        label requested via ``extra_labels``), each a :class:`tk.Label`.
    """
    return build_results_tab(
        parent,
        completion_text="",
        on_open_log=on_open_log,
        on_open_folder=on_open_folder,
        extra_labels=["genre_label"],
    )
