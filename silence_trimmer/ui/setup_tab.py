"""setup_tab.py — Setup tab for Silence Trimmer & Fader."""

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_suite_shared import styles, ui_common
from audio_suite_shared.ui_common import BaseSetupFrame


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    threshold: tk.IntVar,
    fade_var: tk.BooleanVar,
    fade_in_duration: tk.IntVar,
    fade_out_duration: tk.IntVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar | None = None,
    parallel_var: tk.BooleanVar | None = None,
    driver_locked: bool = False,
    parallel_mode: tk.BooleanVar | None = None,
    max_workers: tk.IntVar | None = None,
    preset_names: list[str] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Populate the Setup tab.

    Args:
        parent: Parent frame for the tab contents.
        folder_path: StringVar bound to the selected directory path.
        run_mode: StringVar holding 'Dry Run' or 'Live Update'.
        threshold: IntVar for the silence detection threshold in dBFS.
        fade_var: BooleanVar controlling whether fades are applied.
        fade_in_duration: IntVar for the fade-in duration in milliseconds.
        fade_out_duration: IntVar for the fade-out duration in milliseconds.
        on_browse: Callback invoked when the Browse button is clicked.
        on_start: Callback invoked when the Start button is clicked.
        auto_start_var: BooleanVar bound to the Auto Start checkbox.
        auto_end_var: BooleanVar bound to the Auto End checkbox.
        clear_logs_var: Optional BooleanVar for driver mirror clear-logs.
        parallel_var: Optional BooleanVar for driver mirror parallel-run.
        driver_locked: When True, source/mode controls are read-only.
        parallel_mode: BooleanVar for parallel processing toggle.
        max_workers: IntVar for worker count.
        preset_names: Optional list of existing preset names.
        on_save_preset: Callback to save current settings as a preset.
        on_delete_preset: Callback to delete a named preset.
        on_preset_selected: Callback when a preset is selected from the dropdown.

    Returns:
        Dict with keys: start_btn, refresh_presets, preset_combo, controls_panel.
    """
    frame = _SetupFrame(
        parent,
        title="Silence Trimmer & Fader",
        start_text="BEGIN SILENCE TRIMMING",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        driver_locked=driver_locked,
        preset_names=preset_names,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
        threshold=threshold,
        fade_var=fade_var,
        fade_in_duration=fade_in_duration,
        fade_out_duration=fade_out_duration,
        parallel_mode=parallel_mode,
        max_workers=max_workers,
    )
    return {
        "start_btn": frame.start_btn,
        "refresh_presets": frame.refresh_preset_list,
        "preset_combo": frame.preset_combo,
        "controls_panel": frame.controls_panel,
    }


class _SetupFrame(BaseSetupFrame):
    """Silence Trimmer Setup tab skeleton on the shared BaseSetupFrame.

    Silence Trimmer renders its preset row above the run-controls panel, so
    the standard ordering is overridden to keep the existing visual order.
    """

    def __init__(
        self,
        parent: tk.Frame,
        *,
        threshold: tk.IntVar,
        fade_var: tk.BooleanVar,
        fade_in_duration: tk.IntVar,
        fade_out_duration: tk.IntVar,
        parallel_mode: tk.BooleanVar | None = None,
        max_workers: tk.IntVar | None = None,
        **kwargs: Any,
    ) -> None:
        # Tool-specific option state must be bound before super().__init__,
        # which calls _layout() -> _build_options() during construction.
        self._threshold = threshold
        self._fade_var = fade_var
        self._fade_in_duration = fade_in_duration
        self._fade_out_duration = fade_out_duration
        self._parallel_mode = parallel_mode
        self._max_workers = max_workers
        super().__init__(parent, **kwargs)

    def _layout(self) -> None:
        self._add_title()
        self._add_preset_row()
        self._add_controls_panel()
        self._build_options()
        self._add_start_button()

    def _build_options(self) -> None:
        cfg_frame = self.add_config_group("Configuration")
        build_config_panel(
            cfg_frame,
            None,
            self._threshold,
            self._fade_var,
            self._fade_in_duration,
            self._fade_out_duration,
            parallel_mode=self._parallel_mode,
            max_workers=self._max_workers,
        )


def build_config_panel(
    parent: tk.Misc,
    run_mode: tk.StringVar | None,
    threshold: tk.IntVar,
    fade_var: tk.BooleanVar,
    fade_in_duration: tk.IntVar,
    fade_out_duration: tk.IntVar,
    parallel_mode: tk.BooleanVar | None = None,
    max_workers: tk.IntVar | None = None,
) -> None:
    """Reusable configuration panel for Silence Trimmer.

    Args:
        parent: Parent frame to populate.
        run_mode: StringVar for execution mode, or None when embedded.
        threshold: IntVar for the silence detection threshold in dBFS.
        fade_var: BooleanVar controlling whether fades are applied.
        fade_in_duration: IntVar for the fade-in duration in milliseconds.
        fade_out_duration: IntVar for the fade-out duration in milliseconds.
        parallel_mode: BooleanVar for parallel processing toggle.
        max_workers: IntVar for worker count.

    Returns:
        None
    """
    if run_mode is not None:
        mode_frame = tk.Frame(parent, bg=styles.BG_WHITE)
        mode_frame.pack(fill="x", pady=5)
        tk.Label(
            mode_frame,
            text="Execution Mode:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT)
        mode_menu = ttk.Combobox(
            mode_frame,
            textvariable=run_mode,
            font=styles.FONT_BODY,
            state="readonly",
            width=15,
        )
        mode_menu["values"] = ("Dry Run", "Live Update")
        mode_menu.pack(side=tk.LEFT, padx=10)

    ui_common.slider_row(parent, "Silence Threshold (dB)", threshold, -80, -20, 1)

    tk.Checkbutton(
        parent,
        text="Apply Smart Fades",
        variable=fade_var,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
        activeforeground=styles.FG_MAIN,
        font=styles.FONT_BODY_B,
    ).pack(anchor="w", pady=10)

    fade_frame = tk.Frame(parent, bg=styles.BG_WHITE, padx=20)
    fade_frame.pack(fill="x", pady=(0, 5))

    ui_common.slider_row(fade_frame, "Fade-in (ms)", fade_in_duration, 100, 3000, 100)
    ui_common.slider_row(fade_frame, "Fade-out (ms)", fade_out_duration, 100, 5000, 100)

    if parallel_mode is not None and max_workers is not None:
        par_frame = tk.Frame(parent, bg=styles.BG_WHITE)
        par_frame.pack(fill="x", pady=(10, 0))
        tk.Checkbutton(
            par_frame,
            text="Parallel Processing",
            variable=parallel_mode,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
        ).pack(side=tk.LEFT)
        tk.Label(
            par_frame,
            text="Workers:",
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=(12, 2))
        tk.Entry(
            par_frame,
            textvariable=max_workers,
            width=4,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT)
        tk.Label(
            par_frame,
            text="(I/O-bound trim always threaded; --parallel for CLI consistency)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=10)
