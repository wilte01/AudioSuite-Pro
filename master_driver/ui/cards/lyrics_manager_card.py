"""Lyrics Manager card for Master Driver UI."""

import tkinter as tk
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
        variable=state.module_toggles["lyrics_manager"],
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text="Lyrics Manager",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="▶  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    tk.Label(
        body,
        text="Fetches synced and plain lyrics from online sources and embeds "
        "them into audio tags (synced with plain-text fallback).",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        wraplength=680,
        justify="left",
        anchor="w",
    ).pack(anchor="w", pady=(0, 6))

    r0 = tk.Frame(body, bg=styles.BG_WHITE)
    r0.pack(fill="x", pady=1)
    tk.Label(
        r0,
        text="Lyric Source:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    tk.Entry(
        r0,
        textvariable=state.lyrics_provider,
        width=16,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, padx=6)

    r1 = tk.Frame(body, bg=styles.BG_WHITE)
    r1.pack(fill="x", pady=1)
    tk.Label(
        r1,
        text="Request Timeout (s):",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    tk.Entry(
        r1,
        textvariable=state.lyrics_request_timeout,
        width=8,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, padx=6)

    tk.Checkbutton(
        body,
        variable=state.lyrics_skip_existing,
        text="Skip files that already have lyrics",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(anchor="w", pady=1)

    tk.Checkbutton(
        body,
        variable=state.lyrics_plain_fallback,
        text="Store plain lyrics when no synced lyrics are available",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(anchor="w", pady=1)

    r2 = tk.Frame(body, bg=styles.BG_WHITE)
    r2.pack(fill="x", pady=1)
    tk.Checkbutton(
        r2,
        variable=state.lyrics_parallel,
        text="Parallel Processing",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(side=tk.LEFT)
    tk.Label(
        r2,
        text="Workers:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        anchor="e",
    ).pack(side=tk.LEFT, padx=(12, 2))
    tk.Entry(
        r2,
        textvariable=state.lyrics_workers,
        width=4,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT)

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
