"""
app.py
Main application window for Mood Analysis Batch Tagger.

Recursively walks a root directory and all subfolders, analysing the mood
from the audio signal of every supported audio file it finds, writing the
mood and confidence tags.  Follows the standard AudioSuite-Pro tool pattern.

Changed in 1.4.0: the saved worker default and slot grid resolve through
``default_max_workers()`` / ``DEFAULT_MAX_WORKERS`` (PLAN D56), and a typed
count above the grid is capped before it is persisted (D66); the notice is
logged instead of shown when the launch is unattended (D70).

Changed in 2.4.1: the local ``_ThreadSafeSlotVar`` clone is retired
behind ``audio_suite_shared.thread_safe_slot_var.make_safe_slot_vars``,
the helper four sibling tools already used (WP-3).

Changed in 2.4.3: the View Log button delegates to
``ui_helpers.open_log_file`` instead of carrying its own copy of the
open/no-log branch, so the button's target and wording are the suite's one
implementation (PLAN_2026-11-03_2.4.3_structure.md D-16, D-19).

Changed in 2.7.0: the blind-``except`` boundary is named for the BLE001 triage
(WP-7 of ``PLAN_2026-11-03_2.4.1_stop_the_drift.md``, section 10).

Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, the eighth window of
D8's wave 2), so the shell owns the Help bar and the Processing and Results
tabs and this tool keeps its Setup panel, its
``Folders/Tagged/Skipped/Errors`` counters and its completion heading.  The
poller keeps its queue, but its widget writes go to the shell's widgets, the
completion renders through ``render_completion``, and View Log is the shell's
report opener, so it opens the path the engine reports for the run.
Changed in 2.9.0: the preset trio (select, save, delete) is the shell's,
so this window declares the settings a preset carries and keeps only that (D58).
"""

from __future__ import annotations

import logging
import os
import threading
import time
import tkinter as tk
from queue import Empty, Queue
from typing import Any

from audio_suite_shared import platform_utils, suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS, default_max_workers
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_common import cap_typed_workers
from mood_analysis_batch_tagger.core import batch_analysis_engine
from mood_analysis_batch_tagger.ui import setup_tab
from mood_analysis_batch_tagger.utils import cli_args
from mood_analysis_batch_tagger.utils.config import load_run_mode, save_run_mode

logger = logging.getLogger(__name__)

_TOOL_TITLE = "Mood Analysis Batch Tagger"
TOOL_ID = "mood_analysis_batch_tagger"


def _saved_worker_count(saved: object) -> int:
    """Return the worker count to seed the saved-config field with.

    A missing or corrupt config value must fall back to the suite default
    (host-derived since D56), never to a fixed four (D66).
    """
    if isinstance(saved, int) and not isinstance(saved, bool) and saved >= 1:
        return saved
    return default_max_workers()


class MoodAnalysisBatchTaggerApp(SuiteApp):
    """Main application window for the Mood Analysis Batch Tagger tool."""

    title = _TOOL_TITLE
    window_key = "mood_analysis_batch_tagger_window"
    program_name = TOOL_ID
    #: Kept for the guide registry's scan; the shell reads ``guide_name``.
    HELP_GUIDE = "Mood_Analysis_Batch_Tagger_User_Guide.docx"
    guide_name = HELP_GUIDE
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = ("  Setup  ", "  Processing  ", "  Results  ")
    #: The heading the Results tab shows when a batch finishes.
    completion_text = "Batch Mood Analysis Complete!"
    #: This window counts folders, tagged files, skips and errors.
    processing_stats_text = "Folders: 0 | Tagged: 0 | Skipped: 0 | Errors: 0"

    #: Set from argv in ``__init__``. The class default keeps an
    #: ``object.__new__`` test shell on the interactive (warning) path.
    _launched_from_driver: bool = False

    #: The key these presets live under in the shared store.
    TOOL_ID = TOOL_ID
    #: The settings a preset carries, in the order it has always stored them.
    PRESET_FIELDS = (
        "root_path",
        "run_mode",
        "analysis_duration",
        "parallel_mode",
        "max_workers",
    )

    def __init__(self, root: tk.Tk) -> None:
        # ── Tk variables ──────────────────────────────────────────────────────
        saved_mode = load_run_mode()
        self.root_path: tk.StringVar = tk.StringVar(
            value=suite_config.load_last_directory()
        )
        self.run_mode: tk.StringVar = tk.StringVar(value=saved_mode)
        self.analysis_duration = tk.IntVar(value=90)

        saved_parallel = bool(
            suite_config.load_value("mood_analysis_batch_parallel_mode", False)
        )
        workers_saved = suite_config.load_value(
            "mood_analysis_batch_max_workers", default_max_workers()
        )
        saved_workers = _saved_worker_count(workers_saved)
        self.parallel_mode = tk.BooleanVar(value=saved_parallel)
        self.max_workers = tk.IntVar(value=saved_workers)

        self.auto_start_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.auto_end_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.clear_logs_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.parallel_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # ── Processing state ─────────────────────────────────────────────────

        self._queue: Queue[Any] = Queue()
        self._running: bool = False
        self._tagged_count: int = 0
        self._skipped_count: int = 0
        self._error_count: int = 0
        self._folder_count: int = 0
        # Set by ``_on_start``; the completion's elapsed time reads it.
        self._run_started: float = 0.0
        self.auto_end: bool = False

        # ── Worker slot pool ──────────────────────────────────────────────────
        # Built before super().__init__: the shell renders the grid from it.
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(root, self.slot_vars)

        super().__init__(root)
        self._apply_cli_args()
        self._on_duration_change()

    # ── Shell tabs ────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the root folder, the run settings, the presets and the start button."""
        widgets: dict[str, Any] = setup_tab.build(
            parent,
            root_path=self.root_path,
            run_mode=self.run_mode,
            analysis_duration=self.analysis_duration,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._on_browse,
            on_start=self._on_start,
            driver_locked=self._launched_from_driver,
            parallel_mode=self.parallel_mode,
            max_workers=self.max_workers,
            preset_names=suite_config.list_presets(TOOL_ID),
            on_save_preset=self.store_preset,
            on_delete_preset=self.remove_preset,
            on_preset_selected=self.use_preset,
        )
        self.start_btn = widgets["start_btn"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self.controls_panel = widgets["controls_panel"]

        self.analysis_duration.trace_add(
            "write",
            lambda *_: suite_config.save_value(
                "mood_analysis_batch_duration", self.analysis_duration.get()
            ),
        )
        self.parallel_mode.trace_add(
            "write",
            lambda *_: suite_config.save_value(
                "mood_analysis_batch_parallel_mode", self.parallel_mode.get()
            ),
        )
        self.max_workers.trace_add(
            "write",
            lambda *_: suite_config.save_value(
                "mood_analysis_batch_max_workers", self.max_workers.get()
            ),
        )

    def _on_duration_change(self) -> None:
        saved_duration = suite_config.load_value("mood_analysis_batch_duration", 90)
        if isinstance(saved_duration, int):
            self.analysis_duration.set(saved_duration)

    def _apply_cli_args(self) -> None:
        parsed = cli_args.parse()
        if not parsed.folder_path:
            return

        self.root_path.set(parsed.folder_path)
        self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)
        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        self.analysis_duration.set(parsed.analysis_duration)
        self.parallel_mode.set(parsed.parallel_mode)
        self.max_workers.set(parsed.max_workers)
        self.auto_end = parsed.auto_end

        if parsed.auto_start:
            self.root.after(1500, self._on_start)

    # ── User actions ──────────────────────────────────────────────────────────

    def _on_browse(self) -> None:
        self._browse_folder_standard(
            title="Select Root Music Directory",
            path_variable=self.root_path,
            save_last_dir=True,
        )

    def _on_start(self) -> None:
        """Validate the root, persist the settings, then launch the batch."""
        root = self.root_path.get().strip()
        if not root:
            platform_utils.messagebox.showwarning(
                _TOOL_TITLE, "Please select a root directory first."
            )
            return
        if not os.path.isdir(root):
            platform_utils.messagebox.showerror(
                _TOOL_TITLE, "The selected directory does not exist."
            )
            return

        try:
            save_run_mode(self.run_mode.get())
        # Changed in 2.4.1: BLE001 triage (WP-7 of
        # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
        except (OSError, ValueError, TypeError):
            platform_utils.messagebox.showwarning(
                _TOOL_TITLE,
                "Run-mode preference could not be saved; processing will continue.",
            )
        suite_config.save_last_directory(root)
        suite_config.save_value(
            "mood_analysis_batch_duration", self.analysis_duration.get()
        )
        suite_config.save_value(
            "mood_analysis_batch_parallel_mode", self.parallel_mode.get()
        )
        # The Workers field is free text. Cap it on the main thread, with a
        # warning, before the run is persisted, so the saved value matches what
        # actually runs and no worker gets an index past the grid (D66).
        workers = cap_typed_workers(
            self.max_workers,
            self._safe_slot_vars,
            unattended=self._launched_from_driver,
        )
        suite_config.save_value("mood_analysis_batch_max_workers", workers)

        self._tagged_count = 0
        self._skipped_count = 0
        self._error_count = 0
        self._folder_count = 0
        self._log_path = ""
        self._out_dir = root
        self._run_started = time.monotonic()
        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        self.overall_status.set("Scanning...")
        self.stats_label.config(text=self.processing_stats_text)
        self._reset_slot_vars()

        self._running = True
        self.start_btn.config(state="disabled")
        self.notebook.select(self.processing_frame)

        live: bool = self.run_mode.get() == "Live Update"
        duration: int = self.analysis_duration.get()
        parallel: bool = self.parallel_mode.get()
        workers = self.max_workers.get()

        def _run_worker() -> None:
            def _on_worker_status(slot: int, label: str) -> None:
                self._queue.put(("slot", slot, label))

            with active_batch(TOOL_ID, "tag_edit"):
                batch_analysis_engine.run_batch(
                    root=root,
                    out_queue=self._queue,
                    stop_event=threading.Event(),
                    live=live,
                    analysis_duration=duration,
                    parallel_mode=parallel,
                    max_workers=workers,
                    on_worker_status=_on_worker_status,
                )

        threading.Thread(target=_run_worker, daemon=True).start()
        self.root.after(100, self._poll_queue)

    def _reset_slot_vars(self) -> None:
        for var in self.slot_vars:
            var.set("IDLE")

    def _poll_queue(self) -> None:
        try:
            while True:
                msg = self._queue.get_nowait()
                kind = msg[0]

                if kind == "folder":
                    _, rel_folder, count, folder_total = msg
                    self._folder_count += 1
                    self.file_listbox.insert(
                        tk.END, f"\u25b6  {rel_folder}  ({count} files)"
                    )
                    self.file_listbox.see(tk.END)
                    self.overall_status.set(f"Scanning: {rel_folder}")
                    self._update_stats()

                elif kind == "slot":
                    _, slot_idx, label = msg
                    if 0 <= slot_idx < len(self.slot_vars):
                        self.slot_vars[slot_idx].set(label)

                elif kind == "progress":
                    _, current, total, filename = msg
                    pct = (current / total * 100) if total else 0
                    self.progress["value"] = pct
                    self.overall_status.set(f"Processing: {filename}")

                elif kind == "result":
                    _, filepath, filename, success, detail = msg
                    if success:
                        self._tagged_count += 1
                        entry = f"    OK   {filename}  ->  {detail}"
                    else:
                        self._skipped_count += 1
                        entry = f"    SKIP {filename}  --  {detail}"
                    self.file_listbox.insert(tk.END, entry)
                    self.file_listbox.see(tk.END)
                    self._update_stats()

                elif kind == "done":
                    _, tagged, skipped, errors, folders, log_path = msg
                    self._tagged_count = tagged
                    self._skipped_count = skipped
                    self._error_count = errors
                    self._folder_count = folders
                    self._log_path = log_path
                    self._on_done(tagged, skipped, errors, folders)
                    return

        except Empty:
            pass
        except Exception:  # noqa: BLE001 - poller must survive one bad read
            logger.warning(
                "Unexpected error while polling the batch queue",
                exc_info=True,
            )

        if self._running:
            self.root.after(100, self._poll_queue)

    def _update_stats(self) -> None:
        self.stats_label.config(
            text=(
                f"Folders: {self._folder_count} | "
                f"Tagged: {self._tagged_count} | "
                f"Skipped: {self._skipped_count} | "
                f"Errors: {self._error_count}"
            )
        )

    def _on_done(self, tagged: int, skipped: int, errors: int, folders: int) -> None:
        """Render the finished batch (must run on the main thread)."""
        self._running = False
        self.progress["value"] = 100
        self.overall_status.set("Complete.")
        self.summary_label.config(
            text=(
                f"Folders scanned: {folders}\n"
                f"Files analysed:  {tagged + skipped + errors}\n"
                f"Files tagged:    {tagged}\n"
                f"Files skipped:   {skipped}\n"
                f"Errors:          {errors}"
            )
        )
        logger.info(
            "Batch complete. Folders: %d, Tagged: %d, Skipped: %d, Errors: %d",
            folders,
            tagged,
            skipped,
            errors,
        )

        self.render_completion(
            duration_secs=time.monotonic() - self._run_started,
            output_dir=self._out_dir,
        )

        if self.auto_end_var.get() or self.auto_end:
            self.root.after(1500, self.root.destroy)
