"""
stem_separator_card.py — Stem Separator module card.
Holds the destination, model, stem selection and device for a driver run.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def _row(body: tk.Frame, label: str) -> tk.Frame:
    """Add a label + control row and return the row frame."""
    row = tk.Frame(body, bg=styles.BG_WHITE)
    row.pack(fill="x", pady=1)
    tk.Label(
        row,
        text=f"  {label}:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        anchor="w",
        width=16,
    ).pack(side=tk.LEFT)
    return row


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
        out_row = _row(body, "Output Folder")
        tk.Entry(
            out_row,
            textvariable=state.stem_separator_output_dir,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, fill="x", expand=True, padx=6)

        model_row = _row(body, "Model")
        ttk.Combobox(
            model_row,
            textvariable=state.stem_separator_model,
            state="readonly",
            width=14,
            font=styles.FONT_BODY,
            values=("htdemucs", "htdemucs_ft"),
        ).pack(side=tk.LEFT, padx=6)

        device_row = _row(body, "Device")
        ttk.Combobox(
            device_row,
            textvariable=state.stem_separator_device,
            state="readonly",
            width=8,
            font=styles.FONT_BODY,
            values=("auto", "cpu", "cuda"),
        ).pack(side=tk.LEFT, padx=6)

        stems_row = _row(body, "Stems")
        for label, var in (
            ("Vocals", state.stem_separator_vocals),
            ("Drums", state.stem_separator_drums),
            ("Bass", state.stem_separator_bass),
            ("Other", state.stem_separator_other),
        ):
            tk.Checkbutton(
                stems_row,
                text=label,
                variable=var,
                font=styles.FONT_CAPTION,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                activebackground=styles.BG_WHITE,
            ).pack(side=tk.LEFT, padx=(0, 4))

        tk.Checkbutton(
            body,
            text="Also write mix.wav",
            variable=state.stem_separator_mix,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(anchor="w", pady=(4, 0))

    build_card_shell(
        parent,
        title="Stem Separator",
        toggle_var=state.module_toggles["stem_separator"],
        body_builder=_body,
    )
