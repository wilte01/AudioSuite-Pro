"""
typography_card.py — Typography settings card.
Collapsible panel matching the ENRICH section style.
"""

import sys
import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState
from tkinter import ttk

from audio_suite_shared import styles

# Build a font list appropriate for the current OS.  Segoe UI / Tahoma are
# Windows-only; macOS ships Helvetica Neue / Menlo; Linux typically has the
# DejaVu and Liberation families.  The cross-platform staples are always
# included so users can choose a neutral option on any platform.
_PLATFORM_FONTS: dict[str, list[str]] = {
    "win32": ["Segoe UI", "Tahoma"],
    "darwin": ["Helvetica Neue", "Menlo"],
}
_FONT_OPTIONS: list[str] = [
    "Arial",
    "Courier New",
    "Verdana",
    "Times New Roman",
] + _PLATFORM_FONTS.get(sys.platform, ["DejaVu Sans", "Liberation Sans"])


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
        text="Typography",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="▶  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    # Font Family
    font_row = tk.Frame(body, bg=styles.BG_WHITE)
    font_row.pack(fill="x", pady=(0, 10))
    tk.Label(
        font_row,
        text="Font Family:",
        font=styles.FONT_LABEL_B,
        width=12,
        anchor="w",
        bg=styles.BG_WHITE,
        fg=_get_label_fg(),
    ).pack(side="left")
    font_combo = ttk.Combobox(
        font_row,
        textvariable=state.font_family_var,
        values=_FONT_OPTIONS,
        state="readonly",
        width=15,
        font=styles.FONT_BODY,
    )
    font_combo.pack(side="left")

    # Font Sizes Grid
    tk.Label(
        body,
        text="Sizes:",
        font=styles.FONT_LABEL_B,
        width=12,
        anchor="w",
        bg=styles.BG_WHITE,
        fg=_get_label_fg(),
    ).pack(fill="x", pady=(10, 5))

    sizes_frame = tk.Frame(body, bg=styles.BG_WHITE)
    sizes_frame.pack(fill="x")

    # Layout the 9 spinboxes in 3 rows x 3 columns
    for i, (key, var) in enumerate(state.font_sizes_vars.items()):
        row = i // 3
        col = i % 3

        cell = tk.Frame(sizes_frame, bg=styles.BG_WHITE, padx=0, pady=5)
        cell.grid(row=row, column=col, sticky="w", padx=(0, 20))

        tk.Label(
            cell,
            text=f"{key}:",
            font=styles.FONT_LABEL,
            width=8,
            anchor="w",
            bg=styles.BG_WHITE,
            fg=_get_label_fg(),
        ).pack(side="left")
        ttk.Spinbox(
            cell,
            textvariable=var,
            from_=5,
            to=36,
            increment=1,
            width=4,
            font=styles.FONT_BODY,
        ).pack(side="left")

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
