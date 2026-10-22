"""
setup_tab.py
Setup tab for the Stem Separator.

Holds the source and output directory pickers, the model and stem selection,
the optional mix, and the compute device.  The device caption states what torch
actually reported, so a CPU-only torch build is visible before a run starts
rather than only in the log afterwards.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame, path_row

from ..core.models import MODEL_CHOICES, STEM_NAMES


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    output_dir: tk.StringVar,
    model: tk.StringVar,
    stem_vars: dict[str, tk.BooleanVar],
    write_mix: tk.BooleanVar,
    device: tk.StringVar,
    device_status: tk.StringVar,
    run_mode: tk.StringVar,
    on_browse: Callable[[], None],
    on_browse_output: Callable[[], None],
    on_refresh_device: Callable[[], None],
    on_start: Callable[[], None],
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar | None = None,
    parallel_var: tk.BooleanVar | None = None,
    driver_locked: bool = False,
) -> dict[str, Any]:
    """Populate the Setup tab and return widget references."""
    frame = _SetupFrame(
        parent,
        title="Stem Separator",
        start_text="BEGIN STEM SEPARATION",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        driver_locked=driver_locked,
        output_dir=output_dir,
        model=model,
        stem_vars=stem_vars,
        write_mix=write_mix,
        device=device,
        device_status=device_status,
        on_browse_output=on_browse_output,
        on_refresh_device=on_refresh_device,
    )
    return frame.get_widgets()


class _SetupFrame(BaseSetupFrame):
    """Stem Separator Setup tab built on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        output_dir: tk.StringVar,
        model: tk.StringVar,
        stem_vars: dict[str, tk.BooleanVar],
        write_mix: tk.BooleanVar,
        device: tk.StringVar,
        device_status: tk.StringVar,
        on_browse_output: Callable[[], None],
        on_refresh_device: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        self._output_dir = output_dir
        self._model = model
        self._stem_vars = stem_vars
        self._write_mix = write_mix
        self._device = device
        self._device_status = device_status
        self._on_browse_output = on_browse_output
        self._on_refresh_device = on_refresh_device
        super().__init__(parent, **kwargs)

    def _build_options(self) -> None:
        output_group = self.add_config_group("Output")
        path_row(
            output_group,
            "Stem output folder",
            self._output_dir,
            self._on_browse_output,
        )
        tk.Label(
            output_group,
            text="Each track gets its own subfolder: vocals, drums, bass, other.",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
        ).pack(anchor="w", pady=(4, 0))

        stems_group = self.add_config_group("Stems")
        row = tk.Frame(stems_group, bg=styles.BG_WHITE)
        row.pack(fill="x")
        for stem in STEM_NAMES:
            tk.Checkbutton(
                row,
                text=stem.capitalize(),
                variable=self._stem_vars[stem],
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                activebackground=styles.BG_WHITE,
            ).pack(side=tk.LEFT, padx=(0, 14))
        tk.Checkbutton(
            stems_group,
            text="Also write mix.wav (sum of the selected stems)",
            variable=self._write_mix,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
        ).pack(anchor="w", pady=(6, 0))

        model_group = self.add_config_group("Model and device")
        model_row = tk.Frame(model_group, bg=styles.BG_WHITE)
        model_row.pack(fill="x")
        tk.Label(
            model_row,
            text="Demucs model:",
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=14,
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            model_row,
            textvariable=self._model,
            values=list(MODEL_CHOICES),
            state="readonly",
            width=16,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT)

        device_row = tk.Frame(model_group, bg=styles.BG_WHITE)
        device_row.pack(fill="x", pady=(6, 0))
        tk.Label(
            device_row,
            text="Device:",
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=14,
            anchor="w",
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            device_row,
            textvariable=self._device,
            values=["auto", "cpu", "cuda"],
            state="readonly",
            width=8,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT)
        tk.Button(
            device_row,
            text="Re-check",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_CAPTION,
            padx=8,
            command=self._on_refresh_device,
        ).pack(side=tk.LEFT, padx=8)

        tk.Label(
            model_group,
            textvariable=self._device_status,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            wraplength=720,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(6, 0))
