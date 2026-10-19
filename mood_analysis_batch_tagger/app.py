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
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from queue import Empty, Queue
from tkinter import ttk
from typing import Any

from audio_suite_shared import platform_utils, styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS, default_max_workers
from audio_suite_shared.ui_common import cap_typed_workers
from audio_suite_shared.ui_helpers import UIHelperMixin
from mood_analysis_batch_tagger.core import batch_analysis_engine
from mood_analysis_batch_tagger.ui import processing_tab, results_tab, setup_tab
from mood_analysis_batch_tagger.utils import cli_args
from mood_analysis_batch_tagger.utils.config import load_run_mode, save_run_mode

logger = logging.getLogger(__name__)

_TOOL_TITLE = "Mood Analysis Batch Tagger"
TOOL_ID = "mood_analysis_batch_tagger"


class _ThreadSafeSlotVar:
    """Wrap a tk.StringVar so that .set() is always scheduled on the main thread."""

    def __init__(self, root: tk.Tk, var: tk.StringVar) -> None:
        self._root = root
        self._var = var

    def set(self, value: str) -> None:
        self._root.after(0, self._var.set, value)

    def get(self) -> str:
        return self._var.get()


def _saved_worker_count(saved: object) -> int:
    """Return the worker count to seed the saved-config field with.

    A missing or corrupt config value must fall back to the suite default
    (host-derived since D56), never to a fixed four (D66).
    """
    if isinstance(saved, int) and not isinstance(saved, bool) and saved >= 1:
        return saved
    return default_max_workers()


class MoodAnalysisBatchTaggerApp(UIHelperMixin):
    """Main application window for the Mood Analysis Batch Tagger tool."""

    HELP_GUIDE = "Mood_Analysis_Batch_Tagger_User_Guide.docx"

    #: Set from argv in ``__init__``. The class default keeps an
    #: ``object.__new__`` test shell on the interactive (warning) path.
    _launched_from_driver: bool = False

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            _TOOL_TITLE,
            "mood_analysis_batch_tagger_window",
            "mood_analysis_batch_tagger",
        )

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

        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        self._queue: Queue[Any] = Queue()
        self._running: bool = False
        self._tagged_count: int = 0
        self._skipped_count: int = 0
        self._error_count: int = 0
        self._folder_count: int = 0
        self._log_path: str = ""
        self.auto_end: bool = False

        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = [
            _ThreadSafeSlotVar(self.root, v) for v in self.slot_vars
        ]

        self._build_ui()
        self._apply_cli_args()
        self._on_duration_change()

    def _build_ui(self) -> None:
        help_frame = tk.Frame(self.root, bg=styles.BG_LIGHT)
        help_frame.pack(fill="x", padx=10, pady=(10, 0))
        tk.Button(
            help_frame,
            text="Help",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BODY,
            padx=15,
            pady=3,
            command=self._open_help,
        ).pack(side=tk.RIGHT)

        nb = ttk.Notebook(self.root)
        nb.pack(expand=True, fill="both", padx=10, pady=10)
        self._notebook = nb

        setup_frame = tk.Frame(nb, bg=styles.BG_WHITE)
        processing_frame = tk.Frame(nb, bg=styles.BG_WHITE)
        results_frame = tk.Frame(nb, bg=styles.BG_WHITE)

        nb.add(setup_frame, text="  Setup  ")
        nb.add(processing_frame, text="  Processing  ")
        nb.add(results_frame, text="  Results  ")

        widgets = setup_tab.build(
            setup_frame,
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
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
        )
        self._start_btn: tk.Button = widgets["start_btn"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self._preset_combo = widgets["preset_combo"]
        self._controls_panel = widgets["controls_panel"]

        self._proc = processing_tab.build(processing_frame, slot_vars=self.slot_vars)

        self._res = results_tab.build(
            results_frame,
            on_open_log=self._on_open_log,
            on_open_folder=self._on_open_folder,
        )

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

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "root_path": self.root_path.get(),
            "run_mode": self.run_mode.get(),
            "analysis_duration": self.analysis_duration.get(),
            "parallel_mode": self.parallel_mode.get(),
            "max_workers": self.max_workers.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "root_path" in settings:
            self.root_path.set(settings["root_path"])
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])
        if "analysis_duration" in settings:
            self.analysis_duration.set(settings["analysis_duration"])
        if "parallel_mode" in settings:
            self.parallel_mode.set(settings["parallel_mode"])
        if "max_workers" in settings:
            self.max_workers.set(settings["max_workers"])

    def _on_preset_selected(self, name: str) -> None:
        settings = suite_config.load_preset(TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        suite_config.save_preset(TOOL_ID, name, self._collect_settings())
        if self._refresh_preset_list:
            self._refresh_preset_list(suite_config.list_presets(TOOL_ID))

    def _delete_preset(self, name: str) -> None:
        suite_config.delete_preset(TOOL_ID, name)
        if self._refresh_preset_list:
            self._refresh_preset_list(suite_config.list_presets(TOOL_ID))

    def _open_help(self) -> None:
        self._open_help_standard(self.HELP_GUIDE)

    def _on_browse(self) -> None:
        self._browse_folder_standard(
            title="Select Root Music Directory",
            path_variable=self.root_path,
            save_last_dir=True,
        )

    def _on_start(self) -> None:
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
            save_run_mode("", self.run_mode.get())
        except Exception:
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
        self._proc["file_listbox"].delete(0, tk.END)
        self._proc["progress"]["value"] = 0
        self._proc["overall_status"].set("Scanning...")
        self._proc["stats_label"].config(
            text="Folders: 0 | Tagged: 0 | Skipped: 0 | Errors: 0"
        )
        self._reset_slot_vars()

        self._running = True
        self._start_btn.config(state="disabled")
        self._notebook.select(1)

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
                    self._proc["file_listbox"].insert(
                        tk.END, f"\u25b6  {rel_folder}  ({count} files)"
                    )
                    self._proc["file_listbox"].see(tk.END)
                    self._proc["overall_status"].set(f"Scanning: {rel_folder}")
                    self._update_stats()

                elif kind == "slot":
                    _, slot_idx, label = msg
                    if 0 <= slot_idx < len(self.slot_vars):
                        self.slot_vars[slot_idx].set(label)

                elif kind == "progress":
                    _, current, total, filename = msg
                    pct = (current / total * 100) if total else 0
                    self._proc["progress"]["value"] = pct
                    self._proc["overall_status"].set(f"Processing: {filename}")

                elif kind == "result":
                    _, filepath, filename, success, detail = msg
                    if success:
                        self._tagged_count += 1
                        entry = f"    OK   {filename}  ->  {detail}"
                    else:
                        self._skipped_count += 1
                        entry = f"    SKIP {filename}  --  {detail}"
                    self._proc["file_listbox"].insert(tk.END, entry)
                    self._proc["file_listbox"].see(tk.END)
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
        except Exception:
            logger.warning(
                "Unexpected error while polling the batch queue",
                exc_info=True,
            )

        if self._running:
            self.root.after(100, self._poll_queue)

    def _update_stats(self) -> None:
        self._proc["stats_label"].config(
            text=(
                f"Folders: {self._folder_count} | "
                f"Tagged: {self._tagged_count} | "
                f"Skipped: {self._skipped_count} | "
                f"Errors: {self._error_count}"
            )
        )

    def _on_done(self, tagged: int, skipped: int, errors: int, folders: int) -> None:
        self._running = False
        self._start_btn.config(state="normal")
        self._proc["progress"]["value"] = 100
        self._proc["overall_status"].set("Complete.")
        self._res["summary_label"].config(
            text=(
                f"Folders scanned: {folders}\n"
                f"Files analysed:  {tagged + skipped + errors}\n"
                f"Files tagged:    {tagged}\n"
                f"Files skipped:   {skipped}\n"
                f"Errors:          {errors}"
            )
        )
        self._res["completion_label"].config(text="Batch Mood Analysis Complete!")
        self._notebook.select(2)
        logger.info(
            "Batch complete. Folders: %d, Tagged: %d, Skipped: %d, Errors: %d",
            folders,
            tagged,
            skipped,
            errors,
        )

        if self.auto_end_var.get() or self.auto_end:
            self.root.after(1500, self.root.destroy)

    def _on_open_log(self) -> None:
        if self._log_path and os.path.isfile(self._log_path):
            platform_utils.open_path(self._log_path)
        else:
            platform_utils.messagebox.showinfo(
                _TOOL_TITLE, "No log file available yet."
            )

    def _on_open_folder(self) -> None:
        root = self.root_path.get().strip()
        if root and os.path.isdir(root):
            platform_utils.open_path(root)
        else:
            platform_utils.messagebox.showinfo(_TOOL_TITLE, "No folder selected.")
