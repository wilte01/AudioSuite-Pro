"""Undo Tag Edits card for the Master Driver UI.

Unlike the batch tools in the Utilities tab, Undo Tag Edits is opened on
demand and is never part of a batch run.  The card therefore shows no module
checkbox; its collapsible body holds the description and the prominent
``Open Undo`` button.

Changed in 2.0.0: rendered on the shared card shell and collapsed by default.
The three-line description used to sit outside any collapsible body, which
made this the tallest card in the tab (131 px against 35 px) for a control
opened between batches (PLAN_feature_expansion.md D119).
"""

import tkinter as tk
from typing import TYPE_CHECKING, Callable

from audio_suite_shared import styles

from ._card_base import build_card_shell

if TYPE_CHECKING:
    from ...state.app_state import AppState


def build(
    parent: tk.Frame,
    state: "AppState",
    on_open: "Callable[[], None]",
) -> None:
    """Build the Undo Tag Edits card.

    Args:
        parent: The parent frame to pack into.
        state:  The shared driver app state (unused by this card).
        on_open: Callback that opens the Undo Tag Edits window.
    """

    def _body(body: tk.Frame) -> None:
        tk.Label(
            body,
            justify="left",
            anchor="w",
            wraplength=680,
            text=(
                "Restore the original tags of your audio files to the way they "
                "were before a batch edit ran.  Every tag-editing tool in the "
                "suite records a snapshot automatically, so you can undo a run "
                "any time afterwards."
            ),
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
        ).pack(anchor="w", pady=(0, 8))

        tk.Button(
            body,
            text="Open Undo",
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief=tk.RAISED,
            cursor="hand2",
            command=on_open,
        ).pack(anchor="w", pady=(2, 2))

    build_card_shell(parent, "Undo Tag Edits", None, _body)
