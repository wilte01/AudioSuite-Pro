"""ReplayGain Analyzer card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from audio_suite_shared import styles

LUFS_OPTIONS: tuple[float, ...] = (-12.0, -14.0, -16.0, -18.0, -23.0)


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
        variable=state.module_toggles["replaygain"],
        bg=styles.BG_LIGHT,
        activebackground=styles.BG_LIGHT,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text="ReplayGain Analyzer",
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="▶  Settings")
    expanded = [False]
    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

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
