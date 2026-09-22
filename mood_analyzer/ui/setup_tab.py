"""setup_tab.py — Setup tab for Mood Analyzer."""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame

_HELP_TEXT = (
    "Mood is determined from the audio signal itself: tempo, spectral flux, "
    "zero-crossing rate and RMS energy estimate arousal; musical mode "
    "(major/minor), spectral brightness and low-band energy estimate valence. "
    "The valence\u2013arousal point selects the 3 most-fitted mood words "
    "(e.g. \u201cEnergetic;Bright;Confident\u201d) plus a 0\u20131 confidence "
    "score and a 1\u20136 energy band. Files that cannot be decoded or are "
    "near-silent are skipped; the rest are analysed in full."
)


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
    frame = _SetupFrame(
        parent,
        title="Mood Analyzer",
        start_text="BEGIN MOOD DETECTION",
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
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """Mood Analyzer Setup tab built on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        analysis_duration: tk.IntVar,
        parallel_mode: tk.BooleanVar | None = None,
        max_workers: tk.IntVar | None = None,
        **kwargs: Any,
    ) -> None:
        self._analysis_duration = analysis_duration
        self._parallel_mode = parallel_mode
        self._max_workers = max_workers
        super().__init__(parent, **kwargs)

    def _build_options(self) -> None:
        # Analysis duration
        tk.Label(
            self,
            text="Analysis Duration (seconds):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(15, 0))
        tk.Entry(
            self,
            textvariable=self._analysis_duration,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
            width=10,
        ).pack(anchor="w", pady=5)
        tk.Label(
            self,
            text="(Lower values = faster processing, less accuracy)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

        # Parallel processing
        if self._parallel_mode is not None and self._max_workers is not None:
            self.add_parallel_row(
                self._parallel_mode,
                self._max_workers,
                "(ProcessPoolExecutor bypasses GIL for CQT / FFT)",
            )

        # How mood is determined
        tk.Label(
            self,
            text="How Mood Is Determined:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(20, 2))
        tk.Label(
            self,
            text=_HELP_TEXT,
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            justify="left",
            wraplength=520,
        ).pack(anchor="w")
