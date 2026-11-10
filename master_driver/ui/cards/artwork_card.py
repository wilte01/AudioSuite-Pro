"""Artwork Extractor card for Master Driver UI.

The card carries the three settings the batch step passes to the window: the
sidecar base name, whether an existing sidecar may be replaced, and whether
sub-folders are read. The extraction itself has no other setting, so the body
stays a caption plus those controls.

Changed in 2.6.0: new card — the Artwork Extractor's batch step.
"""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    """Render the Artwork Extractor's toggle, options and caption.

    Args:
        parent: The card cell the window supplies.
        state: The driver's shared state.
    """

    def _body(body: tk.Frame) -> None:
        row = tk.Frame(body, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=2)
        tk.Label(
            row,
            text="Sidecar name:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=16,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            row,
            textvariable=state.artwork_sidecar_name,
            width=14,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        for text, variable in (
            ("Replace existing sidecar", state.artwork_force),
            ("Include sub-folders", state.artwork_recursive),
        ):
            tk.Checkbutton(
                body,
                text=text,
                variable=variable,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                activebackground=styles.BG_WHITE,
                activeforeground=styles.FG_MAIN,
            ).pack(anchor="w")

        tk.Label(
            body,
            text=(
                "Writes each file's embedded cover beside it as cover.jpg or "
                "cover.png, chosen from the image's own bytes; an existing "
                "sidecar is kept unless replacing is ticked."
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
        title="Artwork Extractor",
        toggle_var=state.module_toggles["artwork"],
        body_builder=_body,
    )
