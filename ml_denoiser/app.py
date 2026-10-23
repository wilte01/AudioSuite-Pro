"""
app.py
MlDenoiserApp — thin orchestrator for the ML Denoiser.

The tool is the neural sibling of Noise Reduction: it rewrites files in place,
so it is built on ``NoisePopToolApp`` and inherits the shared undo batch, the
audition controls and the progress/complete/report plumbing.  What it adds is
one setting (how much of RNNoise's output to keep) and one pre-flight check that
the ``ml`` extra is installed.

That check belongs in ``_validate_start`` rather than at the first file: without
it a missing extra would surface as a batch where every file errored, which
reads like a data problem instead of a missing install.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).

Changed in 2.1.0: a missing RNNoise is installed by the tool on first use
    (verified by an import in a fresh process) instead of refusing the run with
    an "install the ml extra" dialog; ``_validate_start`` keeps only the
    settings check.
"""

from __future__ import annotations

import logging
import tkinter as tk
from typing import Any, cast

from audio_suite_shared import optional_deps, ui_common
from audio_suite_shared.tool_app_base import NoisePopToolApp

from .core.file_processor import run_ml_denoise
from .core.models import DEFAULT_AMOUNT, DenoiseParams
from .core.rnnoise_engine import missing_dependency_reason
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "ml_denoiser"


class MlDenoiserApp(NoisePopToolApp):
    """ML Denoiser application GUI."""

    TOOL_ID = TOOL_ID
    TOOL_TITLE = "ML Denoiser"
    HELP_GUIDE = "ML_Denoiser_User_Guide.docx"
    RESULTS_LABEL = "Denoised"
    COMPLETION_LABEL = "ML Denoising Complete!"

    # ── Subclass hooks ────────────────────────────────────────────────────

    def _create_tool_variables(self) -> None:
        # Percent, because the slider is the control a user reads.
        self.denoise_amount = tk.IntVar(value=int(DEFAULT_AMOUNT * 100))

    def _build_setup_controls(self, tab_setup: tk.Frame) -> dict[str, Any]:
        return setup_tab.build(
            tab_setup,
            **self._build_setup_shared_kwargs(),
            amount=self.denoise_amount,
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
        if self.denoise_amount.get() <= 0:
            return "Set the denoise amount above 0%."
        return None

    def _on_start(self) -> None:
        """Provide RNNoise on first use, then run the shared start path.

        A denoise measures the level change, so even a dry run needs the
        model: the install is prompted here rather than reporting the missing
        extra after the user has already asked for a run.
        """
        if missing_dependency_reason() is not None:
            ui_common.install_optional_dependency(
                self.root,
                optional_deps.RNNOISE,
                on_ready=self._start_after_install,
            )
            return
        super()._on_start()

    def _start_after_install(self) -> None:
        """Continue the start that the install was holding back."""
        super()._on_start()

    def _run_engine_in_batch(self, folder: str, is_dry_run: bool) -> None:
        params = DenoiseParams(
            amount=self.denoise_amount.get() / 100.0,
            dry_run=is_dry_run,
        )
        run_ml_denoise(
            dir_path=folder,
            params=params,
            slot_vars=self._safe_slot_vars,
            slot_queue=self.slot_queue,
            on_progress=self._on_progress,
            on_complete=self._on_complete,
            on_error=self._on_error,
        )

    def _on_complete(
        self,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        **_extra: Any,
    ) -> None:
        """Marshal the shared completion render onto the Tk thread.

        The processor calls this from a worker thread; the shared render touches
        widgets directly, so it is scheduled with ``root.after`` instead of run
        inline (AGENTS: "Handlers run off the Tk thread").
        """
        self.root.after(
            0,
            cast(Any, self._render_complete),
            total,
            succeeded,
            skipped,
            errors,
            duration_secs,
            log_entries,
        )

    def _render_complete(
        self,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
    ) -> None:
        """Render the shared completion summary (runs on the Tk thread)."""
        super()._on_complete(
            total=total,
            succeeded=succeeded,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            log_entries=log_entries,
        )

    def _apply_tool_cli_options(self, parsed: Any) -> None:
        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        if parsed.amount is not None:
            self.denoise_amount.set(int(round(parsed.amount * 100)))
        if parsed.auto_end:
            self.auto_end_var.set(True)

    def _tool_cli_parse(self) -> Any:
        return cli_args.parse()

    # ── Presets ─────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "denoise_amount": self.denoise_amount.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "denoise_amount" in settings:
            self.denoise_amount.set(int(settings["denoise_amount"]))
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])


def main() -> None:
    """Standalone entry point: create the Tk root, run the app."""
    root = tk.Tk()
    MlDenoiserApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
