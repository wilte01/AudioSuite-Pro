"""
noise_reduction_card.py — Noise Reduction module card.
Collapsible panel matching the REFINE section style.
"""

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
        tk.Checkbutton(
            body,
            text="Enable Hum Removal",
            variable=state.nr_reduce_hum,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(anchor="w")

        hum_frame = tk.Frame(body, bg=styles.BG_WHITE)
        hum_frame.pack(fill="x", pady=1)
        tk.Label(
            hum_frame,
            text="  Mains Frequency:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            hum_frame,
            textvariable=state.nr_hum_frequency,
            state="readonly",
            width=5,
            font=styles.FONT_BODY,
            values=("50", "60"),
        ).pack(side=tk.LEFT, padx=6)

        harm_frame = tk.Frame(body, bg=styles.BG_WHITE)
        harm_frame.pack(fill="x", pady=1)
        tk.Label(
            harm_frame,
            text="  Harmonics (1-20):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            harm_frame,
            textvariable=state.nr_hum_harmonics,
            width=6,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        q_frame = tk.Frame(body, bg=styles.BG_WHITE)
        q_frame.pack(fill="x", pady=1)
        tk.Label(
            q_frame,
            text="  Q Factor:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            q_frame,
            textvariable=state.nr_hum_quality,
            width=6,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        tk.Checkbutton(
            body,
            text="Enable Broadband Noise Reduction",
            variable=state.nr_reduce_broadband,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(anchor="w", pady=(6, 0))

        ns_frame = tk.Frame(body, bg=styles.BG_WHITE)
        ns_frame.pack(fill="x", pady=1)
        tk.Label(
            ns_frame,
            text="  Noise Start (ms):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            ns_frame,
            textvariable=state.nr_noise_start,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        ne_frame = tk.Frame(body, bg=styles.BG_WHITE)
        ne_frame.pack(fill="x", pady=1)
        tk.Label(
            ne_frame,
            text="  Noise End (ms):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            ne_frame,
            textvariable=state.nr_noise_end,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        gt_frame = tk.Frame(body, bg=styles.BG_WHITE)
        gt_frame.pack(fill="x", pady=1)
        tk.Label(
            gt_frame,
            text="  Gate Threshold (dB):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            gt_frame,
            textvariable=state.nr_gate_threshold,
            width=6,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

    build_card_shell(
        parent,
        title="Noise Reduction",
        toggle_var=state.module_toggles["noise_reduction"],
        body_builder=_body,
    )
