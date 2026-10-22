"""Music Format Converter card for Master Driver UI.

Changed in 2.0.0: renders on the shared card shell instead of a hand-rolled
copy of it, so its open Settings can span both Utilities columns
(PLAN_feature_expansion.md D119).
"""

import tkinter as tk
from tkinter import ttk
from typing import TYPE_CHECKING, Callable, Optional

from audio_suite_shared import styles

from ._card_base import build_card_shell

if TYPE_CHECKING:
    from ...state.app_state import AppState


def build(
    parent: tk.Frame,
    state: "AppState",
    on_browse_output: "Callable[[], None]",
    on_toggle: "Optional[Callable[[], None]]" = None,
) -> None:
    def _body(body: tk.Frame) -> None:
        _build_rows(body, state, on_browse_output)

    build_card_shell(
        parent,
        "Music Format Converter",
        state.converter_toggle,
        _body,
        toggle_command=lambda: (
            on_toggle() if on_toggle and state.converter_toggle.get() else None
        ),
    )


def _build_rows(
    body: tk.Frame, state: "AppState", on_browse_output: "Callable[[], None]"
) -> None:
    """Pack the converter's Settings rows into the shell's body frame."""

    # Detected format label
    state._converter_detected_label = tk.Label(
        body,
        text="",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.get_main(),
    )
    state._converter_detected_label.pack(anchor="w", pady=(0, 6))

    r0 = tk.Frame(body, bg=styles.BG_WHITE)
    r0.pack(fill="x", pady=1)
    tk.Label(
        r0,
        text="Output Format:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    state._converter_format_menu = ttk.Combobox(
        r0,
        textvariable=state.converter_output_format,
        state="readonly",
        width=12,
        font=styles.FONT_BODY,
    )
    state._converter_format_menu["values"] = tuple(state.converter_all_formats)
    state._converter_format_menu.pack(side=tk.LEFT, padx=6)

    r1 = tk.Frame(body, bg=styles.BG_WHITE)
    r1.pack(fill="x", pady=1)
    tk.Label(
        r1,
        text="Quality:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r1,
        textvariable=state.converter_quality,
        state="readonly",
        width=12,
        font=styles.FONT_BODY,
        values=("highest", "high", "medium", "low"),
    ).pack(side=tk.LEFT, padx=6)

    r2 = tk.Frame(body, bg=styles.BG_WHITE)
    r2.pack(fill="x", pady=1)
    tk.Label(
        r2,
        text="Sample Rate:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r2,
        textvariable=state.converter_sample_rate,
        state="readonly",
        width=12,
        font=styles.FONT_BODY,
        values=(
            "source",
            "8000",
            "11025",
            "16000",
            "22050",
            "44100",
            "48000",
            "96000",
        ),
    ).pack(side=tk.LEFT, padx=6)

    r3 = tk.Frame(body, bg=styles.BG_WHITE)
    r3.pack(fill="x", pady=1)
    tk.Label(
        r3,
        text="Bit Depth:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r3,
        textvariable=state.converter_bit_depth,
        state="readonly",
        width=12,
        font=styles.FONT_BODY,
        values=("auto", "16", "24", "32"),
    ).pack(side=tk.LEFT, padx=6)

    r4 = tk.Frame(body, bg=styles.BG_WHITE)
    r4.pack(fill="x", pady=1)
    tk.Label(
        r4,
        text="Target LUFS:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=26,
        anchor="w",
    ).pack(side=tk.LEFT)
    tk.Entry(
        r4,
        textvariable=state.converter_target_lufs,
        width=8,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, padx=6)

    r5 = tk.Frame(body, bg=styles.BG_WHITE)
    r5.pack(fill="x", pady=(6, 1))
    tk.Checkbutton(
        r5,
        text="Normalize MP3 loudness",
        variable=state.converter_normalize_mp3,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(side=tk.LEFT)

    r6 = tk.Frame(body, bg=styles.BG_WHITE)
    r6.pack(fill="x", pady=(2, 1))
    tk.Checkbutton(
        r6,
        text="Delete original files after conversion",
        variable=state.converter_delete_originals,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
    ).pack(side=tk.LEFT)

    tk.Label(
        body,
        text="Output Directory (optional):",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(anchor="w", pady=(8, 2))
    out_f = tk.Frame(body, bg=styles.BG_WHITE)
    out_f.pack(fill="x", pady=(0, 2))
    tk.Entry(
        out_f,
        textvariable=state.converter_output_dir,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 5))
    tk.Button(
        out_f,
        text="Browse",
        command=on_browse_output,
        font=styles.FONT_BUTTON,
        bg=styles.get_main(),
        fg="white",
    ).pack(side=tk.RIGHT)
