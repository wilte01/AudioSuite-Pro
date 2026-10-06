"""Album Genre Tagger card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
        tk.Label(
            body,
            text="Consolidates TITLEGENRE tags into ALBUMGENRE & ALBUMDERIVED",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
        ).pack(anchor="w", pady=(0, 6))

        cov = tk.Frame(body, bg=styles.BG_WHITE)
        cov.pack(fill="x", pady=1)
        tk.Label(
            cov,
            text="Min. Coverage %:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            cov,
            textvariable=state.album_genre_coverage,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)
        tk.Label(
            cov,
            text="(min % of files with TITLEGENRE)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(4, 0))

    build_card_shell(
        parent,
        title="Album Genre Tagger",
        toggle_var=state.module_toggles["album_genre"],
        body_builder=_body,
    )
