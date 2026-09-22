"""
scrubber_card.py — Metadata Scrubber module card.
Collapsible panel matching the REFINE section style.
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
        variable=state.module_toggles["scrubber"],
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text="Metadata Scrubber",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="▶  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    tk.Checkbutton(
        body,
        text="Preserve all USLT lyrics (recommended)",
        variable=state.scrubber_preserve_lyrics,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(anchor="w")

    tk.Checkbutton(
        body,
        text="Preserve Album Artist (TPE2)",
        variable=state.scrubber_preserve_album_artist,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(anchor="w")

    tk.Checkbutton(
        body,
        text="Preserve Embedded Art (APIC)",
        variable=state.scrubber_preserve_embedded_art,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(anchor="w")

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
