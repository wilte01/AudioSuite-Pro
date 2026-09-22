"""
setup_tab.py
Setup tab for Noise Reduction tool.

Provides controls for hum removal (frequency, harmonics, Q) and
broadband noise reduction (noise profile region, gate threshold).
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame, slider_row


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    reduce_hum: tk.BooleanVar,
    hum_frequency: tk.IntVar,
    hum_harmonics: tk.IntVar,
    hum_quality: tk.DoubleVar,
    reduce_broadband: tk.BooleanVar,
    noise_start_ms: tk.IntVar,
    noise_end_ms: tk.IntVar,
    gate_threshold_db: tk.DoubleVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    preset_names: list[str] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
    clear_logs_var: tk.BooleanVar | None = None,
    parallel_var: tk.BooleanVar | None = None,
    driver_locked: bool = False,
) -> dict[str, Any]:
    """Populate the Setup tab and return widget references."""
    frame = _SetupFrame(
        parent,
        title="Noise Reduction",
        start_text="BEGIN NOISE REDUCTION",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        preset_names=preset_names,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        driver_locked=driver_locked,
        reduce_hum=reduce_hum,
        hum_frequency=hum_frequency,
        hum_harmonics=hum_harmonics,
        hum_quality=hum_quality,
        reduce_broadband=reduce_broadband,
        noise_start_ms=noise_start_ms,
        noise_end_ms=noise_end_ms,
        gate_threshold_db=gate_threshold_db,
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """Noise Reduction Setup tab built on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        reduce_hum: tk.BooleanVar,
        hum_frequency: tk.IntVar,
        hum_harmonics: tk.IntVar,
        hum_quality: tk.DoubleVar,
        reduce_broadband: tk.BooleanVar,
        noise_start_ms: tk.IntVar,
        noise_end_ms: tk.IntVar,
        gate_threshold_db: tk.DoubleVar,
        **kwargs: Any,
    ) -> None:
        self._reduce_hum = reduce_hum
        self._hum_frequency = hum_frequency
        self._hum_harmonics = hum_harmonics
        self._hum_quality = hum_quality
        self._reduce_broadband = reduce_broadband
        self._noise_start_ms = noise_start_ms
        self._noise_end_ms = noise_end_ms
        self._gate_threshold_db = gate_threshold_db
        super().__init__(parent, **kwargs)

    def _layout(self) -> None:
        """Presets sit above the Run Controls panel for this tool."""
        self._add_title()
        self._add_preset_row()
        if self._include_controls_panel:
            self._add_controls_panel()
        self._build_options()
        self._add_start_button()

    def _build_options(self) -> None:
        # ── Hum Removal ─────────────────────────────────────────────────────
        hum_frame = self.add_config_group("Hum Removal")

        tk.Checkbutton(
            hum_frame,
            text="Enable Hum Removal",
            variable=self._reduce_hum,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(anchor="w")

        freq_frame = tk.Frame(hum_frame, bg=styles.BG_WHITE)
        freq_frame.pack(fill="x", pady=3)
        tk.Label(
            freq_frame,
            text="Frequency:",
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=12,
            anchor="w",
        ).pack(side=tk.LEFT)
        for val in (50, 60):
            tk.Radiobutton(
                freq_frame,
                text=f"{val} Hz",
                variable=self._hum_frequency,
                value=val,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                activebackground=styles.BG_WHITE,
            ).pack(side=tk.LEFT, padx=5)

        slider_row(hum_frame, "Harmonics (1-20)", self._hum_harmonics, 1, 20, 1)
        slider_row(hum_frame, "Q Factor (1-100)", self._hum_quality, 1.0, 100.0, 1.0)

        # ── Broadband Noise Reduction ───────────────────────────────────────
        bb_frame = self.add_config_group("Broadband Noise Reduction")

        tk.Checkbutton(
            bb_frame,
            text="Enable Broadband Noise Reduction",
            variable=self._reduce_broadband,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(anchor="w")

        slider_row(bb_frame, "Noise Start (ms)", self._noise_start_ms, 0, 5000, 100)
        slider_row(bb_frame, "Noise End (ms)", self._noise_end_ms, 100, 10000, 100)
        slider_row(
            bb_frame, "Gate Threshold (dB)", self._gate_threshold_db, 0.0, 20.0, 0.5
        )
