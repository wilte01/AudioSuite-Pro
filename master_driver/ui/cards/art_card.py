"""Album Art Sync card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState
from tkinter import ttk

from audio_suite_shared import styles

_ART_RES_OPTIONS = ["600", "800", "1000", "1200"]
_DIM_OPTIONS = ["200", "300", "400", "500", "600", "800", "1000"]
_THRESHOLD_OPTIONS = ["0.50", "0.60", "0.70", "0.80", "0.85", "0.90", "0.95", "1.00"]


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
        variable=state.module_toggles["art"],
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text="Album Art Sync",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="▶  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    # -- Resolution row --
    r0 = tk.Frame(body, bg=styles.BG_WHITE)
    r0.pack(fill="x", pady=1)
    tk.Label(
        r0,
        text="Max Resolution:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r0,
        textvariable=state.art_res,
        values=_ART_RES_OPTIONS,
        width=6,
        font=styles.FONT_BODY,
        state="readonly",
    ).pack(side=tk.LEFT, padx=6)

    # -- Purge toggle --
    r1 = tk.Frame(body, bg=styles.BG_WHITE)
    r1.pack(fill="x", pady=1)
    tk.Checkbutton(
        r1,
        text="Purge existing artwork first",
        variable=state.art_purge,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(side=tk.LEFT)

    # -- Min dimension row --
    r2 = tk.Frame(body, bg=styles.BG_WHITE)
    r2.pack(fill="x", pady=1)
    tk.Label(
        r2,
        text="Min Image Dimension (px):",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r2,
        textvariable=state.art_min_dim,
        values=_DIM_OPTIONS,
        width=6,
        font=styles.FONT_BODY,
        state="readonly",
    ).pack(side=tk.LEFT, padx=6)

    # -- Match threshold row --
    r3 = tk.Frame(body, bg=styles.BG_WHITE)
    r3.pack(fill="x", pady=1)
    tk.Label(
        r3,
        text="Album Match Threshold:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r3,
        textvariable=state.art_match_threshold,
        values=_THRESHOLD_OPTIONS,
        width=6,
        font=styles.FONT_BODY,
        state="readonly",
    ).pack(side=tk.LEFT, padx=6)

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
