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
from audio_suite_shared.dsp_models import PRESETS, EnhancementParams, PresetName
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
    _build_trim_panel(stages_frame, config, embedded, stage_vars)
    _build_noise_reduction_panel(stages_frame, config, embedded, stage_vars)
    _build_enhance_panel(stages_frame, config, _state, stage_vars)
    _build_normalise_panel(stages_frame, config, _state, embedded, stage_vars)

    # Store stage_vars in the main state for access by Master Driver
    _state["stage_vars"] = stage_vars

    # Wire up the Output Gain visibility toggle after both panels exist
    def _update_output_gain_visibility(*_args: Any) -> None:
        row = _state.get("output_gain_row")
        if row is None:
            return
        if config.normalise:
            row.pack_forget()
        else:
            row.pack(fill="x", pady=1, before=_state.get("output_gain_anchor"))

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

    _stage_panel(
        parent,
        "Pop & Click Remover",
        config,
        "declick",
        [],
        lambda body: declick_ui.build_config_panel(
            body,
            run_mode,
            tk.DoubleVar(value=p.sensitivity),
            tk.IntVar(value=p.max_width_ms),
        ),
        stage_vars=stage_vars,
    )


def _build_trim_panel(
    parent: tk.Frame,
    config: StageConfig,
    embedded: bool = False,
    stage_vars: dict[str, Any] | None = None,
) -> None:
    p = config.trim_params
    run_mode: tk.StringVar | None = tk.StringVar(value="Live Update")

    # Hide execution mode when embedded since Audio Refinery
    # always runs in Live Update mode
    if embedded:
        run_mode = None

    _stage_panel(
        parent,
        "Silence Trimmer / Fader",
        config,
        "trim",
        [],
        lambda body: trim_ui.build_config_panel(
            body,
            run_mode,
            tk.IntVar(value=p.threshold),
            tk.BooleanVar(value=p.apply_fade),
            tk.IntVar(value=p.fade_in_ms),
            tk.IntVar(value=p.fade_out_ms),
        ),
        stage_vars=stage_vars,
    )


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
        ttk.Combobox(
            row,
            textvariable=preset_var,
            values=["Mild", "Moderate", "Aggressive", "Custom"],
            font=styles.FONT_BODY,
            state="readonly",
            width=12,
        ).pack(side=tk.LEFT, padx=(6, 0))

        dsp_frame = tk.Frame(body, bg=styles.BG_WHITE)
        state["dsp_frame"] = dsp_frame

        enhancer_ui.build_dsp_sliders(dsp_frame, cast(EnhancementParams, p))

        # Capture the output gain row for visibility toggling
        # This is a bit tricky since build_dsp_sliders packs them directly.
        # We'll look for the row that contains "Output Gain"
        for child in dsp_frame.winfo_children():
            for grand in child.winfo_children():
                if (
                    hasattr(grand, "cget")
                    and isinstance(grand, tk.Label)
                    and "Output Gain" in str(grand.cget("text"))
                ):
                    state["output_gain_row"] = child
                    break

        og_anchor = tk.Frame(dsp_frame, bg=styles.BG_WHITE, height=1)
        og_anchor.pack(fill="x")
        state["output_gain_anchor"] = og_anchor

        def _on_preset_change(*_args: Any) -> None:
            selected = preset_var.get()
            p.preset = selected
            if selected != "Custom":
                preset_enum = PresetName(selected)
                vals = PRESETS[preset_enum]
                for field in vals.__dataclass_fields__:
                    setattr(p, field, getattr(vals, field))
                # Trigger a refresh of the sliders (they are bound to the vars
                # created in build_dsp_sliders)
                # However, enhancer_ui.build_dsp_sliders creates its own internal vars.
                # We need a way to update those vars.
                # For now, we'll re-build the panel or just accept the data syncs.
                if state.get("dsp_frame"):
                    state["dsp_frame"].pack_forget()
            else:
                if state.get("dsp_frame"):
                    state["dsp_frame"].pack(fill="x", pady=(4, 0))

        preset_var.trace_add("write", _on_preset_change)
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

    def _on_check_change(enabled: bool) -> None:
        config.normalise = enabled
        cb = state.get("normalise_toggle_cb")
        if cb:
            cb()

    _stage_panel(
        parent,
        "Audio Normaliser",
        config,
        "normalise",
        [],
        lambda body: normalise_ui.build_config_panel(
            body,
            run_mode,
            tk.DoubleVar(value=p.target_lufs),
            tk.DoubleVar(value=p.tolerance),
        ),
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
        activebackground=styles.BG_LIGHT,
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
