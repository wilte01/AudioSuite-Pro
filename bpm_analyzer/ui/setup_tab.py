"""
setup_tab.py
Builds the Setup tab widgets for BPM Analyzer.
Receives parent frame and tk variables; returns a dict of widgets.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_suite_shared import styles, suite_config
from audio_suite_shared.ui_common import BaseSetupFrame


def _load_preset_names() -> list[str]:
    """Load the stored BPM preset names from the shared config."""
    raw = suite_config.load_value("bpm_presets_list", None)
    names_json: str | None = raw if isinstance(raw, str) else None
    return json.loads(names_json) if names_json else []


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    bpm_range_min: tk.IntVar,
    bpm_range_max: tk.IntVar,
    analysis_duration: tk.IntVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    driver_locked: bool = False,
    parallel_mode: tk.BooleanVar | None = None,
    max_workers: tk.IntVar | None = None,
    on_preset_selected: Callable[[object], None] | None = None,
    on_save_preset: Callable[[], None] | None = None,
    on_delete_preset: Callable[[], None] | None = None,
) -> dict[str, Any]:
    """
    Populate the Setup tab.

    Args:
        parent:              The tab Frame to populate.
        folder_path:         StringVar bound to folder entry.
        run_mode:            StringVar for Dry Run / Live Update combobox.
        bpm_range_min:       IntVar for minimum BPM entry.
        bpm_range_max:       IntVar for maximum BPM entry.
        analysis_duration:   IntVar for analysis duration entry.
        auto_start_var:      BooleanVar bound to the Auto Start checkbox.
        auto_end_var:        BooleanVar bound to the Auto End checkbox.
        clear_logs_var:      Tk variable mirroring the driver's Clear Logs
                             state (checkbox stays inert).
        parallel_var:        Tk variable mirroring the driver's Parallel
                             state (checkbox stays inert).
        on_browse:           Callback for Browse button.
        on_start:            Callback for Begin button.
        driver_locked:       True when launched via the Master Driver; locks
                             the Run Controls panel to inherited values.
        parallel_mode:       BooleanVar for the tool-specific parallel
                             processing toggle (functional worker setting).
        max_workers:         IntVar for worker count.
        on_preset_selected:  Callback for preset combobox selection.
        on_save_preset:      Callback for Save Preset button.
        on_delete_preset:    Callback for Delete Preset button.

    Returns:
        Dict with keys: start_btn (tk.Button), preset_combo (ttk.Combobox),
        refresh_preset_list (Callable[[], None]), controls_panel.
    """
    frame = _SetupFrame(
        parent,
        title="BPM Analyzer & Tagger",
        start_text="BEGIN BPM ANALYSIS",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        driver_locked=driver_locked,
        preset_loader=_load_preset_names,
        bpm_range_min=bpm_range_min,
        bpm_range_max=bpm_range_max,
        analysis_duration=analysis_duration,
        parallel_mode=parallel_mode,
        max_workers=max_workers,
        on_preset_selected=on_preset_selected,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """BPM Analyzer Setup tab skeleton on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        *,
        bpm_range_min: tk.IntVar,
        bpm_range_max: tk.IntVar,
        analysis_duration: tk.IntVar,
        parallel_mode: tk.BooleanVar | None = None,
        max_workers: tk.IntVar | None = None,
        on_preset_selected: Callable[[object], None] | None = None,
        on_save_preset: Callable[[], None] | None = None,
        on_delete_preset: Callable[[], None] | None = None,
        **kwargs: Any,
    ) -> None:
        # Tool-specific option state must be bound before super().__init__,
        # which calls _layout() -> _build_options() during construction.
        self._bpm_range_min = bpm_range_min
        self._bpm_range_max = bpm_range_max
        self._analysis_duration = analysis_duration
        self._parallel_mode = parallel_mode
        self._max_workers = max_workers
        # BPM Analyzer's app drives Save/Delete through its own zero-argument
        # callbacks (which open simpledialog prompts), so capture them here
        # rather than through the base's name-taking preset API.
        self._bpm_on_preset_selected = on_preset_selected
        self._bpm_on_save_preset = on_save_preset
        self._bpm_on_delete_preset = on_delete_preset
        super().__init__(parent, **kwargs)

    def _add_preset_row(self) -> None:
        # BPM Analyzer renders its preset row with Save/Delete buttons that
        # invoke its zero-argument app callbacks (simpledialog prompts); this
        # cannot be expressed through the base's shared dialog, so replicate
        # the original row verbatim. Refresh uses the base loader.
        if self._bpm_on_save_preset is None:
            self.preset_combo = None
            return

        preset_frame = tk.Frame(self, bg=styles.BG_WHITE)
        preset_frame.pack(fill="x", pady=(0, 15))
        tk.Label(
            preset_frame,
            text="Preset:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(0, 5))
        combo = ttk.Combobox(
            preset_frame,
            state="readonly",
            font=styles.FONT_BODY,
            width=25,
        )
        combo.pack(side=tk.LEFT, padx=(0, 5))
        self.preset_combo = combo

        on_selected = self._bpm_on_preset_selected
        if on_selected is not None:
            combo.bind("<<ComboboxSelected>>", on_selected)

        def _do_save() -> None:
            if self._bpm_on_save_preset is not None:
                self._bpm_on_save_preset()

        def _do_delete() -> None:
            if self._bpm_on_delete_preset is not None:
                self._bpm_on_delete_preset()

        tk.Button(
            preset_frame,
            text="Save",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=_do_save,
        ).pack(side=tk.LEFT, padx=(0, 3))
        tk.Button(
            preset_frame,
            text="Delete",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=_do_delete,
        ).pack(side=tk.LEFT)

    def _build_options(self) -> None:
        # --- BPM Range ---
        tk.Label(
            self,
            text="BPM Range (Min - Max):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(15, 0))
        range_frame = tk.Frame(self, bg=styles.BG_WHITE)
        range_frame.pack(anchor="w", pady=5)
        tk.Entry(
            range_frame,
            textvariable=self._bpm_range_min,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT)
        tk.Label(
            range_frame,
            text=" to ",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT, padx=5)
        tk.Entry(
            range_frame,
            textvariable=self._bpm_range_max,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT)
        tk.Label(
            self,
            text="(Detected BPM will be constrained to this range)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

        # --- Analysis duration ---
        tk.Label(
            self,
            text="Analysis Duration (seconds):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(15, 0))
        tk.Entry(
            self,
            textvariable=self._analysis_duration,
            width=10,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(anchor="w", pady=5)
        tk.Label(
            self,
            text="(Lower values = faster processing, less accuracy)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

        # --- Parallel processing (tool-specific worker setting) ---
        if self._parallel_mode is not None and self._max_workers is not None:
            self.add_parallel_row(
                self._parallel_mode,
                self._max_workers,
                "(ProcessPoolExecutor bypasses GIL for CPU-bound FFT)",
            )
