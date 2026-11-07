"""Audio Joiner card for the Master Driver UI.

Changed in 2.5.0: new tool (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
"""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    """Build the card's body and its module toggle."""

    def _body(body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Joins a folder's segments end to end, with an optional\n"
            "silence gap or equal-power crossfade at every boundary.",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 6))

        for label, variable in (
            ("Segments (comma names):", state.audio_joiner_order),
            ("Gap (ms):", state.audio_joiner_gap_ms),
            ("Crossfade (ms):", state.audio_joiner_crossfade_ms),
            ("Output file (optional):", state.audio_joiner_output),
        ):
            row = tk.Frame(body, bg=styles.BG_WHITE)
            row.pack(fill="x", pady=1)
            tk.Label(
                row,
                text=label,
                font=styles.FONT_CAPTION,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                width=24,
                anchor="w",
            ).pack(side=tk.LEFT)
            tk.Entry(
                row,
                textvariable=variable,
                width=22,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                insertbackground=styles.FG_MAIN,
            ).pack(side=tk.LEFT, padx=6)

        tk.Checkbutton(
            body,
            text="Stream-copy when every segment already matches",
            variable=state.audio_joiner_copy,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
        ).pack(anchor="w", pady=(4, 0))

    build_card_shell(
        parent,
        title="Audio Joiner",
        toggle_var=state.module_toggles["audio_joiner"],
        body_builder=_body,
    )
