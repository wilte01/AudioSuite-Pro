"""ui_rows.py - the shared label/entry/slider row builders.

Split out of :mod:`audio_suite_shared.ui_common` in 2.4.3 (WP-9); the facade
re-exports each name, so existing importers are unchanged.

Changed in 2.4.3: split out of ``audio_suite_shared.ui_common``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

import tkinter as tk
from typing import Callable, cast

from . import styles
from .exceptions import AudioConfigurationError


def path_row(
    parent: tk.Misc, label: str, var: tk.StringVar, on_browse: Callable[[], None]
) -> None:
    """Standard label + entry + browse button row."""
    tk.Label(
        parent,
        text=label,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(anchor="w", pady=(6, 0))

    row = tk.Frame(parent, bg=styles.BG_WHITE)
    row.pack(fill="x", pady=3)

    tk.Entry(
        row,
        textvariable=var,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 5))

    tk.Button(
        row,
        text="Browse",
        bg=styles.get_main(),
        fg="white",
        font=styles.FONT_BUTTON,
        command=on_browse,
    ).pack(side=tk.RIGHT)


def slider_row(
    parent: tk.Misc,
    label: str,
    var: tk.Variable,
    from_: float,
    to: float,
    resolution: float,
    label_width: int = 28,
) -> None:
    """Standard label + slider + value readout row."""
    row = tk.Frame(parent, bg=styles.BG_WHITE)
    row.pack(fill="x", pady=1)

    tk.Label(
        row,
        text=f"{label}:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=label_width,
        anchor="w",
    ).pack(side=tk.LEFT)

    tk.Scale(
        row,
        from_=from_,
        to=to,
        resolution=resolution,
        orient=tk.HORIZONTAL,
        variable=cast("tk.DoubleVar", var),
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        troughcolor=styles.BG_LIGHT,
        highlightthickness=0,
        font=styles.FONT_CAPTION,
        length=220,
    ).pack(side=tk.LEFT, padx=6)

    tk.Label(
        row,
        textvariable=var,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        width=6,
    ).pack(side=tk.LEFT)


def discrete_slider_row(
    parent: tk.Frame,
    label: str,
    var: tk.StringVar,
    values: list[float],
    label_width: int = 28,
    value_format: str = "{:.1f}",
) -> None:
    """Standard label + discrete-stop slider + value readout row.

    Unlike slider_row(), which sweeps a continuous range at a fixed
    resolution, this snaps to an explicit list of allowed values that
    need not be evenly spaced (e.g. LUFS presets: -12, -14, -16, -18,
    -23). The underlying tk.Scale operates on stop indices
    (0..len(values) - 1); var is kept in sync with the formatted value
    string at the selected stop, so callers that already read var as a
    plain numeric string (e.g. float(var.get())) require no changes.

    Args:
        parent: Container frame.
        label: Row label text (colon appended automatically). Pass ""
            to omit the row label entirely, e.g. when the caller
            already renders its own heading above the row.
        var: StringVar holding the formatted value string (e.g.
            "-16.0"). Read once on build to select the initial stop —
            matched numerically against values, not by exact string,
            since Tcl's float-to-string conversion when var is set
            programmatically (e.g. from a CLI arg) is not guaranteed
            to match value_format's output. Updated on every drag.
        values: Non-empty list of allowed numeric values, in the order
            they should appear along the slider.
        label_width: Character width reserved for the label.
        value_format: Format spec applied to each value, both for
            display and for the string written back into var.

    Raises:
        AudioConfigurationError: If values is empty.
    """
    if not values:
        raise AudioConfigurationError("discrete_slider_row: values must not be empty")

    formatted = [value_format.format(v) for v in values]

    initial_index = 0
    try:
        current = float(var.get())
        initial_index = min(range(len(values)), key=lambda i: abs(values[i] - current))
    except (TypeError, ValueError):
        pass
    var.set(formatted[initial_index])

    index_var = tk.IntVar(value=initial_index)

    def _sync_index_from_var(*_: object) -> None:
        """Re-sync the Scale position when var is set externally.

        var can be changed after this row is built — e.g. CLI arguments
        applied post-UI-build via UniversalCLIHandler — and the Scale
        must follow, not just the text readout bound to var directly.
        This also fires (harmlessly, to the same index) when _on_move
        writes var in response to a drag.
        """
        try:
            current = float(var.get())
        except (TypeError, ValueError):
            return
        idx = min(range(len(values)), key=lambda i: abs(values[i] - current))
        if idx != index_var.get():
            index_var.set(idx)

    var.trace_add("write", _sync_index_from_var)

    row = tk.Frame(parent, bg=styles.BG_WHITE)
    row.pack(fill="x", pady=1)

    if label:
        tk.Label(
            row,
            text=f"{label}:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=label_width,
            anchor="w",
        ).pack(side=tk.LEFT)

    def _on_move(raw_index: str) -> None:
        idx = int(round(float(raw_index)))
        idx = max(0, min(idx, len(formatted) - 1))
        var.set(formatted[idx])

    tk.Scale(
        row,
        from_=0,
        to=len(values) - 1,
        resolution=1,
        orient=tk.HORIZONTAL,
        variable=index_var,
        showvalue=False,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        troughcolor=styles.BG_LIGHT,
        highlightthickness=0,
        font=styles.FONT_CAPTION,
        length=220,
        command=_on_move,
    ).pack(side=tk.LEFT, padx=6)

    tk.Label(
        row,
        textvariable=var,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        width=6,
    ).pack(side=tk.LEFT)
