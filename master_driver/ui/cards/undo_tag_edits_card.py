"""Undo Tag Edits card for the Master Driver UI.

Unlike the batch tools in the Utilities tab, Undo Tag Edits is opened on
demand and is never part of a batch run.  The card therefore shows a
prominent ``Open Undo`` button instead of a module checkbox.
"""

import tkinter as tk
from typing import TYPE_CHECKING, Callable

from audio_suite_shared import styles

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
    outer = tk.Frame(
        parent,
        bg=styles.BG_LIGHT,
        highlightbackground=styles.FG_SUB,
        highlightthickness=1,
    )
    outer.pack(fill="x", pady=4, padx=2)

    body = tk.Frame(outer, bg=styles.BG_LIGHT, padx=12, pady=10)
    body.pack(fill="x")

    tk.Label(
        body,
        text="Undo Tag Edits",
        font=styles.FONT_TITLE,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(anchor="w")

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
        bg=styles.BG_LIGHT,
        fg=styles.FG_SUB,
    ).pack(anchor="w", pady=(4, 8))

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
