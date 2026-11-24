"""
app.py
KeyDetectorApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

The window is the shared :class:`~audio_suite_shared.suite_app.SuiteApp`: the
shell builds the Help bar, the notebook, the Processing tab (progress, worker
grid, file list) and the Results tab, and owns the worker hand-off and the run
report.  This module supplies Key Detector's identity, its settings panel, the
run itself, and the rendering of the messages the run queues.

Changed in 2.9.0: the window composes ``SuiteApp`` (C1 stage 3).  The three
callbacks queue their payload for the shell's poller instead of calling
``root.after`` from the worker thread, and the run's settings are snapshotted on
the Tk thread before that thread starts, so the worker reads no widget and no
Tk variable.  The report is the shell's writer with this tool's two counter
words.

Changed in 2.9.0: the run controls are the shell's (D56).  The preset trio,
the ``audio_suite_config`` key builder, the driver's argv mirror,
``start_processing`` and the Auto End marker have one implementation in
``SuiteApp``; this window supplies its parser, its ``_run`` and its per-tick
stats line, and the only Auto End decision left here is which of the two
sources asked for the close.
Changed in 2.9.0: the Auto End condition is the shell's ``auto_end_requested``,
which reads both the driver's flag and the checkbox (D60).
"""

from __future__ import annotations

import os
import tkinter as tk
from queue import Queue
from typing import Any, ClassVar

from audio_suite_shared import suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.constants import (
    DEFAULT_ANALYSIS_SECONDS,
    DEFAULT_MAX_WORKERS,
    default_max_workers,
)
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars

from .core import file_processor
from .ui import setup_tab
from .utils.cli_args import parse as parse_cli
from .utils.cli_args import was_launched_from_driver


class KeyDetectorApp(SuiteApp):
    """Key Detector application GUI."""

    title = "Key Detector & Tagger"
    window_key = "key_detector_window"
    TOOL_ID: ClassVar[str] = "key_detector"
    program_name = TOOL_ID
    #: Kept for the guide registry scan; the shell reads ``guide_name``.
    HELP_GUIDE = "Key_Detector_User_Guide.docx"
    guide_name = HELP_GUIDE

    #: Prefix of this tool's ``audio_suite_config.json`` keys and of its report
    #: file names (``key_parallel_mode``, ``key_dry_run_log.txt``).
    SETTINGS_PREFIX: ClassVar[str] = "key"

    STARTING_STATUS: ClassVar[str] = "Detecting musical keys..."
    REPORT_HEADER: ClassVar[str] = "KEY DETECTION REPORT"
    #: The report's two counter words; the shell prints both verbatim.
    TAGGED_LABEL = "Tagged/Analyzed"
    SKIPPED_LABEL = "Skipped (already tagged)"
    LIVE_COMPLETION_TEXT: ClassVar[str] = "Key Tagging Complete!"
    DRY_RUN_COMPLETION_TEXT: ClassVar[str] = "Analysis Complete!"
    #: The heading the Results tab shows before the first run; a finished run
    #: replaces it with the dry/live text above.
    completion_text = "Key Detection Complete!"

    def __init__(self, root: tk.Tk) -> None:
        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")
        self.analysis_duration = tk.IntVar(value=DEFAULT_ANALYSIS_SECONDS)
        saved_parallel = bool(
            suite_config.load_value(self._setting_key("parallel_mode"), False)
        )
        workers_saved = suite_config.load_value(
            self._setting_key("max_workers"), default_max_workers()
        )
        saved_workers = (
            workers_saved if isinstance(workers_saved, int) else default_max_workers()
        )
        self.parallel_mode = tk.BooleanVar(value=saved_parallel)
        self.max_workers = tk.IntVar(value=saved_workers)

        # Driver-mirrored run controls (Clear Logs / Parallel are display-only)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self._launched_from_driver: bool = was_launched_from_driver()

        # ── The run's settings, snapshotted by start_processing ───────────────
        self._dir_path: str = ""
        self._is_dry_run: bool = True
        self._analysis_seconds: int = DEFAULT_ANALYSIS_SECONDS
        self._parallel: bool = False
        self._workers: int = default_max_workers()
        #: The driver's Auto End flag.  The Setup-tab checkbox is the other half:
        #: either one closes the window, because a driver launch cannot click it.
        self.auto_end: bool = False

        # ── Worker slot pool ──────────────────────────────────────────────────
        # Built before super().__init__: the shell renders the grid from it.
        self.slot_vars: list[tk.StringVar] = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        super().__init__(root)

        # ── CLI arguments ─────────────────────────────────────────────────────
        self._apply_cli_args()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Shell tabs ────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder row, the run controls and the analysis options."""
        widgets = setup_tab.build(
            parent,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            analysis_duration=self.analysis_duration,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
            parallel_mode=self.parallel_mode,
            max_workers=self.max_workers,
            preset_names=suite_config.list_presets(self.TOOL_ID),
            on_save_preset=self.store_preset,
            on_delete_preset=self.remove_preset,
            on_preset_selected=self.use_preset,
        )
        self.start_btn: tk.Button = widgets["start_btn"]
        self.controls_panel = widgets["controls_panel"]
        self._refresh_preset_list = widgets.get("refresh_preset_list")

    # ── Launcher handshake ────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        """Mirror the Master Driver's handshake onto the Setup tab."""
        self._mirror_cli_args(parse_cli())

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _open_folder(self) -> None:
        """Open the source folder, since this tool processes files in-place."""
        self._open_source_folder_standard()

    def _start_run(self) -> None:
        """Start the run ``start_processing`` snapshot on the shell's thread."""
        self._start_worker(self._run, ())

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="key_detector_app_run")
    def _run(self) -> None:
        """Analyse the snapshotted folder and queue the result for the poller."""
        is_dry_run = self._is_dry_run
        self._log_path = os.path.join(
            self._dir_path,
            f"{self.SETTINGS_PREFIX}_dry_run_log.txt"
            if is_dry_run
            else f"{self.SETTINGS_PREFIX}_sync_log.txt",
        )
        header = [
            f"{self.REPORT_HEADER}\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Analysis Duration: {self._analysis_seconds} seconds\n",
            f"Parallel: {'Yes' if self._parallel else 'No'}\n",
            f"Workers: {self._workers}\n",
            "=" * 60 + "\n",
        ]

        with active_batch(self.TOOL_ID, "tag_edit"):
            file_processor.run_analysis(
                dir_path=self._dir_path,
                is_dry_run=is_dry_run,
                analysis_duration=self._analysis_seconds,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(header=header, **kw),
                on_error=self._on_error,
                parallel_mode=self._parallel,
                max_workers=self._workers,
            )

    # ── Callbacks (worker thread: queue only, no widget writes) ──────────────

    def _on_progress(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
        """Queue one progress tick for the shell's poller."""
        self._ui_updates.put(
            ("progress", processed, total, skipped, errors, display_text)
        )

    def _on_complete(
        self,
        *,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        **_extra: Any,
    ) -> None:
        """Write the run's report, then queue the finished run.

        The report is serialised on the run's own thread; every widget write is
        the poller's.  ``analysed`` is what the run handled without skipping or
        erroring, which is the count the report and the Results tab show.
        """
        analysed = processed - skipped - errors
        self._write_run_report_standard(
            header=header,
            log_entries=log_entries,
            rows=(),
            total=total,
            tagged=analysed,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
        )
        self._ui_updates.put(
            ("complete", total, analysed, skipped, errors, duration_secs)
        )

    def _on_error(self, message: str) -> None:
        """Queue a fatal run error for the shell's poller."""
        self._ui_updates.put(("error", message))

    # ── Rendering (Tk thread: one queued message at a time) ──────────────────

    def _dispatch_ui_message(self, message: tuple[Any, ...]) -> None:
        """Render one queued message on the Tk thread."""
        kind = message[0]
        if kind == "progress":
            _, processed, total, skipped, errors, display_text = message
            self._render_progress_standard(processed, total, display_text)
            # The window's own counters: the shell's stats line is only its
            # starting text, and this tool reports all three counts per tick.
            self.stats_label.config(
                text=f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}"
            )
        elif kind == "complete":
            _, total, analysed, skipped, errors, duration_secs = message
            self._render_complete(total, analysed, skipped, errors, duration_secs)
        elif kind == "error":
            super()._on_error(message[1])

    def _render_complete(
        self,
        total: int,
        analysed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Show the finished run (Tk thread only)."""
        self.summary_label.config(
            text=(
                f"Total: {total} files\n"
                f"Tagged/Analyzed: {analysed}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        )
        self.completion_text = (
            self.DRY_RUN_COMPLETION_TEXT
            if self._is_dry_run
            else self.LIVE_COMPLETION_TEXT
        )
        self.render_completion(duration_secs=duration_secs, output_dir=self._dir_path)

        # Auto End is honoured from *either* source: the driver-issued flag, or
        # the Setup-tab checkbox, which is editable on a standalone launch.
        if self.auto_end_requested():
            self.close_for_auto_end()


def main() -> None:
    root = tk.Tk()
    KeyDetectorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
