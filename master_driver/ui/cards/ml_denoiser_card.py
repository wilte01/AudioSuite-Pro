"""
ml_denoiser_card.py — ML Denoiser module card.
Holds the blend amount for a driver run.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
        amount_row = tk.Frame(body, bg=styles.BG_WHITE)
        amount_row.pack(fill="x", pady=1)
        tk.Label(
            amount_row,
            text="  Amount (%):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            amount_row,
            textvariable=state.ml_denoiser_amount,
            width=6,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        tk.Label(
            body,
            text=(
                "100 % keeps RNNoise's own output; lower values blend the source "
                "back in. The model is trained on speech."
            ),
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            justify=tk.LEFT,
            wraplength=300,
        ).pack(anchor="w", pady=(4, 0))

    build_card_shell(
        parent,
        title="ML Denoiser",
        toggle_var=state.module_toggles["ml_denoiser"],
        body_builder=_body,
    )
