"""audio_enhancer_card.py — Audio Enhancer module card.

The enhancer needs an output directory before it can run.  When the
output directory is empty at batch time, arg_builder returns ``[]`` so no
broken ``--output-dir``/``--output`` flag is ever handed to the tool's
strict GUI parser — the card's required-field hint is the only guard.
"""

import tkinter as tk
from tkinter import filedialog, ttk
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
        variable=state.module_toggles["audio_enhancer"],
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text="Audio Enhancer",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="\u25b6  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    def _browse_output() -> None:
        folder = filedialog.askdirectory()
        if folder:
            state.enhancer_output_dir.set(folder)

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
        textvariable=state.enhancer_output_dir,
        width=24,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, padx=6)
    tk.Button(
        r0,
        text="Browse...",
        font=styles.FONT_CAPTION,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
        relief=tk.RAISED,
        cursor="hand2",
        command=_browse_output,
    ).pack(side=tk.LEFT, padx=4)

    tk.Label(
        body,
        text="Required — the enhancer writes normalised copies into this folder.",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.COLOR_ERROR,
        anchor="w",
    ).pack(anchor="w", pady=(2, 6))

    r1 = tk.Frame(body, bg=styles.BG_WHITE)
    r1.pack(fill="x", pady=1)
    tk.Label(
        r1,
        text="Preset:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r1,
        textvariable=state.enhancer_preset,
        state="readonly",
        width=12,
        font=styles.FONT_BODY,
        values=("Mild", "Moderate", "Aggressive"),
    ).pack(side=tk.LEFT, padx=6)

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
