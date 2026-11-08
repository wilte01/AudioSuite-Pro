"""channel_tools_card.py — Channel Tools module card.

Changed in 2.5.0: Channel Tools' Master Driver card (F-E6).
"""

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import channel_ops, styles
from master_driver.ui.cards._card_base import build_card_shell

#: Display label -> shared operation id.  The card lists the ids the CLI
#: accepts, so a value it writes can never be one the child would refuse.
_OPERATION_LABELS: dict[str, str] = {
    spec.label: operation for operation, spec in channel_ops.OPERATIONS.items()
}


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
        r0 = tk.Frame(body, bg=styles.BG_WHITE)
        r0.pack(fill="x", pady=1)
        tk.Label(
            r0,
            text="Channel rule:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=18,
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            r0,
            textvariable=state.channel_tools_operation,
            values=list(channel_ops.OPERATION_IDS),
            state="readonly",
            width=18,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT, padx=6)

        r1 = tk.Frame(body, bg=styles.BG_WHITE)
        r1.pack(fill="x", pady=1)
        tk.Label(
            r1,
            text="Width % (stereo width):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=18,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            r1,
            textvariable=state.channel_tools_width,
            width=6,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

        r2 = tk.Frame(body, bg=styles.BG_WHITE)
        r2.pack(fill="x", pady=1)
        tk.Label(
            r2,
            text="Source / invert side:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=18,
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            r2,
            textvariable=state.channel_tools_source_channel,
            values=["left", "right"],
            state="readonly",
            width=8,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT, padx=4)
        ttk.Combobox(
            r2,
            textvariable=state.channel_tools_invert,
            values=["left", "right", "both"],
            state="readonly",
            width=8,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT, padx=4)

    build_card_shell(
        parent,
        title="Channel Tools",
        toggle_var=state.module_toggles["channel_tools"],
        body_builder=_body,
    )
