"""
palette_card.py — Colour Palette settings card.
Collapsible panel matching the ENRICH section style.
"""

import logging
import tkinter as tk
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from audio_suite_shared.styles import PALETTES

_log = logging.getLogger(__name__)


def _get_label_fg() -> str:
    return styles.FG_MAIN


def _get_sublabel_fg() -> str:
    return styles.FG_SUB


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
        text="Colour Palette",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="▶  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    # Palette options
    options_frame = tk.Frame(body, bg=styles.BG_WHITE)
    options_frame.pack(fill="x")

    # Resolve each swatch rather than reading PALETTES directly, so the
    # Windows Accent row previews the accent actually in force instead of the
    # static placeholder (iteration-6 B4).
    for name in PALETTES:
        _build_palette_row(
            options_frame, name, styles._resolve_palette(name), state.palette_var
        )

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


def _build_palette_row(
    parent: tk.Frame,
    name: str,
    colours: dict[str, str],
    palette_var: tk.StringVar,
) -> None:
    """Build a single palette radio row with swatches."""
    # If this is the "Windows Accent" row, we want to show the CURRENT
    # system accent colors
    display_colours = colours
    if name == "Windows Accent":
        try:
            import winaccent

            display_colours = {
                "main": winaccent.accent_normal,
                "dark": winaccent.accent_dark,
                "bg_light": winaccent.accent_light,
                "bg_white": "#ffffff",
            }
        except ImportError:
            # Fallback if winaccent isn't installed
            pass
        except (OSError, tk.TclError) as _exc:
            _log.debug("palette_card fallback: %s", _exc, exc_info=True)

    row = tk.Frame(parent, bg=styles.BG_WHITE, pady=6)
    row.pack(fill="x")

    # Radio button
    rb = tk.Radiobutton(
        row,
        text=name,
        variable=palette_var,
        value=name,
        font=styles.FONT_LABEL,
        fg=_get_label_fg(),
        bg=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
        selectcolor=styles.BG_WHITE,
        width=10,
        anchor="w",
    )
    rb.pack(side=tk.LEFT)

    # Swatches — main and dark
    for key, tooltip in [
        ("main", "Primary"),
        ("dark", "Dark"),
        ("bg_light", "Background"),
    ]:
        swatch_frame = tk.Frame(row, bg=styles.BG_WHITE)
        swatch_frame.pack(side=tk.LEFT, padx=(4, 0))

        swatch = tk.Frame(
            swatch_frame,
            bg=display_colours[key],
            width=32,
            height=20,
            relief="flat",
            highlightbackground="#cccccc",
            highlightthickness=1,
        )
        swatch.pack()
        swatch.pack_propagate(False)

        tk.Label(
            swatch_frame,
            text=display_colours[key],
            font=styles.FONT_MONO,
            fg=_get_sublabel_fg(),
            bg=styles.BG_WHITE,
        ).pack()

    # Make clicking anywhere on the row also select the radio
    def _select_palette(event: Any, n: str = name) -> None:
        palette_var.set(n)

    row.bind("<Button-1>", _select_palette)
