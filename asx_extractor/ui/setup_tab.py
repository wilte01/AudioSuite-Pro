"""setup_tab.py — Setup tab for ASX Playlist Extractor."""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame

_MODES: tuple[str, str] = (
    "Dry Run (Simulated)",
    "Execute Extraction (Permanent)",
)


def build(
    parent: tk.Frame,
    current_folder: tk.StringVar,
    asx_action_mode: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    preset_names: list[str] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
    driver_locked: bool = False,
) -> dict[str, Any]:
    """Populate the Setup tab.

    Args:
        parent: Notebook page frame to populate.
        current_folder: Variable holding the target directory path.
        asx_action_mode: Variable holding the extraction mode label.
        auto_start_var: Mirrors the driver's Auto Start (display only).
        auto_end_var: Mirrors the driver's Auto End.
        clear_logs_var: Mirrors the driver's Clear Logs (display only).
        parallel_var: Mirrors the driver's Parallel option (display only).
        on_browse: Callback for the Browse button.
        on_start: Callback for the start button.
        preset_names: Saved preset names to show initially.
        on_save_preset: Optional callback receiving a new preset name.
        on_delete_preset: Optional callback receiving a preset name.
        on_preset_selected: Optional callback fired on preset selection.
        driver_locked: True after a Master Driver launch — locks the
            Run Controls panel to the inherited values.

    Returns:
        Dict with ``start_btn``, ``refresh_preset_list``, ``preset_combo``
        and ``controls_panel``.
    """
    frame = _SetupFrame(
        parent,
        title="ASX Playlist Extractor",
        start_text="START EXTRACTION",
        on_start=on_start,
        folder_path=current_folder,
        run_mode=asx_action_mode,
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
        padx=40,
        title_font=styles.FONT_TITLE_L,
        title_pady=(0, 25),
        start_side=None,
        modes=_MODES,
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """ASX Playlist Extractor Setup tab built on the shared BaseSetupFrame."""
