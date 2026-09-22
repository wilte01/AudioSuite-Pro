"""Library Statistics card for Master Driver UI."""

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles


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

    tk.Checkbutton(
        header,
        variable=state.library_stats_toggle,
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text="Library Statistics Dashboard",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="\u25b6  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    tk.Label(
        body,
        text="Scans your music library by reading existing tags and displays\n"
        "the aggregated data in an interactive GUI with charts.",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        justify=tk.LEFT,
    ).pack(anchor="w", pady=(0, 6))

    r0 = tk.Frame(body, bg=styles.BG_WHITE)
    r0.pack(fill="x", pady=1)
    tk.Label(
        r0,
        text="Scan Mode:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r0,
        textvariable=state.library_stats_incremental,
        state="readonly",
        width=12,
        font=styles.FONT_BODY,
        values=("full", "incremental"),
    ).pack(side=tk.LEFT, padx=6)

    r1 = tk.Frame(body, bg=styles.BG_WHITE)
    r1.pack(fill="x", pady=1)
    tk.Checkbutton(
        r1,
        text="Refresh all cached data",
        variable=state.library_stats_refresh,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(side=tk.LEFT)

    r2 = tk.Frame(body, bg=styles.BG_WHITE)
    r2.pack(fill="x", pady=1)
    tk.Checkbutton(
        r2,
        text="Show tag completeness analysis",
        variable=state.library_stats_completeness,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(side=tk.LEFT)

    r3 = tk.Frame(body, bg=styles.BG_WHITE)
    r3.pack(fill="x", pady=1)
    tk.Label(
        r3,
        text="Detail Category:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r3,
        textvariable=state.library_stats_detail,
        state="readonly",
        width=16,
        font=styles.FONT_BODY,
        values=(
            "",
            "bpm",
            "key",
            "genre",
            "mood",
            "tempo_marking",
            "album_art",
            "replaygain",
        ),
    ).pack(side=tk.LEFT, padx=6)

    r4 = tk.Frame(body, bg=styles.BG_WHITE)
    r4.pack(fill="x", pady=1)
    tk.Label(
        r4,
        text="Export CSV (optional):",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    tk.Entry(
        r4,
        textvariable=state.library_stats_export_csv,
        width=24,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, padx=6)

    r5 = tk.Frame(body, bg=styles.BG_WHITE)
    r5.pack(fill="x", pady=1)
    tk.Label(
        r5,
        text="Export JSON (optional):",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    tk.Entry(
        r5,
        textvariable=state.library_stats_export_json,
        width=24,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, padx=6)

    def _toggle() -> None:
        if expanded[0]:
            body.pack_forget()
            expand_var.set("\u25b6  Settings")
        else:
            body.pack(fill="x", padx=4, pady=(0, 4))
            expand_var.set("\u25bc  Settings")
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
