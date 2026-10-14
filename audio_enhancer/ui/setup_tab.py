"""
ui/setup_tab.py
Setup tab for Audio Enhancer.

Changed in 1.0.1: fixed type annotation from tk.Event[ttk.Combobox] to
tk.Event for Python 3.11 compatibility (Event is not subscriptable in 3.11).

Matches the suite's established UI conventions:
  - tk.LabelFrame for configuration groups
  - ttk.Combobox (readonly) for enumerated choices
  - tk.Scale for numeric ranges (prevents invalid free-text entry)
  - Start button at the bottom, spanning full width
  - styles constants throughout (no hard-coded colours or fonts)
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, cast

from audio_suite_shared import styles, ui_common
from audio_suite_shared.dsp_models import PRESETS, EnhancementParams, PresetName
from audio_suite_shared.ui_common import BaseSetupFrame


def build(
    parent: tk.Frame,
    source_path: tk.StringVar,
    output_path: tk.StringVar,
    preset_name: tk.StringVar,
    params: EnhancementParams,
    on_browse_src: Callable[..., Any],
    on_browse_out: Callable[..., Any],
    on_start: Callable[..., Any],
    run_mode: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar | None = None,
    parallel_var: tk.BooleanVar | None = None,
    driver_locked: bool = False,
    preset_names: "list[str] | None" = None,
    on_save_preset: "Callable[[str], None] | None" = None,
    on_delete_preset: "Callable[[str], None] | None" = None,
    on_preset_selected: "Callable[[str], None] | None" = None,
) -> "tuple[tk.Button, Callable[..., Any] | None, dict[str, float]]":
    """
    Populate the Setup tab.

    Returns (start_button, refresh_preset_list_fn, param_values).

    The shared Run Controls panel (source bar, Mode, Auto Start/End, Clear
    Logs, Parallel) is rendered by BaseSetupFrame; the tool-specific Options
    section keeps only the output folder row plus the preset/DSP config.
    All user-controllable values use constrained widgets (Scale, Combobox)
    so that invalid values never reach the processing layer.
    """
    frame = _SetupFrame(
        parent,
        title="Audio Enhancer",
        start_text="BEGIN ENHANCEMENT",
        on_start=on_start,
        include_controls_panel=True,
        preset_names=preset_names,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
        pady=20,
        folder_path=source_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse_src,
        driver_locked=driver_locked,
        source_path=source_path,
        output_path=output_path,
        preset_name=preset_name,
        params=params,
        on_browse_src=on_browse_src,
        on_browse_out=on_browse_out,
    )
    refresh = frame.refresh_preset_list if frame.preset_combo is not None else None
    return cast(tk.Button, frame.start_btn), refresh, frame._param_values


class _SetupFrame(BaseSetupFrame):
    """Audio Enhancer Setup tab skeleton on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        *,
        source_path: tk.StringVar,
        output_path: tk.StringVar,
        preset_name: tk.StringVar,
        params: EnhancementParams,
        on_browse_src: Callable[..., Any],
        on_browse_out: Callable[..., Any],
        **kwargs: Any,
    ) -> None:
        # Tool-specific option state must be bound before super().__init__,
        # which calls _layout() -> _build_options() during construction.
        self._source_path = source_path
        self._output_path = output_path
        self._preset_name = preset_name
        self._params = params
        self._on_browse_src = on_browse_src
        self._on_browse_out = on_browse_out
        self._param_values: dict[str, float] = {}
        super().__init__(parent, **kwargs)

    def _build_options(self) -> None:
        # ── Output path ───────────────────────────────────────────────────────
        # The shared Run Controls panel already renders the Source bar.
        ui_common.path_row(
            self,
            "Output folder (leave blank for auto):",
            self._output_path,
            self._on_browse_out,
        )

        # ── Preset + DSP configuration ────────────────────────────────────────
        cfg = self.add_config_group("Configuration")

        # Preset selector
        tk.Label(
            cfg,
            text="Enhancement Preset:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(fill="x", pady=(0, 3))
        preset_row = tk.Frame(cfg, bg=styles.BG_WHITE)
        preset_row.pack(fill="x", pady=3)

        preset_menu = ttk.Combobox(
            preset_row,
            textvariable=self._preset_name,
            font=styles.FONT_BODY,
            state="readonly",
            width=14,
        )
        preset_menu["values"] = [p.value for p in PresetName]
        preset_menu.pack(side=tk.LEFT)

        # Custom DSP LabelFrame (shown/hidden via preset selection)
        dsp = tk.LabelFrame(
            cfg,
            text=" Custom DSP Parameters ",
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            font=styles.FONT_CAPTION,
            padx=10,
            pady=8,
        )

        # Build all DSP sliders into the custom frame
        _dsp_sliders, _param_values = build_dsp_sliders(
            cast("tk.Frame", dsp), self._params
        )
        self._param_values = _param_values

        def _on_preset_change(
            _event: tk.Event | None = None,
        ) -> None:
            selected = PresetName(self._preset_name.get())
            if selected == PresetName.CUSTOM:
                dsp.pack(fill="x", pady=(6, 0))
            else:
                dsp.pack_forget()
                # Apply preset values to the shared params object
                p = PRESETS[selected]
                for field_name in p.__dataclass_fields__:
                    var = _dsp_sliders.get(field_name)
                    if var is not None:
                        var.set(getattr(p, field_name))

        preset_menu.bind("<<ComboboxSelected>>", _on_preset_change)
        _on_preset_change()  # apply initial state


# ──────────────────────────────────────────────────────────────────────────────
# Public builders for reuse (e.g. in Audio Refinery)
# ──────────────────────────────────────────────────────────────────────────────


def build_dsp_sliders(
    parent: tk.Frame,
    params: EnhancementParams,
) -> tuple[dict[str, tk.DoubleVar], dict[str, float]]:
    """
    Build Scale widgets for every DSP parameter.

    Returns (slider_vars, param_values) where *slider_vars* maps field names
    to ``tk.DoubleVar`` (for programmatic preset updates) and *param_values*
    is a mutable dict that stays in sync with slider movements so callers can
    construct a new ``EnhancementParams`` at any time via
    ``EnhancementParams(**param_values)``.
    """
    slider_specs: list[tuple[str, str, float, float, float]] = [
        # (field_name,                          label,              from,   to,    res)
        ("noise_gate_threshold_db", "Noise Gate Threshold (dB)", -90.0, -40.0, 1.0),
        ("compressor_threshold_db", "Compressor Threshold (dB)", -40.0, -6.0, 0.5),
        ("compressor_ratio", "Compressor Ratio", 1.0, 10.0, 0.5),
        ("compressor_attack_ms", "Compressor Attack (ms)", 1.0, 50.0, 1.0),
        ("compressor_release_ms", "Compressor Release (ms)", 20.0, 500.0, 10.0),
        ("low_shelf_gain_db", "Low Shelf Gain (dB)", -6.0, 12.0, 0.5),
        ("low_shelf_freq_hz", "Low Shelf Freq (Hz)", 40.0, 400.0, 10.0),
        ("presence_gain_db", "Presence Gain (dB)", -6.0, 12.0, 0.5),
        ("presence_freq_hz", "Presence Freq (Hz)", 500.0, 8000.0, 100.0),
        ("high_shelf_gain_db", "High Shelf Gain (dB)", -6.0, 12.0, 0.5),
        ("high_shelf_freq_hz", "High Shelf Freq (Hz)", 2000.0, 16000.0, 500.0),
        ("output_gain_db", "Output Gain (dB)", -6.0, 18.0, 0.5),
        ("limiter_threshold_db", "Limiter Threshold (dB)", -12.0, -0.1, 0.1),
    ]

    vars_: dict[str, tk.DoubleVar] = {}
    param_values: dict[str, float] = {}

    for field_name, label, from_, to_, resolution in slider_specs:
        initial = getattr(params, field_name)
        var = tk.DoubleVar(value=initial)
        vars_[field_name] = var
        param_values[field_name] = initial

        # Keep param_values dict in sync when slider moves
        def _make_trace(fn: str, v: tk.DoubleVar) -> Callable[..., None]:
            def _cb(*_: object) -> None:
                param_values[fn] = v.get()

            return _cb

        var.trace_add("write", _make_trace(field_name, var))

        ui_common.slider_row(parent, label, var, from_, to_, resolution)

    return vars_, param_values
