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

Changed in 1.1.0: added _SLIDER_SPECS/NUMERIC_DSP_FIELDS and
build_effect_controls; the Custom DSP panel now also renders the
Sprint 1 effect toggles.
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
) -> "tuple[tk.Button, Callable[..., Any] | None, dict[str, Any]]":
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
        self._param_values: dict[str, Any] = {}
        self._effect_vars: dict[str, tk.Variable] = {}
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

        # Sprint 1 effects (D12/D17) — share the param_values dict so the
        # worker can reconstruct a complete EnhancementParams.
        self._effect_vars = build_effect_controls(
            cast("tk.Frame", dsp), self._params, self._param_values
        )

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


#: Numeric DSP fields rendered as ``tk.Scale`` widgets by
#: :func:`build_dsp_sliders`, keyed to ``(label, from, to, resolution)``.
#: This is the single source of truth for the slider set — the boolean effect
#: toggles (``reverse``/``karaoke``/``phaser``/``flanger``/``chorus``) are
#: rendered separately by :func:`build_effect_controls`.
_SLIDER_SPECS: dict[str, tuple[str, float, float, float]] = {
    "noise_gate_threshold_db": ("Noise Gate Threshold (dB)", -90.0, -40.0, 1.0),
    "compressor_threshold_db": ("Compressor Threshold (dB)", -40.0, -6.0, 0.5),
    "compressor_ratio": ("Compressor Ratio", 1.0, 10.0, 0.5),
    "compressor_attack_ms": ("Compressor Attack (ms)", 1.0, 50.0, 1.0),
    "compressor_release_ms": ("Compressor Release (ms)", 20.0, 500.0, 10.0),
    "low_shelf_gain_db": ("Low Shelf Gain (dB)", -6.0, 12.0, 0.5),
    "low_shelf_freq_hz": ("Low Shelf Freq (Hz)", 40.0, 400.0, 10.0),
    "presence_gain_db": ("Presence Gain (dB)", -6.0, 12.0, 0.5),
    "presence_freq_hz": ("Presence Freq (Hz)", 500.0, 8000.0, 100.0),
    "high_shelf_gain_db": ("High Shelf Gain (dB)", -6.0, 12.0, 0.5),
    "high_shelf_freq_hz": ("High Shelf Freq (Hz)", 2000.0, 16000.0, 500.0),
    "output_gain_db": ("Output Gain (dB)", -6.0, 18.0, 0.5),
    "limiter_threshold_db": ("Limiter Threshold (dB)", -12.0, -0.1, 0.1),
}

#: Field names (in display order) that :func:`build_dsp_sliders` renders as
#: numeric Scale widgets.
NUMERIC_DSP_FIELDS: tuple[str, ...] = tuple(_SLIDER_SPECS)

#: Boolean effect toggles rendered as ``tk.Checkbutton`` widgets by
#: :func:`build_effect_controls`, paired with their display label.
_EFFECT_TOGGLES: tuple[tuple[str, str], ...] = (
    ("reverse", "Reverse audio"),
    ("karaoke", "Karaoke (centre-vocal removal)"),
    ("phaser", "Phaser"),
    ("flanger", "Flanger"),
    ("chorus", "Chorus"),
)


def build_dsp_sliders(
    parent: tk.Frame,
    params: EnhancementParams,
) -> tuple[dict[str, tk.DoubleVar], dict[str, Any]]:
    """
    Build Scale widgets for every numeric DSP parameter.

    Returns (slider_vars, param_values) where *slider_vars* maps field names
    to ``tk.DoubleVar`` (for programmatic preset updates) and *param_values*
    is a mutable dict that stays in sync with slider movements so callers can
    construct a new ``EnhancementParams`` at any time via
    ``EnhancementParams(**param_values)``. Callers that also render effect
    controls should pass the same *param_values* dict to
    :func:`build_effect_controls` so a single ``EnhancementParams`` can be
    constructed from all 19 fields.
    """
    vars_: dict[str, tk.DoubleVar] = {}
    param_values: dict[str, Any] = {}

    for field_name, (label, from_, to_, resolution) in _SLIDER_SPECS.items():
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


def build_effect_controls(
    parent: tk.Frame,
    params: EnhancementParams,
    param_values: dict[str, Any],
) -> dict[str, tk.Variable]:
    """
    Build the Sprint 1 effect controls (D12/D17) inside a labelled sub-frame.

    Renders five boolean toggles (reverse, karaoke, phaser, flanger, chorus)
    plus the numeric ``karaoke_strength`` (0.0-1.0). Every widget writes into
    *param_values* (the same dict returned by :func:`build_dsp_sliders`) so a
    complete ``EnhancementParams(**param_values)`` can be constructed.

    Args:
        parent: Container frame to pack the effect sub-frame into.
        params: Current params — supplies each control's initial value.
        param_values: Mutable dict shared with :func:`build_dsp_sliders`;
            extended in place with the six effect field values.

    Returns:
        Mapping of effect field name -> Tk variable (BooleanVar for the
        toggles, DoubleVar for karaoke_strength).
    """
    frame = tk.LabelFrame(
        parent,
        text=" Effects ",
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        font=styles.FONT_CAPTION,
        padx=10,
        pady=8,
    )
    frame.pack(fill="x", pady=(6, 0))

    effect_vars: dict[str, tk.Variable] = {}

    for field_name, label in _EFFECT_TOGGLES:
        initial = bool(getattr(params, field_name))
        bool_var = tk.BooleanVar(value=initial)
        param_values[field_name] = initial

        def _make_bool_trace(fn: str, v: tk.BooleanVar) -> Callable[..., None]:
            def _cb(*_: object) -> None:
                param_values[fn] = bool(v.get())

            return _cb

        bool_var.trace_add("write", _make_bool_trace(field_name, bool_var))
        tk.Checkbutton(
            frame,
            text=label,
            variable=bool_var,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            anchor="w",
        ).pack(fill="x", anchor="w")
        effect_vars[field_name] = bool_var

    strength = float(getattr(params, "karaoke_strength"))
    strength_var = tk.DoubleVar(value=strength)
    param_values["karaoke_strength"] = strength

    def _strength_trace(*_: object) -> None:
        param_values["karaoke_strength"] = strength_var.get()

    strength_var.trace_add("write", _strength_trace)
    ui_common.slider_row(frame, "Karaoke Strength", strength_var, 0.0, 1.0, 0.05)
    effect_vars["karaoke_strength"] = strength_var

    return effect_vars
