"""BPM Analyzer card for Master Driver UI."""

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
            text="BPM Range:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        rf = tk.Frame(r0, bg=styles.BG_WHITE)
        rf.pack(side=tk.LEFT, padx=6)
        tk.Entry(
            rf,
            textvariable=state.bpm_range_min,
            width=6,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT)
        tk.Label(
            rf,
            text=" to ",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT)
        tk.Entry(
            rf,
            textvariable=state.bpm_range_max,
            width=6,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT)

        r1 = tk.Frame(body, bg=styles.BG_WHITE)
        r1.pack(fill="x", pady=1)
        tk.Label(
            r1,
            text="Analysis Duration (s):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r1,
            textvariable=state.bpm_duration,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        r2 = tk.Frame(body, bg=styles.BG_WHITE)
        r2.pack(fill="x", pady=1)
        tk.Checkbutton(
            r2,
            variable=state.bpm_parallel,
            text="Parallel Processing",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(side=tk.LEFT)
        tk.Label(
            r2,
            text="Workers:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="e",
        ).pack(side=tk.LEFT, padx=(12, 2))
        tk.Entry(
            r2,
            textvariable=state.bpm_workers,
            width=4,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT)

    build_card_shell(
        parent,
        title="BPM Analyzer",
        toggle_var=state.module_toggles["bpm"],
        body_builder=_body,
    )
