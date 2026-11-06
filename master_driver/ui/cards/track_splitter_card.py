"""Track Splitter card for the Master Driver UI.

Changed in 2.5.0: new tool (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E4).
"""

import tkinter as tk
from tkinter import ttk
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
            text="Splits each recording into tracks at its silent gaps, naming\n"
            "and (optionally) shelving them with a CUE sheet.",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 6))

        for label, variable in (
            ("Minimum silence (ms):", state.track_splitter_min_silence),
            ("Silence threshold (dBFS):", state.track_splitter_silence_db),
            ("Minimum track (ms):", state.track_splitter_min_track),
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
                width=10,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                insertbackground=styles.FG_MAIN,
            ).pack(side=tk.LEFT, padx=6)

        row = tk.Frame(body, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=1)
        tk.Label(
            row,
            text="Boundary:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=24,
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            row,
            textvariable=state.track_splitter_boundary,
            state="readonly",
            width=12,
            font=styles.FONT_BODY,
            values=("midpoint", "start", "end"),
        ).pack(side=tk.LEFT, padx=6)

        row = tk.Frame(body, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=1)
        tk.Label(
            row,
            text="Output folder (optional):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=24,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            row,
            textvariable=state.track_splitter_output_dir,
            width=22,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        tk.Checkbutton(
            body,
            text="Write a CUE sheet beside the tracks",
            variable=state.track_splitter_cue,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
        ).pack(anchor="w", pady=(4, 0))

    build_card_shell(
        parent,
        title="Track Splitter",
        toggle_var=state.track_splitter_toggle,
        body_builder=_body,
    )
