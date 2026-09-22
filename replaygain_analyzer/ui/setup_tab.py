"""
setup_tab.py
Setup tab for ReplayGain Analyzer.

Builds the shared Run Controls panel (mirroring the Master Driver),
LUFS target picker, preset management, and the primary Start button.
No business logic — purely view.
"""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame, discrete_slider_row
from audio_suite_shared.ui_driver_controls import (
    DriverControlsPanel as DriverControlsPanel,
)

_LUFS_VALUES: list[float] = [-12.0, -14.0, -16.0, -18.0, -23.0]


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    target_lufs: tk.StringVar,
    run_mode: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    apply_lossless_gain_var: tk.BooleanVar | None = None,
    driver_locked: bool = False,
    presets: list[str] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Populate the Setup tab widgets.

    Args:
        parent:            Container frame provided by the notebook.
        folder_path:       Tk variable bound to the directory entry field.
        target_lufs:       Tk variable bound to the LUFS slider.
        run_mode:          Tk variable bound to the mode combobox.
        auto_start_var:    Tk variable bound to the Auto Start checkbox.
        auto_end_var:      Tk variable bound to the Auto End checkbox.
        clear_logs_var:    Tk variable mirroring the driver's Clear Logs
                           state (checkbox stays inert).
        parallel_var:      Tk variable mirroring the driver's Parallel
                           state (checkbox stays inert).
        on_browse:         Callback invoked when Browse button is clicked.
        on_start:          Callback invoked when Start button is clicked.
        apply_lossless_gain_var: Optional Tk variable bound to the "apply
                           gain losslessly" toggle shown under the LUFS target.
        driver_locked:     True when launched via the Master Driver; locks
                           the Run Controls panel to inherited values.
        presets:           List of saved preset names.
        on_preset_selected: Callback when a preset is chosen from the combo.
        on_save_preset:    Callback to save the current settings as a named preset.
        on_delete_preset:  Callback to delete a named preset.

    Returns:
        Dict with keys "start_btn", "preset_combo", "refresh_preset_list",
        "controls_panel".
    """
    frame = _SetupFrame(
        parent,
        title="ReplayGain Analyzer & Tagger",
        start_text="BEGIN REPLAYGAIN ANALYSIS",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        browse_text="Browse",
        driver_locked=driver_locked,
        preset_names=presets,
        preset_row_always=True,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
        target_lufs=target_lufs,
        apply_lossless_gain_var=apply_lossless_gain_var,
    )
    frame.refresh_preset_list(presets)
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """ReplayGain Analyzer Setup tab built on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        target_lufs: tk.StringVar,
        apply_lossless_gain_var: tk.BooleanVar | None = None,
        **kwargs: Any,
    ) -> None:
        self._target_lufs = target_lufs
        self._apply_lossless_gain_var = apply_lossless_gain_var
        super().__init__(parent, **kwargs)

    def refresh_preset_list(self, names: list[str] | None = None) -> None:
        """Reload the preset combobox, selecting the first entry if any."""
        values = names if names is not None else (self._preset_names or [])
        combo = self.preset_combo
        if combo is None:
            return
        combo["values"] = values
        combo.set(values[0] if values else "")

    def _build_options(self) -> None:
        # ── Target LUFS ───────────────────────────────────────────────────────
        tk.Label(
            self,
            text="Target LUFS Level:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(15, 0))
        discrete_slider_row(
            self,
            label="",
            var=self._target_lufs,
            values=_LUFS_VALUES,
        )
        tk.Label(
            self,
            text="(-23.0 LUFS = broadcast standard, -14.0 LUFS = streaming loudness)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

        if self._apply_lossless_gain_var is not None:
            tk.Checkbutton(
                self,
                text="Apply track gain losslessly to MP3 files (MP3Gain-style)",
                font=styles.FONT_BODY,
                fg=styles.FG_MAIN,
                bg=styles.BG_WHITE,
                variable=self._apply_lossless_gain_var,
            ).pack(anchor="w", pady=(10, 0))
