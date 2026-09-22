"""
ui/refinery_tab.py
Refinery tab for the Master Driver.

Embeds the actual audio_refinery setup UI by calling
audio_refinery.ui.setup_tab.build() with embedded=True (suppresses the
title/subtitle). The REFINE tab shows a single Run Controls strip: the
shared DriverControlsPanel, into which the SELECT ALL checkbox is merged
in the driver's usual left-hand position. Driver-owned options (Auto
Start / Auto End / Clear Logs) are re-enabled and rebound to the driver's
state vars so the strip behaves like the ENRICH tab's shared control
strip. The output folder picker is injected between the path rows and
the stage panels via the after_paths callback.

Settings are shared with the standalone app via refinery_settings.json.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import filedialog, messagebox
from typing import TYPE_CHECKING, Any, Callable

from audio_refinery.core.models import StageConfig

if TYPE_CHECKING:
    from master_driver.state.app_state import AppState
from audio_refinery.ui import setup_tab as _setup_tab
from audio_refinery.utils.settings import load as _load_settings
from audio_refinery.utils.settings import save as _save_settings
from audio_suite_shared.security.input_validator import InputValidator

_REFINERY_STAGES = ("declick", "trim", "reduce_noise", "enhance", "normalise")


def build(
    parent: tk.Frame,
    state: "AppState",
    on_run: Callable[[], None],
    on_open_refinery: Callable[[], None],
) -> tuple[tk.Button, StageConfig, dict[str, Any]]:
    """
    Build the Refinery tab into parent.
    Returns (launch_button, stage_config, setup_state).
    """
    config = _load_settings()

    def _browse_src() -> None:
        path = filedialog.askdirectory(title="Select source folder")
        if path and InputValidator.validate_directory_path(path):
            state.refinery_source.set(path)
        elif path:
            messagebox.showwarning(
                "Invalid Path", "Selected folder path is invalid or potentially unsafe."
            )

    def _browse_out() -> None:
        path = filedialog.askdirectory(title="Select output folder")
        if path and InputValidator.validate_directory_path(path):
            state.refinery_output.set(path)
        elif path:
            messagebox.showwarning(
                "Invalid Path", "Selected folder path is invalid or potentially unsafe."
            )

    def _on_reset() -> None:
        from pathlib import Path

        from audio_refinery.core.registry import CompletionRegistry

        src = state.refinery_source.get().strip()
        if not src:
            messagebox.showinfo("Reset Progress", "No source folder selected.")
            return
        confirmed = messagebox.askyesno(
            "Reset Progress",
            f"Clear completion record for:\n\n{src}\n\n"
            f"All files will be reprocessed on the next run.\n\nContinue?",
            icon="warning",
        )
        if confirmed:
            CompletionRegistry(Path(src)).reset()

    def _inject_output_field(frame: tk.Frame) -> None:
        """Add the output folder picker after the source path row."""
        from audio_suite_shared import styles, ui_common

        output_frame = tk.Frame(frame, bg=styles.BG_WHITE, padx=24, pady=16)
        output_frame.pack(fill="x", pady=(10, 0))

        def _browse_output() -> None:
            folder = filedialog.askdirectory(title="Select Output Folder")
            if folder and InputValidator.validate_directory_path(folder):
                state.refinery_output.set(folder)

        ui_common.path_row(
            output_frame,
            "Output folder (blank = in-place):",
            state.refinery_output,
            _browse_output,
        )

    def _after_stages(frame: tk.Frame) -> None:
        """No additional widgets needed after stages."""

    # Build setup first to get setup_state
    setup_state = _setup_tab.build(
        parent=parent,
        source_path=state.refinery_source,
        output_path=None,  # Don't add output folder here
        config=config,
        on_browse_src=_browse_src,
        on_browse_out=_browse_out,
        on_start=on_run,
        on_reset=_on_reset,
        embedded=True,
        after_paths=_inject_output_field,
        after_stages=_after_stages,
        mode_var=state.global_mode,
    )

    _inject_select_all(setup_state, state, config)
    _apply_startup_select_state(setup_state, config, state.refinery_select_all_var)
    _activate_driver_run_controls(setup_state, state)

    launch_btn = setup_state["start_btn"]
    launch_btn.config(text="LAUNCH REFINERY")

    return launch_btn, config, setup_state


def _inject_select_all(
    setup_state: dict[str, Any], state: "AppState", config: StageConfig
) -> None:
    """Merge the SELECT ALL checkbox into the driver's Run Controls strip.

    Guard rails:
      * Missing controls panel/strip is a no-op so other tools are unaffected.
      * Idempotent — a repeat call never adds a duplicate checkbox.
      * The toggle only writes a stage var whose value actually differs, so
        a repeat click cannot re-trigger dependent state in an update loop.
      * ``config`` (the run source-of-truth read by ``arg_builder``) is
        updated in lockstep with each stage var so the UI and the actual
        pipeline stay consistent.
    """
    from audio_suite_shared import styles

    controls_panel = setup_state.get("controls_panel")
    if controls_panel is None:
        return
    strip = getattr(controls_panel, "control_strip", None)
    if (
        strip is None
        or getattr(controls_panel, "refine_select_all_cb", None) is not None
    ):
        return

    select_var = state.refinery_select_all_var

    def _toggle_all() -> None:
        target = select_var.get()
        stage_vars = setup_state.get("stage_vars", {})
        for stage_name in _REFINERY_STAGES:
            var = stage_vars.get(stage_name)
            if var is not None and var.get() != target:
                var.set(target)
            setattr(config, stage_name, target)

    # Make room at the front of the strip so SELECT ALL leads, matching the
    # Master Driver's shared control-strip ordering.
    for child in strip.winfo_children():
        info = child.grid_info()
        if not info:
            continue
        try:
            child.grid_configure(column=int(info["column"]) + 1)
        except (tk.TclError, ValueError):
            continue

    panel_bg = controls_panel.cget("bg")
    select_all_cb = tk.Checkbutton(
        strip,
        text="SELECT ALL",
        variable=select_var,
        command=_toggle_all,
        font=styles.FONT_BODY_B,
        bg=panel_bg,
        fg=styles.FG_MAIN,
        activeforeground=styles.FG_MAIN,
        activebackground=panel_bg,
        selectcolor=panel_bg,
    )
    select_all_cb.grid(row=0, column=0, sticky="w", padx=(0, 20))
    controls_panel.refine_select_all_cb = select_all_cb
    controls_panel.refine_toggle_all = _toggle_all


def _apply_startup_select_state(
    setup_state: dict[str, Any], config: StageConfig, select_var: tk.BooleanVar
) -> None:
    """Force the five stage cards to match the SELECT ALL state at startup.

    The stage checkboxes otherwise inherit their value from the persisted
    ``refinery_settings.json`` (config), which can leave them checked while
    the driver's SELECT ALL starts unchecked. Starting defensive keeps the
    UI and the actual run source-of-truth (``config`` / ``arg_builder``)
    consistent: both are set to the unchecked default together. ``BooleanVar
    .set()`` does not fire the checkbox's ``command``, so the matching
    ``config`` attribute must be updated here explicitly.
    """
    target = select_var.get()
    stage_vars = setup_state.get("stage_vars", {})
    for stage_name in _REFINERY_STAGES:
        var = stage_vars.get(stage_name)
        if var is not None and var.get() != target:
            var.set(target)
        setattr(config, stage_name, target)


def _activate_driver_run_controls(
    setup_state: dict[str, Any], state: "AppState"
) -> None:
    """Enable the driver-owned options on the embedded Run Controls strip.

    The embedded ``DriverControlsPanel`` is built for child tools launched
    from the driver, so its Auto Start / Clear Logs / Parallel checkboxes
    start greyed out ("driver-owned" inert states). Inside the Master Driver
    the driver is the host, so these must be clickable and bound to the
    driver's persistent variables — matching the shared strip on the ENRICH
    tab. The rebind matters, not just the state: ``launch_refinery`` and
    ``arg_builder.build_refinery_args`` read the state vars, so an unbound
    checkbox would toggle a detached BooleanVar that never affects the run.

    Guard rails:
      * A missing controls panel is a no-op so other tools are unaffected.
      * Idempotent — a repeat call only re-asserts the same binding.
      * Parallel stays inert: the refinery runner path never exercises it.
    """
    controls_panel = setup_state.get("controls_panel")
    if controls_panel is None:
        return

    bindings: list[tuple[str, tk.BooleanVar]] = [
        ("auto_start_btn", state.refinery_auto_start),
        ("auto_end_btn", state.refinery_auto_end),
        ("clear_logs_btn", state.clear_logs_var),
    ]
    for attr, var in bindings:
        btn = getattr(controls_panel, attr, None)
        if not isinstance(btn, tk.Checkbutton):
            continue
        btn.config(variable=var, state="normal")


def save_settings(config: StageConfig) -> None:
    """Persist current stage config — called by app.py before launching."""
    _save_settings(config)
