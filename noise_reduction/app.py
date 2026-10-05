"""
app.py
NoiseReductionApp — thin orchestrator for the Noise Reduction tool.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Any, cast

from audio_suite_shared.tool_app_base import NoisePopToolApp

from .core.file_processor import run_noise_reduction
from .core.models import NoiseReductionParams
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "noise_reduction"


class NoiseReductionApp(NoisePopToolApp):
    """Noise Reduction application GUI."""

    TOOL_ID = TOOL_ID
    TOOL_TITLE = "Noise Reduction"
    HELP_GUIDE = "Noise_Reduction_User_Guide.docx"
    RESULTS_LABEL = "Reduced"
    COMPLETION_LABEL = "Noise Reduction Complete!"

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root)

    # ── Subclass hooks ────────────────────────────────────────────────────

    def _create_tool_variables(self) -> None:
        # Hum removal
        self.reduce_hum = tk.BooleanVar(value=False)
        self.hum_frequency = tk.IntVar(value=60)
        self.hum_harmonics = tk.IntVar(value=8)
        self.hum_quality = tk.DoubleVar(value=30.0)

        # Broadband noise
        self.reduce_broadband = tk.BooleanVar(value=False)
        self.noise_start_ms = tk.IntVar(value=0)
        self.noise_end_ms = tk.IntVar(value=500)
        self.gate_threshold_db = tk.DoubleVar(value=3.0)

    def _build_setup_controls(self, tab_setup: tk.Frame) -> dict[str, Any]:
        return setup_tab.build(
            tab_setup,
            **self._build_setup_shared_kwargs(),
            reduce_hum=self.reduce_hum,
            hum_frequency=self.hum_frequency,
            hum_harmonics=self.hum_harmonics,
            hum_quality=self.hum_quality,
            reduce_broadband=self.reduce_broadband,
            noise_start_ms=self.noise_start_ms,
            noise_end_ms=self.noise_end_ms,
            gate_threshold_db=self.gate_threshold_db,
        )

    def _build_processing_controls(self, tab_processing: tk.Frame) -> dict[str, Any]:
        return processing_tab.build(tab_processing, self.slot_vars)

    def _build_results_controls(self, tab_results: tk.Frame) -> dict[str, Any]:
        return results_tab.build(
            tab_results,
            self._open_log,
            self._open_folder,
            on_play_original=self._play_original,
            on_play_result=self._play_result,
        )

    def _validate_start(self) -> str | None:
        if not self.reduce_hum.get() and not self.reduce_broadband.get():
            return "Enable at least one of Hum Removal or Broadband Noise Reduction."
        return None

    def _run_engine_in_batch(self, folder: str, is_dry_run: bool) -> None:
        params = NoiseReductionParams(
            reduce_hum=self.reduce_hum.get(),
            hum_frequency=self.hum_frequency.get(),
            hum_harmonics=self.hum_harmonics.get(),
            hum_quality=self.hum_quality.get(),
            reduce_broadband=self.reduce_broadband.get(),
            noise_start_ms=self.noise_start_ms.get(),
            noise_end_ms=self.noise_end_ms.get(),
            gate_threshold_db=self.gate_threshold_db.get(),
            dry_run=is_dry_run,
        )

        def _complete(**kw: Any) -> None:
            self.root.after(0, cast(Any, self._on_complete), **kw)

        def _fail(msg: str) -> None:
            self.root.after(0, self._on_error, msg)

        run_noise_reduction(
            folder,
            params,
            self._safe_slot_vars,
            self.slot_queue,
            self._on_progress,
            _complete,
            _fail,
        )

    def _apply_tool_cli_options(self, parsed: Any) -> None:
        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        if parsed.reduce_hum:
            self.reduce_hum.set(True)
        if parsed.hum_frequency:
            self.hum_frequency.set(parsed.hum_frequency)
        if parsed.hum_harmonics:
            self.hum_harmonics.set(parsed.hum_harmonics)
        if parsed.hum_quality:
            self.hum_quality.set(parsed.hum_quality)
        if parsed.reduce_broadband:
            self.reduce_broadband.set(True)
        if parsed.noise_start_ms:
            self.noise_start_ms.set(parsed.noise_start_ms)
        if parsed.noise_end_ms:
            self.noise_end_ms.set(parsed.noise_end_ms)
        if parsed.gate_threshold_db:
            self.gate_threshold_db.set(parsed.gate_threshold_db)
        if parsed.auto_end:
            self.auto_end_var.set(True)

    def _tool_cli_parse(self) -> Any:
        return cli_args.parse()

    # ── Presets ─────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "reduce_hum": self.reduce_hum.get(),
            "hum_frequency": self.hum_frequency.get(),
            "hum_harmonics": self.hum_harmonics.get(),
            "hum_quality": self.hum_quality.get(),
            "reduce_broadband": self.reduce_broadband.get(),
            "noise_start_ms": self.noise_start_ms.get(),
            "noise_end_ms": self.noise_end_ms.get(),
            "gate_threshold_db": self.gate_threshold_db.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        for key in (
            "reduce_hum",
            "hum_frequency",
            "hum_harmonics",
            "hum_quality",
            "reduce_broadband",
            "noise_start_ms",
            "noise_end_ms",
            "gate_threshold_db",
        ):
            if key in settings:
                var = getattr(self, key)
                var.set(settings[key])
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])


def main() -> None:
    """Standalone entry point: create the Tk root, run the app."""
    root = tk.Tk()
    NoiseReductionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
