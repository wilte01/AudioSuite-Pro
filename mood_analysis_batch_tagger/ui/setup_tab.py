"""
setup_tab.py
Builds the Setup tab widgets for Mood Analysis Batch Tagger.
"""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared.ui_common import AnalysisSetupFrame

_HELP_TEXT = (
    "The Mood Analysis Batch Tagger recursively scans the selected root "
    "directory and all its subfolders, analysing every supported audio file "
    "(.mp3, .flac, .ogg, .m4a, .mp4, .opus, .wav, .aiff/.aif) it finds.\n\n"
    "Mood is determined from the audio signal itself — tempo, spectral flux, "
    "zero-crossing rate and RMS energy estimate arousal; musical mode "
    "(major/minor), spectral brightness and low-band energy estimate valence. "
    "The valence\u2013arousal point selects the 3 most-fitted mood words "
    "(e.g. \u201cEnergetic;Bright;Confident\u201d) plus a 0\u20131 confidence "
    "score and a 1\u20136 energy band.\n\n"
    "In Live Update mode mood and confidence tags are written to each file; "
    "in Dry Run mode they are only reported.  Files that cannot be decoded or "
    "are near-silent are skipped.\n"
    "A log file (mood_analysis_batch_log.txt) is written to the root folder."
)


def build(
    parent: tk.Frame,
    root_path: tk.StringVar,
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
        title="Mood Analysis Batch Tagger",
        start_text="BEGIN BATCH MOOD ANALYSIS",
        on_start=on_start,
        folder_path=root_path,
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
        parallel_caption="(ProcessPoolExecutor bypasses GIL for CQT / FFT)",
        help_heading="How Mood Is Determined:",
        help_text=_HELP_TEXT,
    )
    return frame.get_widgets()
