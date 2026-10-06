"""ReplayGain Analyzer card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles
from master_driver.ui.cards._card_base import build_card_shell

LUFS_OPTIONS: tuple[float, ...] = (-12.0, -14.0, -16.0, -18.0, -23.0)


def build(parent: tk.Frame, state: "AppState") -> None:
    def _body(body: tk.Frame) -> None:
        row = tk.Frame(body, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=1)
        tk.Label(
            row,
            text="Reference LUFS:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=26,
            anchor="w",
        ).pack(side=tk.LEFT)

        # Use a horizontal slider to pick LUFS. Keep `state.rg_lufs` as a
        # StringVar for compatibility with existing code paths; update it
        # whenever the slider moves.
        # Restrict selectable LUFS values to the allowed set and map a simple
        # integer Scale (0..4) to those values so no other numbers can be chosen.
        try:
            cur = float(state.rg_lufs.get())
        except (OSError, tk.TclError):
            cur = -16.0

        try:
            initial_index = LUFS_OPTIONS.index(cur)
        except ValueError:
            initial_index = LUFS_OPTIONS.index(-16.0)

        def _on_scale(idx_str: str) -> None:
            # Scale passes a string; convert to int index and map to allowed value.
            try:
                idx = int(float(idx_str))
            except (ValueError, IndexError, OSError, tk.TclError):
                return
            val = LUFS_OPTIONS[idx]
            state.rg_lufs.set(f"{val:.1f}")

        scale = tk.Scale(
            row,
            from_=0,
            to=len(LUFS_OPTIONS) - 1,
            resolution=1,
            orient=tk.HORIZONTAL,
            length=160,
            showvalue=False,
            command=_on_scale,
            bg=styles.BG_WHITE,
            troughcolor=styles.BG_LIGHT,
        )
        scale.set(initial_index)
        scale.pack(side=tk.LEFT, padx=6)

        # Numeric readout bound to the same StringVar so the chosen value is visible.
        tk.Label(
            row,
            textvariable=state.rg_lufs,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=6,
            anchor="w",
        ).pack(side=tk.LEFT, padx=(6, 0))

    build_card_shell(
        parent,
        title="ReplayGain Analyzer",
        toggle_var=state.module_toggles["replaygain"],
        body_builder=_body,
    )
