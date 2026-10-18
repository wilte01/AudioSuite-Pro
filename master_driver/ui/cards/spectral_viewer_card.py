"""Spectral Viewer card for the Master Driver UI.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1).
"""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    """Build the Spectral Viewer card body.

    Args:
        parent: Frame the card is built into.
        state: The Master Driver state holding the tool's options.
    """

    def _body(body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Renders an FFT spectrogram for each audio file. In a batch the\n"
            "window opens on the folder's first file; run `audiosuite spectrogram`\n"
            "to export a whole folder without the GUI.",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 6))

        r0 = tk.Frame(body, bg=styles.BG_WHITE)
        r0.pack(fill="x", pady=1)
        tk.Label(
            r0,
            text="Export folder (optional):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r0,
            textvariable=state.spectral_output_dir,
            width=24,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        r1 = tk.Frame(body, bg=styles.BG_WHITE)
        r1.pack(fill="x", pady=1)
        tk.Label(
            r1,
            text="FFT size (samples):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r1,
            textvariable=state.spectral_n_fft,
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
            text="Colour range (dB):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r2,
            textvariable=state.spectral_db_range,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

    build_card_shell(
        parent,
        title="Spectral Viewer",
        toggle_var=state.module_toggles["spectral_viewer"],
        body_builder=_body,
    )
