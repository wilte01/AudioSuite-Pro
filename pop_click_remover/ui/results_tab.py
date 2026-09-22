"""Results tab UI for Pop & Click Remover."""

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
    """
    Populate the Results tab and return its widget references.

    Parameters
    ----------
    parent : tk.Frame
        The notebook frame to build into.
    on_open_log : Callable[[], None]
        Callback invoked when the user clicks "Open Log".
    on_open_folder : Callable[[], None]
        Callback invoked when the user clicks "Open Folder".

    Returns
    -------
    dict
        Keys: ``completion_label``, ``time_label``, ``summary_label``.
    """
    return ui_common.build_results_tab(
        parent,
        "Pop & Click Removal Complete!",
        on_open_log,
        on_open_folder,
        on_play_original=on_play_original,
        on_play_result=on_play_result,
    )
