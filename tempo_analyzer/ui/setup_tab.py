"""
setup_tab.py — Setup tab for Tempo Analyzer & Tagger.

The tab opens with the shared DriverControlsPanel mirroring the Master
Driver's source bar and control strip, followed by tool-specific controls.
Returns a widget dict so app.py can call update_reference(markings)
whenever the scheme changes without the tab needing any knowledge of the
app layer.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame
from tempo_analyzer.core.tempo_schemes import MarkingList


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    tempo_scheme: tk.StringVar,
    scheme_names: list[str],
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    on_scheme_change: Callable[[], None],
    on_preset_select: Callable[[str], None],
    on_save_preset: Callable[[str], None],
    on_delete_preset: Callable[[str], None],
    driver_locked: bool = False,
) -> dict[str, Any]:
    """
    Populate the Setup tab.

    Args:
        on_scheme_change: Called (with no arguments) when the scheme
                          combobox selection changes.  The caller is
                          responsible for updating the marking list and
                          then calling update_reference().
        on_preset_select: Called with the selected preset name.
        on_save_preset: Called with the preset name to save.
        on_delete_preset: Called with the preset name to delete.

    Returns:
        Dict with keys: start_btn, update_reference,
        refresh_preset_list, preset_combo, controls_panel.
        update_reference(markings) redraws the scrollable reference table.
        refresh_preset_list(presets) updates the preset combobox values.
    """
    frame = _SetupFrame(
        parent,
        title="Tempo Analyzer & Tagger",
        start_text="BEGIN TEMPO ANALYSIS",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        driver_locked=driver_locked,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_select,
        tempo_scheme=tempo_scheme,
        scheme_names=scheme_names,
        on_scheme_change=on_scheme_change,
    )
    return {
        "start_btn": frame.start_btn,
        "update_reference": frame.update_reference,
        "refresh_preset_list": frame.refresh_preset_list,
        "preset_combo": frame.preset_combo,
        "controls_panel": frame.controls_panel,
    }


class _SetupFrame(BaseSetupFrame):
    """Tempo Analyzer Setup tab built on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        tempo_scheme: tk.StringVar,
        scheme_names: list[str],
        on_scheme_change: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        self._tempo_scheme = tempo_scheme
        self._scheme_names = scheme_names
        self._on_scheme_change = on_scheme_change
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
        # Informational subtitle
        info = (
            "This tool analyzes BPM values and tags files with tempo markings.\n"
            "BPM tags must already exist in your files."
        )
        tk.Label(
            self,
            text=info,
            font=styles.FONT_BODY,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(0, 15))

        # Scheme selector
        scheme_frame = tk.Frame(self, bg=styles.BG_WHITE)
        scheme_frame.pack(fill="x", pady=(10, 5))
        tk.Label(
            scheme_frame,
            text="Tempo Naming Scheme:",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            font=styles.FONT_LABEL_B,
        ).pack(side=tk.LEFT)
        scheme_menu = ttk.Combobox(
            scheme_frame,
            textvariable=self._tempo_scheme,
            font=styles.FONT_BODY,
            state="readonly",
            width=20,
        )
        scheme_menu["values"] = self._scheme_names
        scheme_menu.pack(side=tk.LEFT, padx=10)

        # Bind scheme change — trace_add is called by app.py so the callback
        # chain (update markings → save config → update reference) stays there.
        self._tempo_scheme.trace_add("write", lambda *_: self._on_scheme_change())

        # Scrollable reference table
        tempo_lf = tk.LabelFrame(
            self, text=" Tempo Marking Reference ", bg=styles.BG_WHITE, padx=15, pady=10
        )
        tempo_lf.pack(fill="both", expand=True, pady=(15, 10))

        canvas = tk.Canvas(tempo_lf, bg=styles.BG_WHITE, height=180)
        scrollbar = ttk.Scrollbar(tempo_lf, orient="vertical", command=canvas.yview)
        ref_frame = tk.Frame(canvas, bg=styles.BG_WHITE)

        ref_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.create_window((0, 0), window=ref_frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill="both", expand=True)
        scrollbar.pack(side=tk.RIGHT, fill="y")

        # ── Reference table renderer ──────────────────────────────────────────

        def update_reference(markings: MarkingList) -> None:
            """Redraw the scrollable reference table for the given markings."""
            for widget in ref_frame.winfo_children():
                widget.destroy()
            for min_bpm, max_bpm, marking in markings:
                range_text = (
                    f"{min_bpm}+ BPM:"
                    if max_bpm is None
                    else f"{min_bpm}-{max_bpm} BPM:"
                )
                row = tk.Frame(ref_frame, bg=styles.BG_WHITE)
                row.pack(fill="x", pady=2)
                tk.Label(
                    row,
                    text=range_text,
                    bg=styles.BG_WHITE,
                    fg=styles.FG_MAIN,
                    font=styles.FONT_BODY,
                    width=15,
                    anchor="w",
                ).pack(side=tk.LEFT)
                tk.Label(
                    row,
                    text=marking,
                    bg=styles.BG_WHITE,
                    font=styles.FONT_BODY_B,
                    fg=styles.FG_MAIN,
                ).pack(side=tk.LEFT)

        self.update_reference = update_reference
