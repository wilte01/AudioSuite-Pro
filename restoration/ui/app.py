"""Tkinter window for the Restoration (declip) tool.

Built on ``NoisePopToolApp`` — the shared scaffold for the in-place DSP tools —
so the window is the suite's three standard tabs, the Run Controls strip, the
worker-slot grid, the before/after audition row and the undo batch, with only the
DSP and its wording supplied here.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

import logging
import tkinter as tk
from functools import partial
from typing import Any

from audio_suite_shared.tool_app_base import NoisePopToolApp

from ..core.declipper import DEFAULT_MAX_RUN_MS, DEFAULT_THRESHOLD
from ..core.file_processor import run_declipping
from ..utils import cli_args
from . import processing_tab, results_tab, setup_tab

logger = logging.getLogger(__name__)


class RestorationApp(NoisePopToolApp):
    """Restoration (declip) application window."""

    TOOL_ID = "restoration"
    TOOL_TITLE = "Restoration (Declip)"
    HELP_GUIDE = "Restoration_User_Guide.docx"
    RESULTS_LABEL = "Repaired"
    COMPLETION_LABEL = "Declip Complete!"

    # ── Subclass hooks ────────────────────────────────────────────────────

    def _create_tool_variables(self) -> None:
        self.threshold = tk.DoubleVar(value=DEFAULT_THRESHOLD)
        self.max_run = tk.IntVar(value=DEFAULT_MAX_RUN_MS)

    def _build_setup_controls(self, tab_setup: tk.Frame) -> dict[str, Any]:
        return setup_tab.build(
            tab_setup,
            **self._build_setup_shared_kwargs(),
            threshold=self.threshold,
            max_run=self.max_run,
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
        """Reject a threshold or plateau width the DSP cannot honour.

        Returns:
            A message to show instead of starting, or None.
        """
        threshold = float(self.threshold.get())
        if not 0.0 < threshold <= 1.0:
            return "The clipping threshold must be greater than 0 and at most 1."
        if int(self.max_run.get()) < 1:
            return "The maximum plateau width must be at least 1 ms."
        return None

    def _run_engine_in_batch(self, folder: str, is_dry_run: bool) -> None:
        """Run this tool's engine inside the undo batch the base established."""
        threshold = float(self.threshold.get())
        max_run = int(self.max_run.get())

        def _complete(**kwargs: Any) -> None:
            # ``Misc.after`` takes positional arguments only: forwarding the
            # published keyword payload as ``after(0, fn, **kwargs)`` raises
            # ``TypeError`` inside the completion call, so a finished batch
            # reported nothing.  Bind it into the callback instead.
            self.root.after(0, partial(self._on_complete, **kwargs))

        def _fail(message: str) -> None:
            self.root.after(0, self._on_error, message)

        run_declipping(
            folder,
            is_dry_run,
            threshold,
            max_run,
            self._safe_slot_vars,
            self.slot_queue,
            self._on_progress,
            _complete,
            _fail,
        )

    def _apply_tool_cli_options(self, parsed: Any) -> None:
        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        if parsed.threshold:
            self.threshold.set(parsed.threshold)
        if parsed.run_ms:
            self.max_run.set(parsed.run_ms)
        if parsed.auto_end:
            self.auto_end_var.set(True)

    def _tool_cli_parse(self) -> Any:
        return cli_args.parse()

    # ── Presets ───────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "threshold": float(self.threshold.get()),
            "max_run": int(self.max_run.get()),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "threshold" in settings:
            self.threshold.set(float(settings["threshold"]))
        if "max_run" in settings:
            self.max_run.set(int(settings["max_run"]))
        if "run_mode" in settings:
            self.run_mode.set(str(settings["run_mode"]))


def main() -> None:
    """Standalone entry point: create the Tk root and run the window."""
    root = tk.Tk()
    RestorationApp(root)
    root.mainloop()
