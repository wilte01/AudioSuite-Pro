"""
theme_card.py — Theme Mode settings card.
Collapsible panel matching the ENRICH section style.
"""

import tkinter as tk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles


def _get_label_fg() -> str:
    return styles.FG_MAIN


def build(parent: tk.Frame, state: "AppState") -> None:
    outer = tk.Frame(
        parent,
        bg=styles.BG_LIGHT,
        highlightbackground=styles.FG_SUB,
        highlightthickness=1,
    )
    outer.pack(fill="x", pady=4, padx=2)

    header = tk.Frame(outer, bg=styles.BG_LIGHT)
    header.pack(fill="x", padx=8, pady=4)

    tk.Label(
        header,
        text="Theme Mode",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="▶  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    # Theme options
    theme_options = tk.Frame(body, bg=styles.BG_WHITE)
    theme_options.pack(fill="x")

    for mode in ["Light", "Dark", "System"]:
        _build_theme_row(theme_options, mode, state.theme_mode_var)

    def _toggle() -> None:
        if expanded[0]:
            body.pack_forget()
            expand_var.set("▶  Settings")
        else:
            body.pack(fill="x", padx=4, pady=(0, 4))
            expand_var.set("▼  Settings")
        expanded[0] = not expanded[0]

    tk.Button(
        header,
        textvariable=expand_var,
        font=styles.FONT_CAPTION,
        bg=styles.BG_LIGHT,
        fg=styles.FG_SUB,
        relief=tk.FLAT,
        cursor="hand2",
        command=_toggle,
    ).pack(side=tk.RIGHT)


def _build_theme_row(parent: tk.Frame, mode: str, theme_var: tk.StringVar) -> None:
    """Build a single theme mode radio row."""
    row = tk.Frame(parent, bg=styles.BG_WHITE, pady=6)
    row.pack(fill="x")

    # Radio button
    rb = tk.Radiobutton(
        row,
        text=mode,
        variable=theme_var,
        value=mode,
        font=styles.FONT_LABEL,
        fg=_get_label_fg(),
        bg=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
        selectcolor=styles.BG_WHITE,
        anchor="w",
    )
    rb.pack(side=tk.LEFT)

    # Make clicking anywhere on the row also select the radio
    def _select_mode(event: Any, m: str = mode) -> None:
        theme_var.set(m)

    row.bind("<Button-1>", _select_mode)
