"""
app.py
MoodAnalyzerApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

The window is the shared :class:`~audio_suite_shared.suite_app.SuiteApp`: the
shell builds the Help bar, the notebook, the Processing tab (progress, worker
grid, file list) and the Results tab, and owns the worker hand-off and the run
report.  This module supplies Mood Analyzer's identity, its settings panel, the
run itself, and the rendering of the messages the run queues.

Changed in 1.2.0: records the tracks the run had to skip as a run note, so a
batch report says so instead of only the tool's own log.

Changed in 2.9.0: the window composes ``SuiteApp`` (C1 stage 3, D54).  The three
callbacks queue their payload for the shell's poller instead of calling
``root.after`` from the run's thread, and the run's settings are
snapshotted on the Tk thread before that thread starts, so the worker reads no
widget and no Tk variable.  The report is the shell's writer with this tool's
two counter words, and the run note is recorded before it.  Two things stay the
window's own because the shell has no equivalent: the per-tick stats line, and
the Auto End marker and the driver-issued flag behind it.
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from queue import Queue
from tkinter import messagebox
from typing import Any, ClassVar

from audio_suite_shared import suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.constants import (
    DEFAULT_ANALYSIS_SECONDS,
    DEFAULT_MAX_WORKERS,
    default_max_workers,
)
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.run_outcome import record_caveats, shortfall
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_common import cap_typed_workers

from .core import file_processor
from .ui import setup_tab
from .utils.cli_args import parse as parse_cli
from .utils.cli_args import was_launched_from_driver

logger = logging.getLogger(__name__)

#: The Master Driver keys this tool's batch step — and therefore its run note
#: — by the manifest id.  It happens to equal the window key below, but the
#: constant is separate because the two keys are owned by different layers.
DRIVER_TOOL_ID = "mood_analyzer"

#: The line a run appends to its report when the window is closing itself.
_AUTO_END_MARKER = "\n[Auto End enabled - closing in 2 seconds...]\n"


class MoodAnalyzerApp(SuiteApp):
    """Mood Analyzer application GUI."""

    title = "Mood Analyzer & Tagger"
    window_key = "mood_analyzer_window"
    TOOL_ID: ClassVar[str] = "mood_analyzer"
    program_name = TOOL_ID
    #: Kept for the guide registry scan; the shell reads ``guide_name``.
    HELP_GUIDE = "Mood_Analyzer_User_Guide.docx"
    guide_name = HELP_GUIDE

    #: Prefix of this tool's ``audio_suite_config.json`` keys and of its report
    #: file names (``mood_parallel_mode``, ``mood_dry_run_log.txt``).
    SETTINGS_PREFIX: ClassVar[str] = "mood"

    STARTING_STATUS: ClassVar[str] = "Detecting mood from the audio signal..."
    REPORT_HEADER: ClassVar[str] = "MOOD DETECTION REPORT"
    #: The report's two counter words; the shell prints both verbatim.
    TAGGED_LABEL = "Tagged/Analyzed"
    SKIPPED_LABEL = "Skipped (undecodable/silent)"
    LIVE_COMPLETION_TEXT: ClassVar[str] = "Mood Tagging Complete!"
    DRY_RUN_COMPLETION_TEXT: ClassVar[str] = "Analysis Complete!"
    #: The heading the Results tab shows before the first run; a finished run
    #: replaces it with the dry/live text above.
    completion_text = "Mood Analysis Complete!"
    #: Set from argv in ``__init__``.  The default keeps an ``object.__new__``
    #: test shell on the interactive (modal-warning) path.
    _launched_from_driver: bool = False

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

        self._refresh_preset_list: Any = None

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
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
        )
        self.start_btn: tk.Button = widgets["start_btn"]
        self.controls_panel = widgets["controls_panel"]
        self._refresh_preset_list = widgets.get("refresh_preset_list")

    # ── Presets and settings ──────────────────────────────────────────────────

    def _setting_key(self, name: str) -> str:
        """Return this tool's ``audio_suite_config.json`` key for *name*."""
        return f"{self.SETTINGS_PREFIX}_{name}"

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "folder_path": self.folder_path.get(),
            "run_mode": self.run_mode.get(),
            "analysis_duration": self.analysis_duration.get(),
            "parallel_mode": self.parallel_mode.get(),
            "max_workers": self.max_workers.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "folder_path" in settings:
            self.folder_path.set(settings["folder_path"])
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])
        if "analysis_duration" in settings:
            self.analysis_duration.set(settings["analysis_duration"])
        if "parallel_mode" in settings:
            self.parallel_mode.set(settings["parallel_mode"])
        if "max_workers" in settings:
            self.max_workers.set(settings["max_workers"])

    def _on_preset_selected(self, name: str) -> None:
        settings = suite_config.load_preset(self.TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        suite_config.save_preset(self.TOOL_ID, name, self._collect_settings())
        self._refresh_preset_list(suite_config.list_presets(self.TOOL_ID))

    def _delete_preset(self, name: str) -> None:
        suite_config.delete_preset(self.TOOL_ID, name)
        self._refresh_preset_list(suite_config.list_presets(self.TOOL_ID))

    # ── Launcher handshake ────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        """Mirror the Master Driver's handshake onto the Setup tab."""
        parsed = parse_cli()
        if not parsed.folder_path:
            return

        self.folder_path.set(parsed.folder_path)
        self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)
        self.analysis_duration.set(parsed.analysis_duration)
        self.parallel_mode.set(parsed.parallel_mode)
        self.max_workers.set(parsed.max_workers)
        self.auto_end = parsed.auto_end

        if parsed.auto_start:
            self.root.after(1500, self.start_processing)

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

    def start_processing(self) -> None:
        """Validate the inputs, snapshot the run's settings and start it."""
        folder = self.folder_path.get()
        if not folder:
            messagebox.showwarning("Warning", "Please select a music directory first.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Error", "Selected path is not a valid directory.")
            return

        # A typed worker count can exceed the fixed slot grid; cap it on the
        # main thread (with a visible warning) before anything is persisted,
        # so the saved setting matches the run that actually happens (D66).
        workers = cap_typed_workers(
            self.max_workers,
            self._safe_slot_vars,
            unattended=self._launched_from_driver,
        )
        suite_config.save_value(
            self._setting_key("parallel_mode"), self.parallel_mode.get()
        )
        suite_config.save_value(self._setting_key("max_workers"), workers)

        # Snapshot on the Tk thread: the worker reads no widget and no Tk
        # variable (AGENTS.md, GUI callback contract).
        self._dir_path = folder
        self._is_dry_run = self.run_mode.get() == "Dry Run"
        self._analysis_seconds = self.analysis_duration.get()
        self._parallel = self.parallel_mode.get()
        self._workers = workers

        self.start_btn.config(state="disabled")
        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        self.notebook.select(self.processing_frame)
        self.overall_status.set(self.STARTING_STATUS)

        self._start_worker(self._run, ())

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="mood_analyzer_app_run")
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
        """Record the run's note, write its report, then queue the finished run.

        The note is recorded before the report, so a damaged Tk or an
        unwritable log cannot suppress what the Master Driver reads.  The
        report is serialised on the run's own thread; every widget write is the
        poller's.  ``analysed`` is what the run handled without skipping or
        erroring, which is the count the report and the Results tab show.
        """
        record_caveats(
            DRIVER_TOOL_ID,
            shortfall(
                skipped, total, "track", "had no usable audio (undecodable or silent)"
            )
            if skipped
            else "",
            shortfall(errors, total, "track", "could not be analyzed")
            if errors
            else "",
        )
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
        # Consulting only the flag left the checkbox inert there.
        if self.auto_end_var.get() or self.auto_end:
            self._mark_auto_end()
            self.root.after(2000, self.root.destroy)

    def _mark_auto_end(self) -> None:
        """Append the Auto End marker to the run's report (best effort).

        The marker is the window's own, not the shell's: it records that this
        run asked to close itself, which only a tool honouring the driver's flag
        knows.  The audio work is already done and the window is about to close,
        so a report that cannot be appended to is a log line, never a dialog.
        """
        try:
            with open(self._log_path, "a", encoding="utf-8") as handle:
                handle.write(_AUTO_END_MARKER)
        except OSError as exc:
            logger.warning("Could not append the Auto End marker: %s", exc)


def main() -> None:
    root = tk.Tk()
    MoodAnalyzerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
