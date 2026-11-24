"""
app.py
GenreSetterApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

Changed in 1.4.0: the worker slot grid is sized from ``DEFAULT_MAX_WORKERS``
instead of a literal 4 (PLAN D56).
Changed in 1.4.1: ``_on_progress`` accepts ``**_extra: Any``, so a progress field
the processor adds is ignored instead of aborting a running batch
(``tests/test_callback_payload_contract.py``).

Changed in 2.7.0: the blind-``except`` boundary is named for the BLE001 triage
(WP-7 of ``PLAN_2026-11-03_2.4.1_stop_the_drift.md``, section 10).

Changed in 2.9.0: the source-folder opener is the shared mixin helper (A1).
Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, the second window of
D8's wave 2), so the shell owns the Help bar and the Processing and Results
tabs; this tool keeps its Setup panel and its per-run completion wording. The
runner calls the progress and completion handlers from its worker pool, so both
now do their file I/O there and hand every widget write to the Tk thread.
Changed in 2.9.0: the run's folder and mode are read once in
``start_processing``, so neither the worker nor the completion calls ``.get()``
on a Tk variable off the Tk thread.
Changed in 2.9.0: the preset trio (select, save, delete) is the shell's,
so this window declares the settings a preset carries and keeps only that (D58).
"""

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox
from typing import Any

from audio_suite_shared import suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars

from .core import file_processor, log_builder
from .ui import setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "genre_sync"


class GenreSetterApp(SuiteApp):
    """Genre Sync application GUI."""

    title = "Genre Sync"
    window_key = "genre_sync_window"
    program_name = TOOL_ID
    guide_name = "Genre_Sync_User_Guide.docx"
    completion_text = "Processing Complete!"
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" 1. Setup ", " 2. Processing ", " 3. Results ")
    # The counters this tool reports; a run overwrites the line from its ticks.
    processing_stats_text = "Processed: 0 | Updated: 0 | Skipped: 0 | Errors: 0"

    #: The key these presets live under in the shared store.
    TOOL_ID = TOOL_ID
    #: The settings a preset carries, in the order it has always stored them.
    PRESET_FIELDS = ("run_mode",)

    def __init__(self, root: tk.Tk):
        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        # Master Driver handshake: any CLI argument means driver-launched,
        # in which case the Run Controls panel is locked to inherited values.
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # ── State ─────────────────────────────────────────────────────────────
        self._dir_path: str = ""
        self._run_path: str = ""
        self._run_mode: str = ""
        self.auto_end: bool = False

        # ── Worker slot pool ──────────────────────────────────────────────────
        # Built before super().__init__: the shell renders the grid from it.
        self.root = root
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        super().__init__(root)
        self._apply_cli_args()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Shell tabs ────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the run controls, the presets and the genre rules into *parent*."""
        widgets = setup_tab.build(
            parent,
            title=self.title,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
            preset_names=suite_config.list_presets(TOOL_ID),
            on_save_preset=self.store_preset,
            on_delete_preset=self.remove_preset,
            on_preset_selected=self.use_preset,
        )
        self.start_btn = widgets["start_btn"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self.controls_panel = widgets["controls_panel"]

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        parsed = cli_args.parse()

        # Mirror the inherited driver arguments onto the Run Controls
        # panel before any early return so the display always reflects
        # exactly what the Master Driver passed.
        self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        if not parsed.folder_path:
            return

        # Universal CLI handling
        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed, folder_var=self.folder_path, auto_start_func=self.start_processing
        )

        # Auto-start if instructed by Master Driver
        if should_auto_start:
            self.root.after(1500, self.start_processing)

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _open_folder(self) -> None:
        """Open the source folder since Genre Sync processes files in-place."""
        self._open_source_folder_standard()

    def _reset_ui(self) -> None:
        self.notebook.select(self.setup_frame)
        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        self.stats_label.config(text=self.processing_stats_text)

    def start_processing(self) -> None:
        folder = self.folder_path.get()
        if not folder:
            messagebox.showwarning("Warning", "Please select a music directory first.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Error", "Selected path is not a valid directory.")
            return

        self.start_btn.config(state="disabled")
        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        self.stats_label.config(text=self.processing_stats_text)
        self.notebook.select(self.processing_frame)
        self.overall_status.set("Processing genre fields...")

        # Snapshot the run's inputs on the main thread: neither the worker nor
        # the completion may call .get() on a Tk variable (see _run).
        self._run_path = folder
        self._run_mode = self.run_mode.get()

        threading.Thread(target=self._run, daemon=True).start()

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="genre_sync_app_run")
    def _run(self) -> None:
        """Run the batch on a worker thread.

        Thread safety: the runner publishes progress and completion from its
        own pool, so those handlers do their file I/O here and hand every
        widget write to the Tk thread. The run's inputs are the snapshot
        ``start_processing`` took on the main thread, never a Tk variable read
        from here.
        """
        dir_path = self._run_path
        is_dry_run = self._run_mode == "Dry Run"
        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            "genre_dry_run_log.txt" if is_dry_run else "genre_sync_log.txt",
        )

        with active_batch("genre_sync", "tag_edit"):
            file_processor.run_processing(
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=self._on_complete,
                on_error=self._on_error,
            )

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_progress(
        self,
        processed: int,
        total: int,
        updated: int,
        skipped: int,
        no_genre: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
        """Progress seam: hand the widget writes to the Tk thread."""
        self.root.after(
            0,
            self._update_progress_ui,
            processed,
            total,
            updated,
            skipped,
            no_genre,
            errors,
            display_text,
        )

    def _update_progress_ui(
        self,
        processed: int,
        total: int,
        updated: int,
        skipped: int,
        no_genre: int,
        errors: int,
        display_text: str,
    ) -> None:
        """Render one progress tick (must run on the main thread)."""
        self._render_progress_standard(processed, total, display_text)
        self.stats_label.config(
            text=f"Processed: {processed} | Updated: {updated}"
            f" | Skipped: {skipped} | Errors: {errors}"
        )

    def _on_complete(
        self,
        total: int,
        updated: int,
        skipped: int,
        no_genre: int,
        errors: int,
        duration_secs: float,
        log_updated: list[Any],
        log_skipped: list[Any],
        log_no_genre: list[Any],
        log_errors: list[Any],
        **kwargs: object,
    ) -> None:
        """Completion seam: write the report here, render it on the Tk thread."""
        is_dry_run = self._run_mode == "Dry Run"

        log_lines = log_builder.build_log_lines(
            is_dry_run=is_dry_run,
            total=total,
            updated_count=updated,
            skipped_count=skipped,
            no_genre_count=no_genre,
            error_count=errors,
            duration_secs=duration_secs,
            log_updated=log_updated,
            log_skipped=log_skipped,
            log_no_genre=log_no_genre,
            log_errors=log_errors,
        )

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(log_lines)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Error: %s", mapped, exc_info=True)
            self.root.after(
                0,
                messagebox.showerror,
                "Error",
                f"Could not write log file:\n{user_message_for(mapped)}",
            )

        self.root.after(
            0,
            self._render_completion_ui,
            is_dry_run,
            total,
            updated,
            skipped,
            no_genre,
            errors,
            duration_secs,
        )

        if self.auto_end:
            log_lines.append("\n[Auto End enabled - closing in 2 seconds...]\n")
            try:
                with open(self._log_path, "w", encoding="utf-8") as f:
                    f.writelines(log_lines)
            except Exception as _exc:  # noqa: BLE001 - log rewrite before close
                logger.warning("Swallowed exception: %s", _exc, exc_info=True)
            self.root.after(2000, self.root.destroy)

    def _render_completion_ui(
        self,
        is_dry_run: bool,
        total: int,
        updated: int,
        skipped: int,
        no_genre: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Render the finished run (must run on the main thread)."""
        self.summary_label.config(
            text=f"Total: {total} files\n"
            f"Updated: {updated}\n"
            f"Skipped (already correct): {skipped}\n"
            f"No genre fields: {no_genre}\n"
            f"Errors: {errors}"
        )
        # This window has always labelled a finished run by its mode; the shell
        # renders ``completion_text``, so point it at this run's wording first.
        self.completion_text = (
            "Analysis Complete!" if is_dry_run else "Genre Update Complete!"
        )
        self.render_completion(duration_secs=duration_secs, output_dir=self._dir_path)
