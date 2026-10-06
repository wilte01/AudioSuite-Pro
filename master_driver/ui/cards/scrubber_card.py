"""
scrubber_card.py — Metadata Scrubber module card.
Collapsible panel matching the REFINE section style.
"""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
        tk.Checkbutton(
            body,
            text="Preserve all USLT lyrics (recommended)",
            variable=state.scrubber_preserve_lyrics,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(anchor="w")

        tk.Checkbutton(
            body,
            text="Preserve Album Artist (TPE2)",
            variable=state.scrubber_preserve_album_artist,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(anchor="w")

        tk.Checkbutton(
            body,
            text="Preserve Embedded Art (APIC)",
            variable=state.scrubber_preserve_embedded_art,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(anchor="w")

    build_card_shell(
        parent,
        title="Metadata Scrubber",
        toggle_var=state.module_toggles["scrubber"],
        body_builder=_body,
    )
