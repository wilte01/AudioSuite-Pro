"""silence_trimmer_card.py — Silence Trimmer module card."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
        r0 = tk.Frame(body, bg=styles.BG_WHITE)
        r0.pack(fill="x", pady=1)
        tk.Label(
            r0,
            text="Silence Threshold (dB):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r0,
            textvariable=state.trimmer_threshold,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        tk.Checkbutton(
            body,
            text="Apply fade-in / fade-out after trimming",
            variable=state.trimmer_apply_fade,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(anchor="w", pady=(6, 0))

        r1 = tk.Frame(body, bg=styles.BG_WHITE)
        r1.pack(fill="x", pady=1)
        tk.Label(
            r1,
            text="  Fade-in (ms, 100–3000):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r1,
            textvariable=state.trimmer_fade_in_ms,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        r2 = tk.Frame(body, bg=styles.BG_WHITE)
        r2.pack(fill="x", pady=1)
        tk.Label(
            r2,
            text="  Fade-out (ms, 100–5000):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r2,
            textvariable=state.trimmer_fade_out_ms,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

    build_card_shell(
        parent,
        title="Silence Trimmer",
        toggle_var=state.module_toggles["silence_trimmer"],
        body_builder=_body,
    )
