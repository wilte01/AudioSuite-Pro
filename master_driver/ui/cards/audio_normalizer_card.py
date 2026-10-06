"""audio_normalizer_card.py — Audio Normalizer module card."""

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell

LUFS_OPTIONS: tuple[str, ...] = ("-12.0", "-14.0", "-16.0", "-18.0", "-23.0")


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
        r0 = tk.Frame(body, bg=styles.BG_WHITE)
        r0.pack(fill="x", pady=1)
        tk.Label(
            r0,
            text="Target LUFS:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            r0,
            textvariable=state.normalizer_target_lufs,
            state="readonly",
            width=8,
            font=styles.FONT_BODY,
            values=LUFS_OPTIONS,
        ).pack(side=tk.LEFT, padx=6)

        r1 = tk.Frame(body, bg=styles.BG_WHITE)
        r1.pack(fill="x", pady=1)
        tk.Label(
            r1,
            text="Tolerance (LUFS):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r1,
            textvariable=state.normalizer_tolerance,
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
            text="Mode:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            r2,
            textvariable=state.normalizer_mode,
            state="readonly",
            width=12,
            font=styles.FONT_BODY,
            values=("normalise", "lossless"),
        ).pack(side=tk.LEFT, padx=6)

    build_card_shell(
        parent,
        title="Audio Normalizer",
        toggle_var=state.module_toggles["audio_normalizer"],
        body_builder=_body,
    )
