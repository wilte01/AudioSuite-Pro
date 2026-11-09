"""
ui/setup_tab.py
Setup tab for Audio Refinery.

Displays four collapsible stage panels in fixed pipeline order:
  1. Pop & Click Remover
  2. Silence Trimmer / Fader
  3. Audio Enhancer
  4. Audio Normaliser

Each panel has:
  - A checkbox to enable/disable the stage
  - An expand/collapse toggle revealing that stage's full settings
  - Settings identical to those in the standalone program

Output Gain in the Enhancer panel is hidden when the Normaliser is active.

Changed in 1.1.0: added the Sprint 1 effect controls to the enhancer
panel and fixed the Custom-mode sliders so they write back to
config.enhance_params (D24).

Changed in 2.6.0 (U-04): the Declick, Trim and Normalise panels write their
controls back into the stage params the way the enhancer panel already did.
Before, each panel bound a throwaway Tk variable, so moving REFINE's Click
Sensitivity, Trim Threshold or Target LUFS slider changed a value nobody read
and the run used the stored setting. The Normalise panel also gained the
standalone Audio Normalizer's true-peak ceiling, LRA target and lossless MP3
strategy, which have no other surface once the standalone window is gone.
Changed in 2.3.1: the widget's text colours follow the suite theme instead of
Tk's symbolic defaults (PLAN_restoration_2026-10-31.md T-02).

Changed in 2.4.1: the enhancer panel's preset combobox values are built
with ``preset_text(preset)`` - the shared model's single display
accessor - instead of ``preset.value``, so an enum-base change cannot
rewrite a label. The rendered strings are unchanged (WP-0).
"""

from __future__ import annotations

import itertools
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, cast

import audio_enhancer.ui.setup_tab as enhancer_ui
import audio_normalizer.ui.setup_tab as normalise_ui
import pop_click_remover.ui.setup_tab as declick_ui
import silence_trimmer.ui.setup_tab as trim_ui
from audio_refinery.core.models import StageConfig
from audio_suite_shared import styles, ui_common
from audio_suite_shared.dsp_models import (
    PRESETS,
    EnhancementParams,
    PresetName,
    preset_text,
)
from audio_suite_shared.ui_driver_controls import DriverControlsPanel

_MODE_VAR_IDS = itertools.count()


def build(
    parent: tk.Frame,
    source_path: tk.StringVar,
    output_path: "tk.StringVar | None",
    config: StageConfig,
    on_browse_src: Callable[..., Any],
    on_browse_out: Callable[..., Any],
    on_start: Callable[..., Any],
    on_reset: Callable[..., Any],
    embedded: bool = False,
    after_paths: "Callable[..., Any] | None" = None,
    after_stages: "Callable[..., Any] | None" = None,
    preset_names: "list[str] | None" = None,
    on_save_preset: "Callable[[str], None] | None" = None,
    on_delete_preset: "Callable[[str], None] | None" = None,
    on_preset_selected: "Callable[[str], None] | None" = None,
    auto_start_var: "tk.BooleanVar | None" = None,
    auto_end_var: "tk.BooleanVar | None" = None,
    clear_logs_var: "tk.BooleanVar | None" = None,
    parallel_var: "tk.BooleanVar | None" = None,
    driver_locked: bool = False,
    mode_var: "tk.StringVar | None" = None,
) -> dict[str, Any]:
    """Populate the Setup tab.

    Args:
        parent: The tab Frame to populate.
        source_path: StringVar bound to the source directory entry.
        output_path: Optional StringVar for the output directory.
        config: Pipeline stage configuration.
        on_browse_src: Callback for the source Browse button.
        on_browse_out: Callback for the output Browse button.
        on_start: Callback for the Start button.
        on_reset: Callback for the Reset Progress button.
        embedded: When True, hide the title and subtitle labels.
        after_paths: Optional callback injected after path rows.
        after_stages: Optional callback injected after stage panels.
        preset_names: Optional list of saved preset names.
        on_save_preset: Optional callback to save a preset.
        on_delete_preset: Optional callback to delete a preset.
        on_preset_selected: Optional callback when a preset is selected.
        auto_start_var: Mirrors the driver's Auto Start (display only).
        auto_end_var: Mirrors the driver's Auto End.
        clear_logs_var: Mirrors the driver's Clear Logs (display only).
        parallel_var: Mirrors the driver's Parallel option (display only).
        driver_locked: True after a Master Driver launch — locks the
            Run Controls panel to the inherited values.
        mode_var: Optional StringVar bound to the panel's Mode combo. If
            omitted a default ``"Dry Run"`` var is created and kept alive
            for the panel's lifetime. Callers (Master Driver, standalone
            app) should pass their persistent run-mode var so the value
            always displays and reflects the real execution mode.

    Returns:
        Dict with keys: start_btn, reset_btn, controls_panel, state_dict.
    """
    frame = tk.Frame(parent, padx=24, pady=16, bg=styles.BG_WHITE)
    frame.pack(expand=True, fill="both")

    if not embedded:
        tk.Label(
            frame,
            text="Audio Refinery",
            font=styles.FONT_TITLE,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
        ).pack(pady=(0, 4))

        tk.Label(
            frame,
            text="Single-pass pipeline: Declick  →  Trim  →  Noise Reduction  "
            "→  Enhance  →  Normalise",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
        ).pack(pady=(0, 12))

    _state: dict[str, Any] = {}

    # ── Presets ───────────────────────────────────────────────────────────────
    if on_save_preset is not None:
        preset_row = tk.Frame(frame, bg=styles.BG_WHITE)
        preset_row.pack(fill="x", pady=(0, 8))
        tk.Label(
            preset_row,
            text="Presets:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(0, 5))

        def _refresh_preset_list(names: list[str]) -> None:
            _state["preset_combo"]["values"] = names

        _state["refresh_preset_list"] = _refresh_preset_list

        _state["preset_combo"] = ttk.Combobox(
            preset_row,
            state="readonly",
            font=styles.FONT_BODY,
            width=28,
        )
        _state["preset_combo"]["values"] = preset_names or []
        _state["preset_combo"].pack(side=tk.LEFT, padx=(0, 5))

        def _on_preset_select(_event: object = None) -> None:
            name = _state["preset_combo"].get()
            if name and on_preset_selected:
                on_preset_selected(name)

        _state["preset_combo"].bind("<<ComboboxSelected>>", _on_preset_select)

        tk.Button(
            preset_row,
            text="Save",
            command=lambda: _save_preset_dialog(_state["preset_combo"], on_save_preset),
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BODY,
            padx=8,
        ).pack(side=tk.LEFT, padx=(0, 3))

        tk.Button(
            preset_row,
            text="Delete",
            command=lambda: _delete_preset_action(
                _state["preset_combo"], on_delete_preset
            ),
            bg="#cc5555",
            fg="white",
            font=styles.FONT_BODY,
            padx=8,
        ).pack(side=tk.LEFT)

    # ── Run Controls panel (mirrors the Master Driver control strip) ──────
    if mode_var is None:
        # Keep the default mode var alive for the panel's lifetime — a bare
        # inline StringVar would otherwise be garbage-collected, destroying
        # its Tcl variable and leaving the Mode combobox blank.  The name is
        # pinned so a shared Tk root (used by tests) cannot recycle the
        # variable's Tcl name underneath the panel.
        mode_var = tk.StringVar(
            parent, value="Dry Run", name=f"_refinery_mode_{next(_MODE_VAR_IDS)}"
        )
        _state["mode_var"] = mode_var
    controls_panel = DriverControlsPanel(
        frame,
        source_var=source_path,
        mode_var=mode_var,
        auto_start_var=auto_start_var or tk.BooleanVar(value=False),
        auto_end_var=auto_end_var or tk.BooleanVar(value=False),
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse_src,
    )
    controls_panel.pack(fill="x", pady=(0, 15))
    controls_panel.set_driven(driver_locked)

    _state["controls_panel"] = controls_panel

    # Output path (only add if provided)
    if output_path is not None:
        ui_common.path_row(
            frame, "Output folder (blank = in-place):", output_path, on_browse_out
        )

    # ── Optional injected widgets ──────────────────────────────────────────────
    if after_paths is not None:
        after_paths(frame)

    # ── Stage panels ──────────────────────────────────────────────────────────
    stages_frame = tk.Frame(frame, bg=styles.BG_WHITE)
    stages_frame.pack(fill="x", pady=(10, 0))

    # Keep a reference to the enhancer output_gain row so we can show/hide it

    # Store BooleanVar references for SELECT ALL functionality
    stage_vars: dict[str, Any] = {}

    _build_declick_panel(stages_frame, config, embedded, stage_vars)
    _state["trim_widgets"] = _build_trim_panel(
        stages_frame, config, embedded, stage_vars
    )
    _build_noise_reduction_panel(stages_frame, config, embedded, stage_vars)
    _build_enhance_panel(stages_frame, config, _state, stage_vars)
    _build_normalise_panel(stages_frame, config, _state, embedded, stage_vars)

    # Store stage_vars in the main state for access by Master Driver
    _state["stage_vars"] = stage_vars

    # Wire up the Output Gain visibility toggle after both panels exist
    def _update_output_gain_visibility(*_args: Any) -> None:
        panel = _state.get("dsp_panel")
        if panel is None:
            return
        # The pipeline already zeroes output gain when the Normaliser runs; the
        # row is hidden so the UI does not offer a control that has no effect.
        panel.set_field_visible("output_gain_db", not config.normalise)

    # Trigger on normalise checkbox change
    _state["normalise_toggle_cb"] = _update_output_gain_visibility
    _update_output_gain_visibility()

    # Call after_stages callback if provided
    if after_stages is not None:
        after_stages(frame)

    # ── Bottom buttons ────────────────────────────────────────────────────────
    btn_frame = tk.Frame(frame, bg=styles.BG_WHITE)
    btn_frame.pack(side=tk.BOTTOM, fill="x", pady=(12, 0))

    reset_btn = tk.Button(
        btn_frame,
        text="Reset Progress",
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
        font=styles.FONT_BUTTON,
        command=on_reset,
    )
    reset_btn.pack(side=tk.LEFT)

    start_btn = tk.Button(
        btn_frame,
        text="BEGIN REFINERY",
        bg=styles.get_main(),
        fg="white",
        font=styles.FONT_BUTTON,
        height=2,
        command=on_start,
    )
    start_btn.pack(side=tk.RIGHT, fill="x", expand=True, padx=(8, 0))

    return {
        "start_btn": start_btn,
        "reset_btn": reset_btn,
        "controls_panel": controls_panel,
        **_state,
    }


# ── Preset helpers ───────────────────────────────────────────────────────────


def _save_preset_dialog(
    combo: ttk.Combobox,
    on_save: "Callable[[str], None]",
) -> None:
    dialog = tk.Toplevel()
    dialog.title("Save Preset")
    dialog.geometry("350x150+400+300")
    dialog.transient()
    dialog.grab_set()
    tk.Label(dialog, text="Preset Name:", font=styles.FONT_BODY).pack(pady=(15, 5))
    name_var = tk.StringVar()
    entry = tk.Entry(dialog, textvariable=name_var, font=styles.FONT_BODY, width=40)
    entry.pack(padx=20, pady=5)
    entry.focus_set()

    def _do_save() -> None:
        name = name_var.get().strip()
        if name:
            on_save(name)
            combo.set(name)
        dialog.destroy()

    entry.bind("<Return>", lambda e: _do_save())
    tk.Button(
        dialog,
        text="Save",
        command=_do_save,
        bg=styles.get_main(),
        fg="white",
        font=styles.FONT_BUTTON,
    ).pack(pady=10)


def _delete_preset_action(
    combo: ttk.Combobox,
    on_delete: "Callable[[str], None] | None",
) -> None:
    name = combo.get()
    if name and on_delete is not None:
        from tkinter import messagebox

        if messagebox.askyesno("Delete Preset", f'Delete preset "{name}"?'):
            on_delete(name)
            combo.set("")


# ── Stage panel builders ──────────────────────────────────────────────────────

#: The two normalisation strategies, labelled for the panel.  Keys are the
#: values ``NormaliseParams.mode`` stores; the labels are what a user picks.
_NORMALISE_MODE_LABELS: dict[str, str] = {
    "normalise": "Normalise (FFmpeg loudnorm)",
    "lossless": "Lossless (MP3 global gain)",
}
_NORMALISE_MODE_VALUES: dict[str, str] = {
    label: mode for mode, label in _NORMALISE_MODE_LABELS.items()
}

#: The two normalisation targets, labelled for the panel (F-E2).  Keys are the
#: values ``NormaliseParams.target_mode`` stores; the labels are what a user
#: picks.  ``mode`` above is a different question - how the gain is applied.
_NORMALISE_TARGET_LABELS: dict[str, str] = {
    "lufs": "Playlist loudness (LUFS)",
    "peak": "Peak (dBTP)",
}
_NORMALISE_TARGET_VALUES: dict[str, str] = {
    label: mode for mode, label in _NORMALISE_TARGET_LABELS.items()
}


def _build_declick_panel(
    parent: tk.Frame,
    config: StageConfig,
    embedded: bool = False,
    stage_vars: dict[str, Any] | None = None,
) -> None:
    p = config.declick_params
    run_mode: tk.StringVar | None = tk.StringVar(value="Live Update")

    if embedded:
        run_mode = None

    # The panel's widgets own these variables, so they are traced back into the
    # stage params — a copied value would leave the slider controlling nothing.
    sensitivity_var = tk.DoubleVar(value=p.sensitivity)
    width_var = tk.IntVar(value=p.max_width_ms)

    def _write_back(*_trace: Any) -> None:
        p.sensitivity = round(float(sensitivity_var.get()), 2)
        p.max_width_ms = int(width_var.get())

    sensitivity_var.trace_add("write", _write_back)
    width_var.trace_add("write", _write_back)

    _stage_panel(
        parent,
        "Pop & Click Remover",
        config,
        "declick",
        [],
        lambda body: declick_ui.build_config_panel(
            body,
            run_mode,
            sensitivity_var,
            width_var,
        ),
        stage_vars=stage_vars,
    )


def _optional_int(text: str) -> int | None:
    """Parse a millisecond entry; an empty or partial field reads as unset."""
    stripped = text.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def _build_trim_panel(
    parent: tk.Frame,
    config: StageConfig,
    embedded: bool = False,
    stage_vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Trim panel, returning the variables a caller can re-sync.

    The panel offers the stage's two modes: trimming detected silence (the
    behaviour it always had) or keeping an exact millisecond range (F-E3).
    """
    p = config.trim_params
    run_mode: tk.StringVar | None = tk.StringVar(value="Live Update")

    # Hide execution mode when embedded since Audio Refinery
    # always runs in Live Update mode
    if embedded:
        run_mode = None

    threshold_var = tk.IntVar(value=p.threshold)
    fade_var = tk.BooleanVar(value=p.apply_fade)
    fade_in_var = tk.IntVar(value=p.fade_in_ms)
    fade_out_var = tk.IntVar(value=p.fade_out_ms)

    def _write_back(*_trace: Any) -> None:
        p.threshold = int(threshold_var.get())
        p.apply_fade = bool(fade_var.get())
        p.fade_in_ms = int(fade_in_var.get())
        p.fade_out_ms = int(fade_out_var.get())

    for _var in (threshold_var, fade_var, fade_in_var, fade_out_var):
        _var.trace_add("write", _write_back)

    # Changed in 2.5.0: exact time-range trim (F-E3).  The mode and range fields
    # write back to the same stage params the run reads, and a driver launch
    # re-syncs these variables through this same trace (`_sync_trim_panel`).
    mode_var = tk.StringVar(value=p.mode)
    start_var = tk.StringVar(value="" if p.start_ms is None else str(p.start_ms))
    end_var = tk.StringVar(value="" if p.end_ms is None else str(p.end_ms))
    duration_var = tk.StringVar(
        value="" if p.duration_ms is None else str(p.duration_ms)
    )
    copy_var = tk.BooleanVar(value=p.copy_mode)

    def _write_range(*_trace: Any) -> None:
        p.mode = mode_var.get()
        p.start_ms = _optional_int(start_var.get())
        p.end_ms = _optional_int(end_var.get())
        p.duration_ms = _optional_int(duration_var.get())
        p.copy_mode = bool(copy_var.get())

    range_vars: tuple[tk.Variable, ...] = (
        mode_var,
        start_var,
        end_var,
        duration_var,
        copy_var,
    )
    for _range_var in range_vars:
        _range_var.trace_add("write", _write_range)

    def _extra(body: tk.Frame) -> None:
        # The shared silence controls first, then the Refinery's own exact-range
        # fields, so one panel holds one stage's whole surface.
        trim_ui.build_config_panel(
            body,
            run_mode,
            threshold_var,
            fade_var,
            fade_in_var,
            fade_out_var,
        )
        tk.Label(
            body,
            text="Trim by:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            anchor="w",
        ).pack(anchor="w", pady=(4, 0))
        mode_row = tk.Frame(body, bg=styles.BG_WHITE)
        mode_row.pack(fill="x")
        for value, label in (("silence", "Silence"), ("exact", "Exact range")):
            tk.Radiobutton(
                mode_row,
                text=label,
                variable=mode_var,
                value=value,
                font=styles.FONT_CAPTION,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                activebackground=styles.BG_WHITE,
                activeforeground=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                anchor="w",
            ).pack(side=tk.LEFT, padx=5)

        for label, var in (
            ("Start (ms):", start_var),
            ("End (ms):", end_var),
            ("Duration (ms):", duration_var),
        ):
            row = tk.Frame(body, bg=styles.BG_WHITE)
            row.pack(fill="x", pady=2)
            tk.Label(
                row,
                text=label,
                font=styles.FONT_CAPTION,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                width=14,
                anchor="w",
            ).pack(side=tk.LEFT, padx=5)
            ttk.Entry(row, textvariable=var, width=12, font=styles.FONT_CAPTION).pack(
                side=tk.LEFT
            )

        copy_row = tk.Frame(body, bg=styles.BG_WHITE)
        copy_row.pack(fill="x", pady=(4, 0))
        tk.Checkbutton(
            copy_row,
            text="Stream copy (frame-accurate, no re-encode)",
            variable=copy_var,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            anchor="w",
        ).pack(side=tk.LEFT, padx=5)
        tk.Label(
            body,
            text=(
                "Exact keeps the range you enter: start plus end, or start plus "
                "duration. A stream copy keeps the source's own frames, so the "
                "cut lands on a frame boundary and it cannot run beside the "
                "other stages."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=520,
            justify="left",
        ).pack(anchor="w", padx=5)

    _stage_panel(
        parent,
        "Silence Trimmer / Fader",
        config,
        "trim",
        [],
        _extra,
        stage_vars=stage_vars,
    )

    return {
        "mode": mode_var,
        "start": start_var,
        "end": end_var,
        "duration": duration_var,
        "copy": copy_var,
    }


def _build_noise_reduction_panel(
    parent: tk.Frame,
    config: StageConfig,
    embedded: bool = False,
    stage_vars: dict[str, Any] | None = None,
) -> None:
    """Build the Noise Reduction stage panel with hum + broadband controls."""
    p = config.noise_reduction_params

    def _extra(body: tk.Frame) -> None:
        # Hum removal sub-section
        hum_var = tk.BooleanVar(value=p.reduce_hum)

        def _set_hum() -> None:
            p.reduce_hum = bool(hum_var.get())

        tk.Checkbutton(
            body,
            text="Enable Hum Removal",
            variable=hum_var,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            command=_set_hum,
            activeforeground=styles.FG_MAIN,
        ).pack(anchor="w")

        freq_frame = tk.Frame(body, bg=styles.BG_WHITE)
        freq_frame.pack(fill="x", pady=3)
        tk.Label(
            freq_frame,
            text="Frequency:",
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=12,
            anchor="w",
        ).pack(side=tk.LEFT)
        freq_var = tk.IntVar(value=p.hum_frequency)

        def _set_frequency(*_: object) -> None:
            p.hum_frequency = int(freq_var.get())

        freq_var.trace_add("write", _set_frequency)

        for val in (50, 60):
            tk.Radiobutton(
                freq_frame,
                text=f"{val} Hz",
                variable=freq_var,
                value=val,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                activebackground=styles.BG_WHITE,
                activeforeground=styles.FG_MAIN,
            ).pack(side=tk.LEFT, padx=5)

        harmonics_var = tk.IntVar(value=p.hum_harmonics)
        ui_common.slider_row(body, "Harmonics (1-20)", harmonics_var, 1, 20, 1)
        harmonics_var.trace_add(
            "write", lambda *_: setattr(p, "hum_harmonics", harmonics_var.get())
        )

        quality_var = tk.DoubleVar(value=p.hum_quality)
        ui_common.slider_row(body, "Q Factor (1-100)", quality_var, 1.0, 100.0, 1.0)
        quality_var.trace_add(
            "write", lambda *_: setattr(p, "hum_quality", quality_var.get())
        )

        # Broadband noise sub-section
        tk.Label(body, text="", bg=styles.BG_WHITE).pack(pady=2)
        bb_var = tk.BooleanVar(value=p.reduce_broadband)

        def _set_broadband() -> None:
            p.reduce_broadband = bool(bb_var.get())

        tk.Checkbutton(
            body,
            text="Enable Broadband Noise Reduction",
            variable=bb_var,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            command=_set_broadband,
            activeforeground=styles.FG_MAIN,
        ).pack(anchor="w")

        start_var = tk.IntVar(value=p.noise_start_ms)
        ui_common.slider_row(body, "Noise Start (ms)", start_var, 0, 5000, 100)
        start_var.trace_add(
            "write", lambda *_: setattr(p, "noise_start_ms", start_var.get())
        )

        end_var = tk.IntVar(value=p.noise_end_ms)
        ui_common.slider_row(body, "Noise End (ms)", end_var, 100, 10000, 100)
        end_var.trace_add("write", lambda *_: setattr(p, "noise_end_ms", end_var.get()))

        gate_var = tk.DoubleVar(value=p.gate_threshold_db)
        ui_common.slider_row(body, "Gate Threshold (dB)", gate_var, 0.0, 20.0, 0.5)
        gate_var.trace_add(
            "write", lambda *_: setattr(p, "gate_threshold_db", gate_var.get())
        )

    _stage_panel(
        parent,
        "Noise Reduction",
        config,
        "reduce_noise",
        [],
        _extra,
        stage_vars=stage_vars,
    )


def _build_enhance_panel(
    parent: tk.Frame,
    config: StageConfig,
    state: dict[str, Any],
    stage_vars: dict[str, Any] | None = None,
) -> None:
    p = config.enhance_params
    preset_var = tk.StringVar(value=p.preset)

    def _extra(body: tk.Frame) -> None:
        # Preset selector
        row = tk.Frame(body, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=3)
        tk.Label(
            row,
            text="Preset:",
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
        ).pack(side=tk.LEFT)
        combo = ttk.Combobox(
            row,
            textvariable=preset_var,
            values=[preset_text(preset) for preset in PresetName],
            font=styles.FONT_BODY,
            state="readonly",
            width=12,
        )
        combo.pack(side=tk.LEFT, padx=(6, 0))

        def _mirror(values: dict[str, Any]) -> None:
            """Write the editor's values into the run config.

            Done here rather than per-widget because the controls live in the
            shared editor: the panel reports every change (widget or preset)
            with a full value set, which is exactly what ``StageConfig``
            needs — the pipeline runs on it, not on the widget variables.
            """
            for name, value in values.items():
                if hasattr(p, name):
                    setattr(p, name, value)

        # The same compact row + non-modal editor the standalone Audio
        # Enhancer shows. The stage body previously embedded all 19 controls
        # inline (745 px), which pushed the REFINE tab past the desktop height
        # as soon as Custom was selected — the defect this replaces.
        panel = enhancer_ui.CustomDspPanel(
            body, cast(EnhancementParams, p), preset_var, on_change=_mirror
        )
        state["dsp_panel"] = panel
        state["preset_var"] = preset_var
        state["enhance_preset_combo"] = combo
        state["dsp_row"] = panel.build_row(body)
        panel.sync_preset()
        panel.set_field_visible("output_gain_db", not config.normalise)

        def _on_preset_change(*_args: Any) -> None:
            selected = preset_var.get()
            p.preset = selected
            if selected == PresetName.CUSTOM.value:
                panel.sync_preset()
                return
            built_in = PRESETS.get(PresetName(selected)) if selected else None
            # A named preset supplies the base 13 fields; Sprint 1 effect
            # toggles are left as the user set them (D13).
            panel.apply_values(
                {} if built_in is None else enhancer_ui.preset_values(built_in)
            )

        preset_var.trace_add("write", _on_preset_change)
        # Only a real click opens the editor: a preset restored from settings
        # at build time must not pop a window.
        combo.bind(
            "<<ComboboxSelected>>",
            lambda _event: (
                panel.open() if preset_var.get() == PresetName.CUSTOM.value else None
            ),
        )
        _on_preset_change()

    _stage_panel(
        parent, "Audio Enhancer", config, "enhance", [], _extra, stage_vars=stage_vars
    )


def _build_normalise_panel(
    parent: tk.Frame,
    config: StageConfig,
    state: dict[str, Any],
    embedded: bool = False,
    stage_vars: dict[str, Any] | None = None,
) -> None:
    p = config.normalise_params
    # Hide execution mode when embedded since Audio Refinery
    # always runs in Live Update mode
    run_mode = None if embedded else tk.StringVar(value="Normalize")

    # Traced back into the stage params (U-04): the target, tolerance, ceiling,
    # LRA and strategy all reach the pipeline from here.
    target_var = tk.DoubleVar(value=p.target_lufs)
    tolerance_var = tk.DoubleVar(value=p.tolerance)
    peak_var = tk.DoubleVar(value=p.true_peak)
    lra_var = tk.DoubleVar(value=p.lra)
    mode_var = tk.StringVar(value=_NORMALISE_MODE_LABELS.get(p.mode, ""))
    target_mode_var = tk.StringVar(
        value=_NORMALISE_TARGET_LABELS.get(p.target_mode, "")
    )
    target_peak_var = tk.DoubleVar(value=p.target_peak_dbtp)
    # Declared here rather than in ``_extra`` because the target selector and
    # the album checkbox exclude each other (F-E2) and each has to clear the
    # other through the other's own write-back.
    album_var = tk.BooleanVar(value=p.album_mode)

    def _write_album(*_trace: Any) -> None:
        p.album_mode = bool(album_var.get())
        if p.album_mode and p.target_mode == "peak":
            target_mode_var.set(_NORMALISE_TARGET_LABELS["lufs"])

    album_var.trace_add("write", _write_album)

    def _write_back(*_trace: Any) -> None:
        p.target_lufs = float(target_var.get())
        p.tolerance = float(tolerance_var.get())
        p.true_peak = float(peak_var.get())
        p.lra = float(lra_var.get())
        mode = _NORMALISE_MODE_VALUES.get(mode_var.get())
        if mode is not None:
            p.mode = mode
        target_mode = _NORMALISE_TARGET_VALUES.get(target_mode_var.get())
        if target_mode is not None:
            p.target_mode = target_mode
        p.target_peak_dbtp = float(target_peak_var.get())
        if p.target_mode == "peak":
            album_var.set(False)

    for _var in (
        target_var,
        tolerance_var,
        peak_var,
        lra_var,
        mode_var,
        target_mode_var,
        target_peak_var,
    ):
        _var.trace_add("write", _write_back)

    def _on_check_change(enabled: bool) -> None:
        config.normalise = enabled
        cb = state.get("normalise_toggle_cb")
        if cb:
            cb()

    def _extra(body: tk.Frame) -> None:
        normalise_ui.build_config_panel(
            body,
            run_mode,
            target_var,
            tolerance_var,
            true_peak=peak_var,
            lra=lra_var,
        )
        # Changed in 2.6.0: the normalise target (F-E2).  Playlist loudness is
        # the LUFS target the panel already had; Peak targets the true peak with
        # one static gain, so the file's dynamics are left alone.
        target_row = tk.Frame(body, bg=styles.BG_WHITE)
        target_row.pack(fill="x", pady=(4, 0))
        tk.Label(
            target_row,
            text="Target:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            width=28,
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            target_row,
            textvariable=target_mode_var,
            values=list(_NORMALISE_TARGET_LABELS.values()),
            state="readonly",
            font=styles.FONT_CAPTION,
            width=30,
        ).pack(side=tk.LEFT, padx=6)
        peak_target_row = tk.Frame(body, bg=styles.BG_WHITE)
        peak_target_row.pack(fill="x", pady=(2, 0))
        tk.Label(
            peak_target_row,
            text="True peak target (dBTP):",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            width=28,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            peak_target_row,
            textvariable=target_peak_var,
            width=10,
            font=styles.FONT_CAPTION,
        ).pack(side=tk.LEFT, padx=6)
        tk.Label(
            body,
            text=(
                "Playlist loudness targets integrated loudness in LUFS. Peak "
                "targets the true peak in dBTP with one static gain, so the "
                "file's dynamics stay as they are; a gain that would pass full "
                "scale is limited rather than clipped. Peak mode and album "
                "loudness cannot be combined."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=520,
            justify="left",
        ).pack(anchor="w", padx=5)

        strategy_row = tk.Frame(body, bg=styles.BG_WHITE)
        strategy_row.pack(fill="x", pady=(4, 0))
        tk.Label(
            strategy_row,
            text="Strategy:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=28,
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            strategy_row,
            textvariable=mode_var,
            values=list(_NORMALISE_MODE_LABELS.values()),
            state="readonly",
            font=styles.FONT_CAPTION,
            width=30,
        ).pack(side=tk.LEFT, padx=6)
        tk.Label(
            body,
            text=(
                "Lossless rewrites an MP3's global gain and re-encodes nothing; "
                "other formats fall back to the loudnorm re-encode."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=520,
            justify="left",
        ).pack(anchor="w", padx=5)

        # Changed in 2.5.0: album mode (F-E1).  The checkbox writes the flag
        # back to the stage params the run reads; the plan itself is measured
        # when the run starts, so a Dry Run is the pass that reports the gain.
        # Changed in 2.6.0: its variable and trace now live at the top of the
        # panel, because peak mode and album mode exclude each other (F-E2).
        album_row = tk.Frame(body, bg=styles.BG_WHITE)
        album_row.pack(fill="x", pady=(6, 0))
        tk.Checkbutton(
            album_row,
            text="Album loudness (one gain for the whole folder)",
            variable=album_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            font=styles.FONT_CAPTION,
            anchor="w",
        ).pack(side=tk.LEFT, padx=5)
        tk.Label(
            body,
            text=(
                "Measures the folder as one album and moves every track by that "
                "single gain, so the album's relative levels survive. A track "
                "that would exceed the true-peak ceiling is limited on its own "
                "and named in the run log."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=520,
            justify="left",
        ).pack(anchor="w", padx=5)

    _stage_panel(
        parent,
        "Audio Normaliser",
        config,
        "normalise",
        [],
        _extra,
        on_check_change=_on_check_change,
        stage_vars=stage_vars,
    )


# ── Generic stage panel ───────────────────────────────────────────────────────


def _stage_panel(
    parent: tk.Frame,
    title: str,
    config: StageConfig,
    attr: str,  # 'declick' | 'trim' | 'enhance' | 'normalise'
    slider_rows: list[Any],
    extra_builder: Callable[..., Any] | None,
    on_check_change: Callable[..., Any] | None = None,
    stage_vars: dict[str, Any]
    | None = None,  # Store BooleanVar references for SELECT ALL
) -> None:
    """Build a collapsible labelled panel for one pipeline stage."""
    outer = tk.Frame(
        parent,
        bg=styles.BG_LIGHT,
        highlightbackground=styles.FG_SUB,
        highlightthickness=1,
    )
    outer.pack(fill="x", pady=4, padx=2)

    # Header row: checkbox + title + expand toggle
    header = tk.Frame(outer, bg=styles.BG_LIGHT)
    header.pack(fill="x", padx=8, pady=4)

    enabled_var = tk.BooleanVar(value=getattr(config, attr))

    # Store reference for SELECT ALL functionality
    if stage_vars is not None:
        stage_vars[attr] = enabled_var

    def _on_check() -> None:
        setattr(config, attr, enabled_var.get())
        if on_check_change:
            on_check_change(enabled_var.get())

    tk.Checkbutton(
        header,
        variable=enabled_var,
        command=_on_check,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
        activebackground=styles.BG_LIGHT,
        activeforeground=styles.FG_MAIN,
        selectcolor=styles.BG_LIGHT,
        disabledforeground=styles.FG_SUB,
    ).pack(side=tk.LEFT)

    tk.Label(
        header,
        text=title,
        font=styles.FONT_BODY,
        bg=styles.BG_LIGHT,
        fg=styles.FG_MAIN,
    ).pack(side=tk.LEFT, expand=True, fill="x")

    expand_var = tk.StringVar(value="▶  Settings")
    expanded = [False]

    body = tk.Frame(outer, bg=styles.BG_WHITE, padx=12, pady=8)

    # Build body contents
    for label, var, from_, to_, res in slider_rows:
        ui_common.slider_row(body, label, var, from_, to_, res)

    if extra_builder:
        extra_builder(body)

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


# ── Bottom buttons ────────────────────────────────────────────────────────
