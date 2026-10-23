"""
stem_separator_card.py — Stem Separator module card.
Holds the destination, model, stem selection and device for a driver run.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).

Changed in 2.1.0: the Output Folder row gains a Browse button, so the
    destination is picked the same way it is on the tool's own Setup tab
    instead of having to be typed, and the card states the required-field rule
    the arg builder enforces (an output folder and at least one stem).
"""

import os
import tkinter as tk
from tkinter import filedialog, ttk
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
        def _browse_output() -> None:
            """Pick the stem output folder, starting from the current value.

            The entry accepts typed text, so the current value is only used as
            the dialog's starting directory when it really is one — a stale or
            mistyped path would otherwise hand Tk an unusable ``initialdir``.
            """
            current = state.stem_separator_output_dir.get().strip()
            folder = filedialog.askdirectory(
                title="Select Stem Output Directory",
                initialdir=(current if current and os.path.isdir(current) else ""),
            )
            if folder:
                state.stem_separator_output_dir.set(folder)

        out_row = _row(body, "Output Folder")
        tk.Entry(
            out_row,
            textvariable=state.stem_separator_output_dir,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, fill="x", expand=True, padx=6)
        tk.Button(
            out_row,
            text="Browse",
            command=_browse_output,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
        ).pack(side=tk.LEFT)

        tk.Label(
            body,
            text=(
                "Required \u2014 each track is written into a subfolder here, and "
                "at least one stem must be ticked."
            ),
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.COLOR_ERROR,
            anchor="w",
            wraplength=460,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(2, 4))

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
