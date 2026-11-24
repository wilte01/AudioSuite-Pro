"""
app.py
ReplayGainAnalyzerApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

Changed in 1.4.0: the worker slot grid is sized from ``DEFAULT_MAX_WORKERS``
instead of a literal 4 (PLAN D56).

Changed in 1.4.1: ``_on_complete`` and ``_on_progress`` accept ``**_extra: Any``,
so a payload field the processor adds (D112) is ignored instead of aborting an
otherwise-finished run; ``tests/test_callback_payload_contract.py`` locks the
completion, progress and error seams.  ``_on_complete``'s ``skipped``, ``errors``,
``duration_secs`` and ``log_entries`` lost their defaults, so a payload that
omits a count raises with its name instead of printing ``Errors: 0`` and
``Time: 00:00`` from a run that never reported.

Changed in 2.9.0: the source-folder opener is the shared mixin helper (A1).
Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, the fourth window of
D8's wave 2), so the shell owns the Help bar and the Processing and Results
tabs; this tool keeps its Setup panel and its per-run completion wording. The
Processing tab's five-column results table became the shell's shared file list,
one line per file carrying the same LUFS, track gain, album gain and status.
The run's folder, mode, target and lossless-gain choice are snapshotted on the
main thread in ``start_processing``, so the worker and the completion never read
a Tk variable off the Tk thread.

Changed in 2.9.0: the run report's ``SUMMARY:`` footer is
``audio_suite_shared.run_report.summary_lines``, the one implementation
every window writes with (D36).
Changed in 2.9.0: the preset trio (select, save, delete) is the shell's,
so this window declares the settings a preset carries and keeps only that (D58).
"""

import argparse
import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox
from typing import Any, cast

from audio_suite_shared import suite_config
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_dataclasses import validate_target_lufs
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.run_report import summary_lines
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars

from .core import file_processor
from .ui import setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)
TOOL_ID = "replaygain_analyzer"


class ReplayGainAnalyzerApp(SuiteApp):
    """ReplayGain Analyzer application GUI."""

    title = "ReplayGain Analyzer & Tagger"
    window_key = "replaygain_analyzer_window"
    program_name = TOOL_ID
    #: Kept for the guide registry's scan; the shell reads ``guide_name``.
    HELP_GUIDE = "ReplayGain_Analyzer_User_Guide.docx"
    guide_name = HELP_GUIDE
    # The heading the Results tab opens with; a finished run sets its own.
    completion_text = "ReplayGain Analysis Complete!"
    # The counters this tool reports; a run overwrites the line from its ticks.
    processing_stats_text = "Processed: 0 | Errors: 0"

    #: The key these presets live under in the shared store.
    TOOL_ID = TOOL_ID
    #: The settings a preset carries, in the order it has always stored them.
    PRESET_FIELDS = ("target_lufs", "run_mode")

    def __init__(self, root: tk.Tk) -> None:
        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.target_lufs = tk.StringVar(value="-16.0")
        self.run_mode = tk.StringVar(value="Dry Run")
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self.apply_lossless_gain_var = tk.BooleanVar(value=False)

        # Master Driver handshake: any CLI argument means driver-launched,
        # in which case the Run Controls panel is locked to inherited values.
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # ── State ─────────────────────────────────────────────────────────────
        self._log_path: str = ""
        self.auto_end: bool = False
        # The run's inputs, snapshotted by start_processing on the Tk thread.
        self._run_path: str = ""
        self._run_mode: str = ""
        self._run_target_lufs: float = 0.0
        self._run_apply_lossless_gain: bool = False

        # ── Worker slot pool ──────────────────────────────────────────────────
        # Built before super().__init__: the shell renders the grid from it.
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        super().__init__(root)

        # ── Apply CLI arguments ───────────────────────────────────────────────
        self._apply_cli_args()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Shell tabs ────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the run controls, the LUFS target and the presets into *parent*."""
        widgets = setup_tab.build(
            parent,
            folder_path=self.folder_path,
            target_lufs=self.target_lufs,
            run_mode=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            apply_lossless_gain_var=self.apply_lossless_gain_var,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
            presets=suite_config.list_presets(TOOL_ID),
            on_preset_selected=self.use_preset,
            on_save_preset=self.store_preset,
            on_delete_preset=self.remove_preset,
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
        self.apply_lossless_gain_var.set(parsed.apply_lossless_gain)

        if not parsed.folder_path:
            return

        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            cast(argparse.Namespace, parsed),
            folder_var=self.folder_path,
            auto_start_func=self.start_processing,
        )
        # target_lufs and auto_end are applied generically by
        # UniversalCLIHandler.apply_cli_args() above (it detects the
        # folder_path pattern and matches attributes on self by name).

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        """Browse for folder with enhanced error handling."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _open_folder(self) -> None:
        """Open the source folder since ReplayGain Analyzer processes files in-place."""
        self._open_source_folder_standard()

    def start_processing(self) -> None:
        """Start processing with validation and error handling."""
        try:
            folder = self.folder_path.get().strip()

            if not folder:
                messagebox.showerror(
                    "No Directory Selected",
                    "Please select a music directory containing audio files.",
                )
                return

            if not os.path.exists(folder):
                messagebox.showerror(
                    "Directory Not Found",
                    f"The selected directory does not exist:\n{folder}",
                )
                return

            if not os.path.isdir(folder):
                messagebox.showerror(
                    "Invalid Directory",
                    f"The selected path is not a valid directory:\n{folder}",
                )
                return

            has_audio = any(
                f.lower().endswith(SUPPORTED_EXTENSIONS) for f in os.listdir(folder)
            )

            if not has_audio:
                messagebox.showerror(
                    "No Audio Files",
                    f"No supported audio files found in:\n{folder}\n\n"
                    "Supported formats: MP3, FLAC, OGG, M4A, Opus, WAV, AIFF",
                )
                return

            try:
                lufs_val = float(self.target_lufs.get())
                lufs_errors = validate_target_lufs(lufs_val)
                if lufs_errors:
                    messagebox.showerror("Invalid LUFS Target", lufs_errors[0])
                    return
            except (ValueError, TypeError) as exc:
                messagebox.showerror("Invalid LUFS Value", f"Invalid LUFS value: {exc}")
                return

            self.start_btn.config(state="disabled")
            self.file_listbox.delete(0, tk.END)
            self.progress["value"] = 0
            self.stats_label.config(text=self.processing_stats_text)
            self.notebook.select(self.processing_frame)
            self.overall_status.set("Analyzing ReplayGain values...")

            # Snapshot the run's inputs on the main thread: the worker and the
            # completion must never call .get() off the Tk thread (see _run).
            self._run_path = folder
            self._run_mode = self.run_mode.get()
            self._run_target_lufs = lufs_val
            self._run_apply_lossless_gain = self.apply_lossless_gain_var.get()

            threading.Thread(target=self._run, daemon=True).start()

        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Processing Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Processing Error",
                f"Failed to start processing:\n{user_message_for(mapped)}",
            )

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="replaygain_app_run")
    def _run(self) -> None:
        """Analyse the folder on a worker thread.

        Thread safety: this runs off the Tk main thread, so it must not touch
        a widget or call ``.get()`` on a Tk variable. The inputs are the
        snapshot ``start_processing`` took on the main thread, and every UI
        write goes through ``root.after(0, ...)``.
        """
        dir_path = self._run_path
        is_dry_run = self._run_mode == "Dry Run"
        target = self._run_target_lufs

        self._log_path = os.path.join(
            dir_path,
            "replaygain_dry_run_log.txt" if is_dry_run else "replaygain_sync_log.txt",
        )

        header: list[str] = [
            "REPLAYGAIN ANALYSIS REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Target LUFS Level: {target}\n",
            "=" * 60 + "\n",
        ]

        with active_batch(TOOL_ID, "tag_edit"):
            file_processor.run_analysis(
                dir_path=dir_path,
                target_lufs=target,
                is_dry_run=is_dry_run,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_folder_complete=self._on_folder_complete,
                on_complete=lambda **kw: self._on_complete(header=header, **kw),
                on_error=self._on_error,
                apply_lossless_gain=(not is_dry_run and self._run_apply_lossless_gain),
            )

    # ── Callbacks (called from background threads — all UI via root.after) ────

    def _on_progress(
        self, processed: int, total: int, errors: int, **_extra: Any
    ) -> None:
        """Progress seam: hand the widget writes to the Tk thread."""
        self.root.after(0, self._update_progress_ui, processed, total, errors)

    def _update_progress_ui(self, processed: int, total: int, errors: int) -> None:
        """Render one progress tick (must run on the main thread)."""
        # This processor publishes no per-file line; the bar and counters move.
        self._render_progress_standard(processed, total, None)
        self.stats_label.config(text=f"Processed: {processed} | Errors: {errors}")

    def _on_folder_complete(
        self,
        folder_path: str,
        files_data: list[Any],
        album_gain_str: str,
        album_peak_str: str,
        tag_results: list[Any],
        log_header: str,
    ) -> None:
        """Report one folder's per-file measurements (called off the Tk thread)."""
        for file_data, status, tg_str, tp_str in tag_results:
            line = (
                f"{file_data['name']} | LUFS {file_data['lufs']:.2f}"
                f" | Track {tg_str} | Album {album_gain_str} | {status}"
            )
            self.root.after(0, self._append_progress_line, line)

    def _on_complete(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        **_extra: Any,
    ) -> None:
        """Write the run report; every count is required, never defaulted.

        ``skipped`` is not rendered here, but it stays required because
        ``run_analysis`` sends it unconditionally: a count the handler would
        accept a stand-in for is a count the summary can print wrong.
        """
        # ``processed`` counts successes already; errors are counted apart from it.
        succeeded = processed

        summary: list[str] = summary_lines(
            total=total,
            tagged=succeeded,
            tagged_label="Successfully processed",
            skipped=skipped,
            skipped_label=None,
            errors=errors,
            duration_secs=duration_secs,
        )
        all_entries = header + log_entries + summary
        if self.auto_end:
            all_entries.append("\n[Auto End enabled - closing in 2 seconds...]\n")

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(all_entries)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Error writing log: %s", mapped, exc_info=True)

            def _show_log_error(m: str = user_message_for(mapped)) -> None:
                messagebox.showerror("Error", f"Could not write log file:\n{m}")

            self.root.after(0, _show_log_error)

        self.root.after(
            0,
            self._update_ui_on_complete,
            total,
            succeeded,
            errors,
            duration_secs,
        )

    def _update_ui_on_complete(
        self,
        total: int,
        succeeded: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Render the finished run (must run on the main thread)."""
        self.summary_label.config(
            text=f"Total: {total} files\n"
            f"Successfully processed: {succeeded}\n"
            f"Errors: {errors}"
        )
        # This window has always labelled a finished run by its mode; the shell
        # renders ``completion_text``, so point it at this run's wording first.
        self.completion_text = (
            "Analysis Complete!"
            if self._run_mode == "Dry Run"
            else "ReplayGain Tagging Complete!"
        )
        self.render_completion(duration_secs=duration_secs, output_dir=self._run_path)

        if self.auto_end:
            self.root.after(2000, self.root.destroy)
