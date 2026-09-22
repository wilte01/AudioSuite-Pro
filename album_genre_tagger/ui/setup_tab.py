"""
setup_tab.py
Setup tab for Album Genre Tagger.

Builds the shared Run Controls panel (mirroring the Master Driver),
preset management, coverage option, info box, and Start button.
No business logic — purely view.
"""

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    min_coverage: tk.IntVar,
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
        min_coverage:      Tk variable bound to the coverage entry.
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
        title="Album Genre Tagger",
        start_text="BEGIN GENRE CONSOLIDATION",
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
        min_coverage=min_coverage,
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """Album Genre Tagger Setup tab built on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        min_coverage: tk.IntVar,
        **kwargs: Any,
    ) -> None:
        self._min_coverage = min_coverage
        super().__init__(parent, **kwargs)

    def _build_options(self) -> None:
        # Minimum coverage
        tk.Label(
            self,
            text="Minimum Coverage (%):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(15, 0))
        tk.Entry(
            self,
            textvariable=self._min_coverage,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
            width=10,
        ).pack(anchor="w", pady=5)
        tk.Label(
            self,
            text="(Minimum percentage of files that must have TITLEGENRE tag)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

        # Info box
        info_frame = tk.Frame(self, bg=styles.BG_LIGHT, relief=tk.RIDGE, borderwidth=1)
        info_frame.pack(fill="x", pady=(20, 10))
        tk.Label(
            info_frame,
            text=(
                "This tool extracts TITLEGENRE tags from every supported audio "
                "file (MP3, FLAC, OGG, M4A, MP4, Opus, WAV, AIFF, AIF), "
                "consolidates them into unique, sorted values, and writes them "
                "to ALBUMGENRE and ALBUMDERIVED tags.\n\n"
                "Tags used:\n"
                "  MP3, WAV, AIFF, AIF - ID3 TXXX:TITLEGENRE / ALBUMGENRE / "
                "ALBUMDERIVED\n"
                "  FLAC, OGG, Opus - Vorbis TITLEGENRE / ALBUMGENRE / "
                "ALBUMDERIVED\n"
                "  M4A, MP4 - iTunes freeform TITLEGENRE / ALBUMGENRE / "
                "ALBUMDERIVED"
            ),
            font=styles.FONT_BODY,
            bg=styles.BG_LIGHT,
            fg=styles.FG_MAIN,
            justify=tk.LEFT,
            padx=15,
            pady=15,
        ).pack()
