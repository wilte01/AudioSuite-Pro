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
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
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

    build_card_shell(
        parent,
        title="Audio Enhancer",
        toggle_var=state.module_toggles["audio_enhancer"],
        body_builder=_body,
    )
