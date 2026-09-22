"""
processing_tab.py — Processing tab for ASX Playlist Extractor.

Returns an update_step(index, state, suffix) callable so app.py can
drive step animations without knowing how the labels are stored.
"""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared import styles

# Status colours — processing-tab specific, not in shared palette
C_GREEN = styles.COLOR_SUCCESS
C_GRAY = styles.FG_SUB

STEPS = [
    "Scanning directory for ASX files",
    "Parsing ASX file contents",
    "Verifying source audio & paths",
    "Copying audio to target directory",
    "Removing/Trashing original ASX files",
    "Finalizing Priority Error Log",
]


def build(parent: tk.Frame) -> Callable[..., Any]:
    """
    Populate the Processing tab.

    Returns:
        update_step(index, state, suffix="") — animates one step label.
        state is 'active' (purple arrow) or 'done' (green tick).
    """
    container = tk.Frame(parent, padx=50, pady=50, bg=styles.BG_WHITE)
    container.pack(fill="both", expand=True)

    tk.Label(
        container,
        text="Process Status",
        font=styles.FONT_HEADER,
        fg=styles.get_dark(),
        bg=styles.BG_WHITE,
    ).pack(anchor="w", pady=(0, 20))

    step_labels = []
    for step in STEPS:
        lbl = tk.Label(
            container,
            text=f"  {step}",
            font=styles.FONT_TITLE,
            fg=C_GRAY,
            bg=styles.BG_WHITE,
        )
        lbl.pack(anchor="w", pady=8)
        step_labels.append(lbl)

    def update_step(index: int, state: str, suffix: str = "") -> None:
        icon = "▶ " if state == "active" else "✔ "
        color = styles.get_main() if state == "active" else C_GREEN
        step_labels[index].config(
            text=f"{icon}{STEPS[index]}{suffix}",
            fg=color,
        )

    def reset_steps() -> None:
        for lbl, step_text in zip(step_labels, STEPS):
            lbl.config(text=f"  {step_text}", fg=C_GRAY)

    # Bundle both callables; reset_steps used by app on each new run.
    # Deliberate dynamic attribute — consumers store this callable as Any.
    update_step.reset = reset_steps  # type: ignore[attr-defined]
    return update_step
