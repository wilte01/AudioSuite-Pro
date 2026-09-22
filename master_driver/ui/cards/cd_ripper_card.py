"""
master_driver/ui/cards/cd_ripper_card.py
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

    tk.Checkbutton(
        header,
        variable=state.cd_ripper_toggle,
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text="CD Ripper",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="\u25b6  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    tk.Label(
        body,
        text="Rips audio CDs with automatic MusicBrainz metadata lookup.",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
    ).pack(anchor="w", pady=(0, 6))

    r0 = tk.Frame(body, bg=styles.BG_WHITE)
    r0.pack(fill="x", pady=1)
    tk.Label(
        r0,
        text="Output Directory:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    tk.Entry(
        r0,
        textvariable=state.cd_ripper_output_dir,
        width=24,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, padx=6)

    r1 = tk.Frame(body, bg=styles.BG_WHITE)
    r1.pack(fill="x", pady=1)
    tk.Label(
        r1,
        text="Format:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r1,
        textvariable=state.cd_ripper_format,
        state="readonly",
        width=12,
        font=styles.FONT_BODY,
        values=("wav", "mp3", "flac", "ogg", "m4a", "opus"),
    ).pack(side=tk.LEFT, padx=6)

    r2 = tk.Frame(body, bg=styles.BG_WHITE)
    r2.pack(fill="x", pady=1)
    tk.Label(
        r2,
        text="Tracks (optional):",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    tk.Entry(
        r2,
        textvariable=state.cd_ripper_tracks,
        width=20,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, padx=6)

    r3 = tk.Frame(body, bg=styles.BG_WHITE)
    r3.pack(fill="x", pady=(4, 1))
    tk.Checkbutton(
        r3,
        text="Generate CUE sheet",
        variable=state.cd_ripper_cue,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(side=tk.LEFT)

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
