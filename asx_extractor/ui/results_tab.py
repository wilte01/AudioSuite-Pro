# Changed in 2.3.1: the widget's text colours follow the suite theme instead of
# Tk's symbolic defaults (PLAN_restoration_2026-10-31.md T-02).
"""results_tab.py — Results tab for ASX Playlist Extractor."""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared import styles


def build(
    parent: tk.Frame,
    on_open_log: Callable[..., Any],
    on_open_folder: Callable[..., Any],
) -> tk.Button:
    """
    Populate the Results tab.

    Returns:
        btn_log — the View Log button, initially disabled.
        app.py enables it once the log has been written.
    """
    frame = tk.Frame(parent, padx=40, pady=40, bg=styles.BG_WHITE)
    frame.pack(expand=True, fill="both")

    btn_log = tk.Button(
        frame,
        text="View Log",
        width=30,
        bg=styles.get_main(),
        fg=styles.BG_WHITE,
        disabledforeground=styles.FG_ON_ACCENT_LOCKED,
        pady=10,
        state="disabled",
        font=styles.FONT_BUTTON,
        command=on_open_log,
    )
    btn_log.pack(pady=10)

    tk.Button(
        frame,
        text="Open Folder",
        width=30,
        bg=styles.get_main(),
        fg=styles.BG_WHITE,
        font=styles.FONT_BUTTON,
        pady=10,
        command=on_open_folder,
    ).pack(pady=10)

    return btn_log
