"""Lyrics Manager card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
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

    build_card_shell(
        parent,
        title="Lyrics Manager",
        toggle_var=state.module_toggles["lyrics_manager"],
        body_builder=_body,
    )
