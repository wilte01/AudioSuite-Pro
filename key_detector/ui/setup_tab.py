"""
setup_tab.py - Setup tab for Key Detector & Tagger.
"""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared.ui_common import AnalysisSetupFrame


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
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
    preset_names: list[str] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """Populate the Setup tab.

    Returns:
        Dict with keys: start_btn, refresh_preset_list, preset_combo,
        controls_panel.
    """
    frame = AnalysisSetupFrame(
        parent,
        title="Key Detector & Tagger",
        start_text="BEGIN KEY DETECTION",
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
        analysis_duration=analysis_duration,
        parallel_mode=parallel_mode,
        max_workers=max_workers,
        parallel_caption="(ProcessPoolExecutor bypasses GIL for chroma CQT)",
    )
    return frame.get_widgets()
