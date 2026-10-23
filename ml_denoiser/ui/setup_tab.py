"""
setup_tab.py
Setup tab for the ML Denoiser.

One control carries the whole decision: how much of the model's output to keep.
The panel says plainly what the model is (speech-trained) and what a blend is
for, because the measured behaviour — a 220 Hz tone attenuated by ~24 dB — is
not obvious from the word "denoise" (PLAN_feature_expansion.md D116).

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
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
    amount: tk.IntVar,
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
        title="ML Denoiser",
        start_text="BEGIN ML DENOISING",
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
        amount=amount,
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """ML Denoiser Setup tab built on the shared BaseSetupFrame."""

    def __init__(self, parent: tk.Frame, amount: tk.IntVar, **kwargs: Any) -> None:
        self._amount = amount
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
        group = self.add_config_group("Neural Denoising (RNNoise)")

        slider_row(group, "Denoise Amount (%)", self._amount, 1, 100, 1)

        tk.Label(
            group,
            text=(
                "100 % keeps the model's own result. Lower values blend the "
                "source back in, which is what music needs: the model is "
                "trained on speech and attenuates tonal content heavily."
            ),
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            justify=tk.LEFT,
            wraplength=520,
        ).pack(anchor="w", pady=(6, 2))

        tk.Label(
            group,
            text=(
                "Dry Run still runs the model: it measures each file's "
                "attenuation and writes nothing."
            ),
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            justify=tk.LEFT,
            wraplength=520,
        ).pack(anchor="w", pady=(2, 2))
