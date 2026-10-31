"""
app.py
PopClickRemoverApp — thin orchestrator for the Pop & Click Remover tool.

Changed in 2.3.0: the completion payload is marshalled positionally - ``after()`` takes
no keywords (found while wiring the F-02 window).
"""

from __future__ import annotations

import logging
import tkinter as tk
from functools import partial
from typing import Any

from audio_suite_shared.tool_app_base import NoisePopToolApp

from .core.file_processor import run_declicking
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "pop_click_remover"


class PopClickRemoverApp(NoisePopToolApp):
    """Pop & Click Remover application GUI."""

    TOOL_ID = TOOL_ID
    TOOL_TITLE = "Pop & Click Remover"
    HELP_GUIDE = "Pop_Click_Remover_User_Guide.docx"
    RESULTS_LABEL = "Succeeded"
    COMPLETION_LABEL = "Pop & Click Removal Complete!"

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(root)

    # ── Subclass hooks ────────────────────────────────────────────────────

    def _create_tool_variables(self) -> None:
        self.sensitivity = tk.DoubleVar(value=0.31)
        self.max_width = tk.IntVar(value=2)

    def _build_setup_controls(self, tab_setup: tk.Frame) -> dict[str, Any]:
        return setup_tab.build(
            tab_setup,
            **self._build_setup_shared_kwargs(),
            sensitivity=self.sensitivity,
            max_width=self.max_width,
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
        return None

    def _run_engine_in_batch(self, folder: str, is_dry_run: bool) -> None:
        sens = self.sensitivity.get()
        width = self.max_width.get()

        def _complete(**kw: Any) -> None:
            # ``Misc.after`` takes positional arguments only: forwarding the
            # published keyword payload as ``after(0, fn, **kw)`` raises
            # ``TypeError`` inside the completion call, so a finished batch
            # reported nothing.  Bind it into the callback instead.
            self.root.after(0, partial(self._on_complete, **kw))

        def _fail(msg: str) -> None:
            self.root.after(0, self._on_error, msg)

        run_declicking(
            folder,
            is_dry_run,
            sens,
            width,
            self._safe_slot_vars,
            self.slot_queue,
            self._on_progress,
            _complete,
            _fail,
        )

    def _apply_tool_cli_options(self, parsed: Any) -> None:
        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        if parsed.sensitivity:
            self.sensitivity.set(parsed.sensitivity)
        if parsed.width:
            self.max_width.set(parsed.width)
        if parsed.auto_end:
            self.auto_end_var.set(True)

    def _tool_cli_parse(self) -> Any:
        return cli_args.parse()

    # ── Presets ─────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "sensitivity": self.sensitivity.get(),
            "max_width": self.max_width.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "sensitivity" in settings:
            self.sensitivity.set(settings["sensitivity"])
        if "max_width" in settings:
            self.max_width.set(settings["max_width"])
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])


def main() -> None:
    """Standalone entry point: create the Tk root, run the app."""
    root = tk.Tk()
    PopClickRemoverApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
