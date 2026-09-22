"""setup_tab.py — Setup tab for Genre Sync."""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame
from audio_suite_shared.ui_driver_controls import (
    DriverControlsPanel as DriverControlsPanel,
)


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    driver_locked: bool = False,
    preset_names: list[str] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Populate the Setup tab widgets.

    Args:
        parent:            Container frame provided by the notebook.
        folder_path:       Tk variable bound to the directory entry field.
        run_mode:          Tk variable bound to the mode combobox.
        auto_start_var:    Tk variable bound to the Auto Start checkbox.
        auto_end_var:      Tk variable bound to the Auto End checkbox.
        clear_logs_var:    Tk variable mirroring the driver's Clear Logs
                           state (checkbox stays inert).
        parallel_var:      Tk variable mirroring the driver's Parallel
                           state (checkbox stays inert).
        on_browse:         Callback invoked when Browse button is clicked.
        on_start:          Callback invoked when Start button is clicked.
        driver_locked:     True when launched via the Master Driver; locks
                           the Run Controls panel to inherited values.
        preset_names:      List of saved preset names.
        on_save_preset:    Callback to save the current settings as a named preset.
        on_delete_preset:  Callback to delete a named preset.
        on_preset_selected: Callback when a preset is chosen from the combo.

    Returns:
        Dict with keys "start_btn", "preset_combo", "refresh_preset_list",
        "controls_panel".
    """
    frame = _SetupFrame(
        parent,
        title="Genre Sync",
        start_text="BEGIN GENRE UPDATE",
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
        preset_row_always=True,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """Genre Sync Setup tab built on the shared BaseSetupFrame."""

    def _build_options(self) -> None:
        # Description / rules
        desc = (
            "This tool sets the Genre (TCON) field based on custom genre fields.\n\n"
            "Priority Rules:\n"
            "1. TITLE GENRE (always used if present)\n"
            "2. If Album Artist = 'Various Artists':\n"
            "   → Use ARTIST GENRE, or fallback to ALBUM GENRE\n"
            "3. If Album Artist ≠ 'Various Artists':\n"
            "   → Use ALBUM GENRE, or fallback to ALBUM ARTIST GENRE"
        )
        tk.Label(
            self,
            text=desc,
            bg=styles.BG_WHITE,
            justify=tk.LEFT,
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
        ).pack(pady=(0, 20), anchor="w")
