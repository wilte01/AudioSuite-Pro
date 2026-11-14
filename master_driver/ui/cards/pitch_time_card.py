"""Pitch / Time card for the Master Driver UI.

The card emits one mode, never both: the tool's command refuses a launch that
sets two modes at once, so the choice here is the choice the run makes.

Changed in 2.7.0: new tool (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
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
            text="Changes each file's playback speed (pitch kept) or its\n"
            "pitch (length kept), writing the result beside the source.",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 6))

        for label, variable in (
            ("Tempo rate (factor):", state.pitch_time_rate),
            ("Pitch shift (semitones):", state.pitch_time_semitones),
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

        row = tk.Frame(body, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=(4, 0))
        tk.Label(
            row,
            text="Mode:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=24,
            anchor="w",
        ).pack(side=tk.LEFT)
        for value, text in (("tempo", "Tempo (rate)"), ("pitch", "Pitch (semitones)")):
            tk.Radiobutton(
                row,
                text=text,
                variable=state.pitch_time_mode,
                value=value,
                font=styles.FONT_CAPTION,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                activebackground=styles.BG_WHITE,
                activeforeground=styles.FG_MAIN,
            ).pack(side=tk.LEFT, padx=(0, 10))

    build_card_shell(
        parent,
        title="Pitch / Time",
        toggle_var=state.module_toggles["pitch_time"],
        body_builder=_body,
    )
