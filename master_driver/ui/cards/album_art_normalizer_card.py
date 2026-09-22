"""
master_driver/ui/cards/album_art_normalizer_card.py
"""

import tkinter as tk
from tkinter import ttk
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

    toggle = state.module_toggles["album_art_normalizer"]

    tk.Checkbutton(
        header,
        variable=toggle,
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text="Album Art Normalizer",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="\u25b6  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    tk.Label(
        body,
        text="Centre-crops and resizes embedded artwork to a standard resolution.",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
    ).pack(anchor="w")

    r0 = tk.Frame(body, bg=styles.BG_WHITE)
    r0.pack(fill="x", pady=(6, 1))
    tk.Label(
        r0,
        text="Target Size:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r0,
        textvariable=state.art_normalizer_size,
        state="readonly",
        width=12,
        font=styles.FONT_BODY,
        values=("600", "800", "1000", "1200"),
    ).pack(side=tk.LEFT, padx=6)

    tk.Label(
        body,
        text="Normalises folder.jpg to 1000\u00d71000. Supports MP3 and FLAC.",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
    ).pack(anchor="w", pady=(4, 0))
    tk.Label(
        body,
        text="Note: Uses its own mode setting, not the Master Driver Mode option",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.AMBER,
    ).pack(anchor="w", pady=(8, 0))

    def _toggle() -> None:
        if expanded[0]:
            body.pack_forget()
            expand_var.set("\u25b6  Settings")
        else:
            body.pack(fill="x", padx=4, pady=(0, 4))
            expand_var.set("\u25bc  Settings")
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
