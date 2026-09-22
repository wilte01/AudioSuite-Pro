"""
setup_tab.py
Setup tab for Pop & Click Remover.

Changes from original
---------------------
* Max Click Width is now a Scale widget (1–10 ms) rather than a free-text
  Entry, preventing invalid values from reaching the declicker.
* sys.path manipulation removed — the suite root is now resolved once
  in app.py; setup_tab.py can rely on the import having already succeeded.
* Label alignment is consistent (no more mixed indentation in keyword args).

Note on sensitivity semantics
-----------------------------
The Click Sensitivity slider runs 0.01–0.40 and maps directly to the
``threshold`` parameter of :func:`declicker.declick_audio`: LOWER values
are MORE aggressive (detect quieter clicks), matching the original
semantics documented in declicker.py and cli_args.py. No inversion or
relabeling is implemented here.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_suite_shared import styles, ui_common
from audio_suite_shared.ui_common import BaseSetupFrame


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    sensitivity: tk.DoubleVar,
    max_width: tk.IntVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    preset_names: list[str] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
    clear_logs_var: tk.BooleanVar | None = None,
    parallel_var: tk.BooleanVar | None = None,
    driver_locked: bool = False,
) -> dict[str, Any]:
    """
    Populate the Setup tab and return the Start button, preset list refresher,
    and preset combo box.

    All validation of user-supplied values is enforced by widget constraints
    (Scale ranges, Combobox readonly) so that invalid values never reach the
    processing layer.

    Parameters
    ----------
    parent : tk.Frame
        The notebook frame to build into.
    folder_path : tk.StringVar
        Bound to the directory path entry.
    run_mode : tk.StringVar
        Bound to the execution-mode combobox (``"Dry Run"`` or ``"Live Update"``).
    sensitivity : tk.DoubleVar
        Bound to the click-sensitivity slider (0.01–0.40).
    max_width : tk.IntVar
        Bound to the max-click-width slider (1–10 ms).
    on_browse : Callable[[], None]
        Callback invoked when the Browse button is clicked.
    on_start : Callable[[], None]
        Callback invoked when the Start button is clicked.
    preset_names : list[str] | None
        Initial list of saved preset names for the combobox.
    on_save_preset : Callable[[str], None] | None
        Callback invoked to save the current settings as a named preset.
    on_delete_preset : Callable[[str], None] | None
        Callback invoked to delete a named preset.
    on_preset_selected : Callable[[str], None] | None
        Callback invoked when a preset is selected from the combobox.

    Returns
    -------
    dict[str, Any]
        Keys: ``start_btn``, ``refresh_preset_list``, ``preset_combo``,
        ``controls_panel``.
    """
    frame = _SetupFrame(
        parent,
        title="Pop & Click Remover",
        start_text="BEGIN POP & CLICK REMOVAL",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        preset_names=preset_names,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        driver_locked=driver_locked,
        sensitivity=sensitivity,
        max_width=max_width,
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """Pop & Click Remover Setup tab built on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        sensitivity: tk.DoubleVar,
        max_width: tk.IntVar,
        **kwargs: Any,
    ) -> None:
        self._sensitivity = sensitivity
        self._max_width = max_width
        super().__init__(parent, **kwargs)

    def _layout(self) -> None:
        """Presets sit above the Run Controls panel for this tool."""
        self._add_title()
        self._add_preset_row()
        if self._include_controls_panel:
            self._add_controls_panel()
        self._build_options()
        self._add_start_button()

    def _build_options(self) -> None:
        # ── Configuration LabelFrame ──────────────────────────────────────────
        cfg = self.add_config_group("Configuration")

        build_config_panel(cfg, None, self._sensitivity, self._max_width)


def build_config_panel(
    parent: tk.Misc,
    run_mode: tk.StringVar | None,
    sensitivity: tk.DoubleVar,
    max_width: tk.IntVar,
) -> None:
    """
    Reusable configuration panel for Pop & Click Remover.

    Parameters
    ----------
    parent : tk.Frame
        Container frame for the configuration controls.
    run_mode : tk.StringVar | None
        Execution-mode variable.  Pass ``None`` when embedding this panel
        inside a host that manages mode selection externally (e.g. Master Driver).
    sensitivity : tk.DoubleVar
        Click-sensitivity slider variable (0.01–0.40).
    max_width : tk.IntVar
        Max-click-width slider variable (1–10 ms).
    """
    if run_mode is not None:
        mode_row = tk.Frame(parent, bg=styles.BG_WHITE)
        mode_row.pack(fill="x", pady=5)

        tk.Label(
            mode_row,
            text="Execution Mode:",
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
        ).pack(side=tk.LEFT)

        mode_menu = ttk.Combobox(
            mode_row,
            textvariable=run_mode,
            font=styles.FONT_BODY,
            state="readonly",
            width=15,
        )
        mode_menu["values"] = ("Dry Run", "Live Update")
        mode_menu.pack(side=tk.LEFT, padx=10)

        tk.Label(
            mode_row,
            text="Dry Run detects clicks without modifying files.",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(0, 5))

    # Click sensitivity ────────────────────────────────────────────────────────
    ui_common.slider_row(parent, "Click Sensitivity", sensitivity, 0.01, 0.40, 0.01)

    # Max click width ─────────────────────────────────────────────────────────
    ui_common.slider_row(parent, "Max Click Width (ms)", max_width, 1, 10, 1)
