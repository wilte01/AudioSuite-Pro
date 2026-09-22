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
        variable=state.module_toggles["noise_reduction"],
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text="Noise Reduction",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="\u25b6  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

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
