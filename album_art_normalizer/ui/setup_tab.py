"""
setup_tab.py — Setup tab for Album Art Normalizer.

Builds the directory picker, resolution selector, and DriverControlsPanel.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame

RESOLUTION_LABELS = ("600×600", "800×800", "1000×1000", "1200×1200")
RESOLUTION_MAP: dict[str, tuple[int, int]] = {
    "600×600": (600, 600),
    "800×800": (800, 800),
    "1000×1000": (1000, 1000),
    "1200×1200": (1200, 1200),
}


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    resolution: tk.StringVar,
    run_mode: tk.StringVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    driver_locked: bool = False,
) -> dict[str, Any]:
    """Populate the Setup tab.

    Args:
        parent: The tab Frame to populate.
        folder_path: StringVar bound to the directory entry.
        resolution: StringVar for the selected embedded resolution label.
        run_mode: StringVar for the Dry Run / Live Update combobox.
        on_browse: Callback for the Browse button.
        on_start: Callback for the Start button.
        auto_start_var: Mirrors the driver's Auto Start (display only).
        auto_end_var: Mirrors the driver's Auto End.
        clear_logs_var: Mirrors the driver's Clear Logs (display only).
        parallel_var: Mirrors the driver's Parallel option (display only).
        driver_locked: True after a Master Driver launch — locks the
            Run Controls panel to the inherited values.

    Returns:
        Dict with keys: start_btn (tk.Button), controls_panel.
    """
    frame = _SetupFrame(
        parent,
        title="Album Art Normalizer",
        start_text="BEGIN ARTWORK NORMALIZATION",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        driver_locked=driver_locked,
        resolution=resolution,
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """Album Art Normalizer Setup tab built on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        resolution: tk.StringVar,
        **kwargs: Any,
    ) -> None:
        self._resolution = resolution
        super().__init__(parent, **kwargs)

    def _build_options(self) -> None:
        tk.Label(
            self,
            text=(
                "Select the folder containing .mp3 or .flac files whose embedded\n"
                "artwork you want to resize to a consistent standard."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(2, 20))

        tk.Label(
            self,
            text="Embedded Image Resolution:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(10, 4))

        res_combo = ttk.Combobox(
            self,
            textvariable=self._resolution,
            values=list(RESOLUTION_LABELS),
            state="readonly",
            font=styles.FONT_BODY,
            width=18,
        )
        res_combo.pack(anchor="w", pady=(0, 4))

        tk.Label(
            self,
            text=(
                "Artwork that does not match the chosen size will be centre-cropped\n"
                "and resized. folder.jpg (if present) is"
                " always normalised to 1000×1000."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(2, 30))
