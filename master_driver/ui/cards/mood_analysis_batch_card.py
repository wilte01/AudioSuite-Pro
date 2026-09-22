"""
mood_analysis_batch_card.py — Mood Analysis Batch Tagger module card.
Collapsible panel matching the UTILITY section style.
"""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles


def build(parent: tk.Frame, state: "AppState") -> None:
    outer = tk.Frame(
        parent,
        bg=styles.BG_LIGHT,
        highlightbackground=styles.FG_SUB,
        highlightthickness=1,
    )
    outer.pack(fill="x", pady=4, padx=2)

    header = tk.Frame(outer, bg=styles.BG_LIGHT)
    header.pack(fill="x", padx=8, pady=4)

    tk.Checkbutton(
        header,
        variable=state.module_toggles["mood_analysis_batch"],
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text="Mood Analysis Batch Tagger",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="▶  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    # Analysis duration
    dur_row = tk.Frame(body, bg=styles.BG_WHITE)
    dur_row.pack(fill="x", pady=2)
    tk.Label(
        dur_row,
        text="Analysis Duration (sec):",
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT)
    tk.Entry(
        dur_row,
        textvariable=state.mood_analysis_batch_duration,
        width=6,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, padx=(8, 0))

    # Parallel + workers
    par_row = tk.Frame(body, bg=styles.BG_WHITE)
    par_row.pack(fill="x", pady=4)
    tk.Checkbutton(
        par_row,
        text="Parallel Processing",
        variable=state.mood_analysis_batch_parallel,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(side=tk.LEFT)
    tk.Label(
        par_row,
        text="Workers:",
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, padx=(12, 2))
    tk.Entry(
        par_row,
        textvariable=state.mood_analysis_batch_workers,
        width=4,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT)

    tk.Label(
        body,
        text="Recursively analyses the audio signal of every file under the "
        "selected root and writes mood + confidence tags.",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        wraplength=480,
        justify=tk.LEFT,
    ).pack(anchor="w", pady=(4, 0))

    def _toggle() -> None:
        if expanded[0]:
            body.pack_forget()
            expand_var.set("▶  Settings")
        else:
            body.pack(fill="x", padx=4, pady=(0, 4))
            expand_var.set("▼  Settings")
        expanded[0] = not expanded[0]

    tk.Button(
        header,
        textvariable=expand_var,
        font=styles.FONT_CAPTION,
        bg=styles.BG_LIGHT,
        fg=styles.FG_SUB,
        relief=tk.FLAT,
        cursor="hand2",
        command=_toggle,
    ).pack(side=tk.RIGHT)
