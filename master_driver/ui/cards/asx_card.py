# Changed in 2.4.0: duplicate dispositions and ASX stubs.
"""ASX Playlist Extractor card for Master Driver UI."""

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
            text="Include subfolders (find .asx playlists in sub-folders)",
            variable=state.asx_recursive,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            anchor="w",
        ).pack(fill="x", pady=2)

    build_card_shell(
        parent,
        title="ASX Playlist Extractor",
        toggle_var=state.asx_extractor_toggle,
        body_builder=_body,
    )
