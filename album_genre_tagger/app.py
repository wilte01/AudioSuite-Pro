"""
app.py
GenreConsolidatorApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

Changed in 1.4.1: ``_on_complete`` and ``_on_progress`` accept ``**_extra: Any``,
so a payload field the processor adds (D112) is ignored instead of aborting an
otherwise-finished run; ``tests/test_callback_payload_contract.py`` locks the
completion, progress and error seams.

Changed in 2.9.0: the source-folder opener is the shared mixin helper (A1).
Changed in 2.9.0: the progress tick is the shared mixin helper (C1).
Changed in 2.9.0: the window adopts ``SuiteApp`` (C1 stage 3, D50).  Its two
one-line tab delegates are gone and the shell builds the notebook, the
Processing and Results tabs and the report's View Log; the run's four callbacks
queue their payload for the shell's poller instead of marshalling with
``root.after``, and the coverage check's failure is a completion of its own that
leaves the run's report behind.

Changed in 2.9.0: the migration's three vestiges are cut - the processing list
keeps the ``PHASE 1`` header spelling the run report already wrote, the class
no longer declares an unused ``TOOL_ID``, and the run's queue is seeded only by
the shell (D51).
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from audio_suite_shared import suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.suite_app import SuiteApp

from .core import consolidator
from .ui import setup_tab
from .utils import cli_args
from .utils.cli_args import GenreTaggerArgs

TOOL_ID = "album_genre_tagger"

#: The report a run leaves in the folder it read; View Log opens it.
LOG_NAME = "AlbumGenre_Tagger_Log.txt"

#: The Processing tab's first list line, posted before the read phase runs.
PHASE1_HEADER = "=== PHASE 1: READING TITLEGENRE TAGS ==="

DRY_RUN = "Dry Run"
LIVE_UPDATE = "Live Update"


class GenreConsolidatorApp(SuiteApp):
    """Album Genre Tagger application window."""

    title = "Album Genre Tagger"
    window_key = "album_genre_tagger_window"
    program_name = TOOL_ID
    #: Kept for the guide registry's scan; the shell reads ``guide_name``.
    HELP_GUIDE = "AlbumGenre_Tagger_User_Guide.docx"
    guide_name = HELP_GUIDE
    #: Replaced per run: a dry run analyses, a live run consolidates.
    completion_text = "Analysis Complete!"
    processing_stats_text = "Processed: 0 | With Genre: 0 | Errors: 0"
    #: The consolidated genre string the Results tab shows under the summary.
    result_extra_labels = ("genre_label",)
    #: Built by the shell from ``result_extra_labels`` and published here.
    genre_label: tk.Label

    def __init__(
        self, root: tk.Tk, cli_args_parsed: GenreTaggerArgs | None = None
    ) -> None:
        """Build the window, its variables and its state.

        Args:
            root: The Tk root the launcher created.
            cli_args_parsed: Arguments the entry point already parsed, so the
                handshake is not read off ``sys.argv`` twice.
        """
        self._cli_args_parsed: GenreTaggerArgs | None = cli_args_parsed

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path: tk.StringVar = tk.StringVar()
        self.run_mode: tk.StringVar = tk.StringVar(value=DRY_RUN)
        self.min_coverage: tk.IntVar = tk.IntVar(value=50)
        self.auto_start_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.auto_end_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.clear_logs_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.parallel_var: tk.BooleanVar = tk.BooleanVar(value=False)

        # Master Driver handshake: any CLI argument means driver-launched,
        # in which case the Run Controls panel is locked to inherited values.
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # ── State ─────────────────────────────────────────────────────────────
        self._log_path: str = ""
        self._dir_path: str = ""
        # Snapshotted on the Tk thread by start_processing; the worker reads
        # these, never the Tk vars.
        self._is_dry_run: bool = True
        self._min_coverage: int = 50
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None
        super().__init__(root)

        self._apply_cli_args()

        if not self.folder_path.get():
            last: str = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Shell tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder, the coverage option and the presets."""
        widgets: dict[str, Any] = setup_tab.build(
            parent,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            min_coverage=self.min_coverage,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
            preset_names=suite_config.list_presets(TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
        )
        self.start_btn = widgets["start_btn"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self._preset_combo = widgets["preset_combo"]
        self.controls_panel = widgets["controls_panel"]

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "run_mode": self.run_mode.get(),
            "min_coverage": self.min_coverage.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])
        if "min_coverage" in settings:
            self.min_coverage.set(settings["min_coverage"])

    def _on_preset_selected(self, name: str) -> None:
        settings = suite_config.load_preset(TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        suite_config.save_preset(TOOL_ID, name, self._collect_settings())
        self._refresh_preset_list(suite_config.list_presets(TOOL_ID))

    def _delete_preset(self, name: str) -> None:
        suite_config.delete_preset(TOOL_ID, name)
        self._refresh_preset_list(suite_config.list_presets(TOOL_ID))

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        # Use pre-parsed args when supplied (e.g. from entry point) to avoid
        # parsing sys.argv a second time.
        parsed = (
            self._cli_args_parsed
            if self._cli_args_parsed is not None
            else cli_args.parse()
        )
        # Mirror the inherited driver arguments onto the Run Controls
        # panel before any early return so the display always reflects
        # exactly what the Master Driver passed.
        self.run_mode.set(LIVE_UPDATE if parsed.live_mode else DRY_RUN)
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        if not parsed.folder_path:
            return

        # UniversalCLIHandler applies folder_path, run_mode, auto_end, and
        # all app-specific args (including min_coverage) via
        # _apply_app_specific_args.
        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed, folder_var=self.folder_path
        )

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def start_processing(self) -> None:
        """Validate the inputs, snapshot them, then start the run."""
        folder = self.folder_path.get()
        if not folder:
            messagebox.showwarning("Warning", "Please select a music directory first.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Error", "Selected path is not a valid directory.")
            return
        coverage = self.min_coverage.get()
        if coverage < 0 or coverage > 100:
            messagebox.showerror(
                "Error", "Coverage percentage must be between 0 and 100."
            )
            return

        self.start_btn.config(state="disabled")
        self.file_listbox.delete(0, tk.END)
        self.notebook.select(self.processing_frame)
        self.overall_status.set("Processing genres...")
        self._reset_progress_ui()

        # Snapshot every Tk variable on the Tk thread: the worker must not
        # call .get() on a Tk var (see _run's thread-safety note).
        self._dir_path = folder
        self._is_dry_run = self.run_mode.get() == DRY_RUN
        self._min_coverage = coverage
        self._log_path = os.path.join(self._dir_path, LOG_NAME)

        self._start_worker(self._run, ())

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="genre_tagger_app_run")
    def _run(self) -> None:
        """Process the directory on the worker thread the shell started.

        Thread safety: this runs off the Tk thread, so it must not touch a
        widget or call ``.get()`` on a Tk variable.  The inputs
        (``_dir_path``, ``_is_dry_run``, ``_min_coverage``) and the log path
        are snapshotted by ``start_processing``, and every callback below
        queues its payload for the shell's poller instead of writing a widget.
        """
        with active_batch("album_genre_tagger", "tag_edit"):
            consolidator.run_analysis(
                dir_path=self._dir_path,
                is_dry_run=self._is_dry_run,
                min_coverage=self._min_coverage,
                on_phase1_progress=self._on_phase1_progress,
                on_coverage_fail=self._on_coverage_fail,
                on_phase2_progress=self._on_phase2_progress,
                on_complete=self._on_complete,
                on_error=self._on_error,
            )

    # ── Callbacks (worker thread: queue only, no widget writes) ──────────────

    def _on_phase1_progress(
        self,
        processed: int,
        total: int,
        files_with_genre: int,
        errors: int,
        display_text: str,
        log_text: str,
        **_extra: Any,
    ) -> None:
        """Queue one read-phase tick for the Tk poller."""
        self._ui_updates.put(
            ("phase1", processed, total, files_with_genre, errors, display_text)
        )

    def _on_phase2_progress(
        self, display_text: str, log_text: str, **_extra: Any
    ) -> None:
        """Queue one write-phase line for the Tk poller."""
        self._ui_updates.put(("phase2", display_text))

    def _on_coverage_fail(
        self,
        total: int,
        files_with_genre: int,
        coverage_pct: float,
        min_coverage: int,
        duration_secs: float,
        log_entries: list[Any],
    ) -> None:
        """Write the run's report, then queue the failure completion.

        The coverage check failing ends the run the same way a finished
        consolidation does: the report is on disk before the window says why.
        """
        self._write_log(log_entries)
        self._ui_updates.put(
            (
                "coverage_fail",
                total,
                files_with_genre,
                coverage_pct,
                min_coverage,
                duration_secs,
            )
        )

    def _on_complete(
        self,
        total: int,
        files_with_genre: int,
        coverage_pct: float,
        unique_genres: list[Any],
        album_genre_string: str,
        write_count: int,
        write_errors: int,
        read_errors: int,
        duration_secs: float,
        log_entries: list[Any],
        **_extra: Any,
    ) -> None:
        """Write the run's report, then queue the finished run.

        The ten declared fields are required, so a payload that drops one
        raises with its name before any report is written.
        """
        self._write_log(log_entries)
        self._ui_updates.put(
            (
                "complete",
                total,
                files_with_genre,
                coverage_pct,
                unique_genres,
                album_genre_string,
                write_count,
                write_errors,
                read_errors,
                duration_secs,
            )
        )

    def _on_error(self, message: str) -> None:
        """Queue a fatal run error for the Tk poller's dialog."""
        self._ui_updates.put(("error", message))

    # ── Rendering (Tk thread: one queued message at a time) ──────────────────

    def _dispatch_ui_message(self, message: tuple[Any, ...]) -> None:
        """Render one queued message on the Tk thread."""
        kind = message[0]
        if kind == "phase1":
            _, processed, total, files_with_genre, errors, display_text = message
            # +1 reserves the bar's last step for the write phase.
            self._render_progress_standard(processed, total + 1, display_text)
            self.stats_label.config(
                text=f"Processed: {processed} | With Genre: {files_with_genre}"
                f" | Errors: {errors}"
            )
        elif kind == "phase2":
            self._append_progress_line(message[1])
        elif kind == "coverage_fail":
            _, total, files_with_genre, coverage_pct, min_coverage, duration_secs = (
                message
            )
            self._render_coverage_fail(
                total, files_with_genre, coverage_pct, min_coverage, duration_secs
            )
        elif kind == "complete":
            (
                _,
                total,
                files_with_genre,
                coverage_pct,
                unique_genres,
                album_genre_string,
                write_count,
                write_errors,
                read_errors,
                duration_secs,
            ) = message
            self._render_complete(
                total,
                files_with_genre,
                coverage_pct,
                unique_genres,
                album_genre_string,
                write_count,
                write_errors,
                read_errors,
                duration_secs,
            )
        elif kind == "error":
            super()._on_error(message[1])
        elif kind == "log_error":
            messagebox.showerror("Error", message[1])

    def _render_coverage_fail(
        self,
        total: int,
        files_with_genre: int,
        coverage_pct: float,
        min_coverage: int,
        duration_secs: float,
    ) -> None:
        """Show why the run stopped short (Tk thread only)."""
        self.summary_label.config(
            text=f"Total: {total} files\n"
            f"With TITLEGENRE: {files_with_genre} ({coverage_pct:.1f}%)\n"
            f"Required: {min_coverage}%\n\n"
            f"Status: FAILED - Insufficient coverage"
        )
        self.genre_label.config(text="")
        self.progress["value"] = total + 1
        self.completion_text = "Coverage Check Failed!"
        self.render_completion(duration_secs=duration_secs, output_dir=self._dir_path)
        self._schedule_auto_end()

    def _render_complete(
        self,
        total: int,
        files_with_genre: int,
        coverage_pct: float,
        unique_genres: list[Any],
        album_genre_string: str,
        write_count: int,
        write_errors: int,
        read_errors: int,
        duration_secs: float,
    ) -> None:
        """Show the finished run's summary (Tk thread only)."""
        # Read the snapshotted mode, not the Tk var: this runs after the run
        # began, and the snapshot is what the run itself used.
        is_dry_run = self._is_dry_run
        self.progress["value"] = total + 1
        self.summary_label.config(
            text=f"Total: {total} files\n"
            f"With TITLEGENRE: {files_with_genre} ({coverage_pct:.1f}%)\n"
            f"Unique genres found: {len(unique_genres)}\n"
            f"Files {'would be ' if is_dry_run else ''}updated:"
            f" {write_count}\n"
            f"Errors: {read_errors + write_errors}"
        )
        self.genre_label.config(text=f"Consolidated ALBUMGENRE:\n{album_genre_string}")
        self.completion_text = (
            "Analysis Complete!" if is_dry_run else "Genre Consolidation Complete!"
        )
        self.render_completion(duration_secs=duration_secs, output_dir=self._dir_path)
        self._schedule_auto_end()

    def _schedule_auto_end(self) -> None:
        """Close the window when the driver asked it to (Tk thread only)."""
        if self.auto_end_var.get():
            self.overall_status.set("Auto End enabled - closing in 2 seconds...")
            self.root.after(2000, self.root.destroy)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _reset_progress_ui(self) -> None:
        """Zero the progress bar and open the log list with the phase-1 header."""
        self.progress["value"] = 0
        self.file_listbox.insert(tk.END, PHASE1_HEADER)

    def _write_log(self, log_entries: list[Any]) -> None:
        """Serialise the run's entries into ``_log_path``.

        Called from the run's completion handlers, so a failed write is queued
        for the Tk poller's dialog rather than raised off the worker thread.
        """
        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(log_entries)
        # Changed in 2.4.1: BLE001 triage (WP-7 of
        # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
        # BLE001 boundary: the log file is best effort, results stand
        except Exception as exc:  # noqa: BLE001
            mapped = map_to_audio_error(exc)
            self.error_logger.log_error(
                type(exc).__name__, f"Error: {mapped}", include_traceback=True
            )
            self._ui_updates.put(
                ("log_error", f"Could not write log file:\n{user_message_for(mapped)}")
            )
