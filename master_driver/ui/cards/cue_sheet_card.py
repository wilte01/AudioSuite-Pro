"""CUE Sheet Generator card for Master Driver UI.

Changed in 2.6.0: new card (PLAN_2026-11-03_2.6.0_feature_wave_2.md F-E8).
"""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    """Render the CUE Sheet Generator's toggle and caption.

    Args:
        parent: The card cell the window supplies.
        state: The driver's shared state.
    """

    def _body(body: tk.Frame) -> None:
        tk.Label(
            body,
            text=(
                "Writes one album.cue beside the folder's tracks, one FILE "
                "block per track, numbered from the track tag or the name."
            ),
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            wraplength=320,
            justify=tk.LEFT,
            anchor="w",
        ).pack(fill="x", pady=2)

    build_card_shell(
        parent,
        title="CUE Sheet Generator",
        toggle_var=state.module_toggles["cue_sheet"],
        body_builder=_body,
    )
