"""
analysis_app_base.py - Shared GUI scaffold for the in-place analysis tools.

``key_detector`` and ``mood_analyzer`` are the same Tk application: the same
bootstrap, the same driver-mirrored run controls, the same Setup / Processing /
Results notebook, the same folder picker, the same log and help buttons, the
same start/stop wiring, the same slot pool and the same report writer.  The
only thing that differs is the analysis the middle calls, plus a handful of
per-tool strings (window title, config-key prefix, report wording).

That application now lives here exactly once.  A tool subclasses
``AnalysisAppBase``, declares its literals as class attributes, hands over its
own ``ui`` tab modules and CLI-argument module, and overrides
``_run_analysis`` with the single call that actually differs.

The one thing a subclass cannot inherit is the ``handle_audio_errors`` context
string on ``_run``: the decorator bakes its argument in at definition time, so
each tool keeps its own two-line ``_run`` that delegates to ``_run_batch``.
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, ClassVar

from . import platform_utils, styles
from . import suite_config as _suite_config
from .app_bootstrap import bootstrap_tool_app
from .batch_undo import active_batch
from .exceptions import map_to_audio_error
from .thread_safe_slot_var import ThreadSafeSlotVar
from .ui_helpers import UIHelperMixin

logger = logging.getLogger(f"audio_suite.{__name__}")

WORKER_SLOT_COUNT = 4


class AnalysisAppBase(UIHelperMixin):
    """The shared application; a tool supplies the literals and the analysis.

    Every class attribute declared without a value here **must** be set by the
    subclass.  They are declared (rather than left undefined) so that
    ``mypy --strict`` catches a tool that forgets one at class-definition time
    instead of at first click.
    """

    # -- Identity ---------------------------------------------------------
    TOOL_ID: ClassVar[str]
    """Suite-internal tool id: window-geometry key, preset namespace, and the
    tool id handed to :func:`active_batch`."""

    APP_TITLE: ClassVar[str]
    """Human-readable window title passed to :func:`bootstrap_tool_app`."""

    WINDOW_NAME: ClassVar[str]
    """Named-window key used for geometry persistence."""

    HELP_GUIDE: ClassVar[str]
    """File name of the tool's generated ``.docx`` user guide."""

    SETTINGS_PREFIX: ClassVar[str]
    """Prefix for this tool's ``audio_suite_config.json`` keys, its log file
    stem, and its report/undo wording.  The two tools differ here only as
    ``key`` versus ``mood``."""

    # -- Per-tool wording -------------------------------------------------
    STARTING_STATUS: ClassVar[str]
    """Processing-tab status set the moment the batch is dispatched."""

    REPORT_HEADER: ClassVar[str]
    """First line of the generated report file (without the newline)."""

    SKIPPED_SUMMARY_LABEL: ClassVar[str]
    """How the report's skipped count is labelled.  The two tools legitimately
    disagree: Key Detector skips files that were already tagged, Mood Analyzer
    skips files it could not decode or found silent."""

    LIVE_COMPLETION_TEXT: ClassVar[str]
    """Results-tab completion label after a live (writing) run."""

    DRY_RUN_COMPLETION_TEXT: ClassVar[str] = "Analysis Complete!"
    """Results-tab completion label after a dry run.  Identical for both."""

    # -- Collaborators ----------------------------------------------------
    SETUP_TAB: ClassVar[Any]
    """This tool's ``ui.setup_tab`` module.  Typed ``Any`` because a module
    object has no expressible nominal type; the ``build()`` contract is
    enforced by the per-tool ``ui`` package and its own tests."""

    PROCESSING_TAB: ClassVar[Any]
    """This tool's ``ui.processing_tab`` module (see ``SETUP_TAB``)."""

    RESULTS_TAB: ClassVar[Any]
    """This tool's ``ui.results_tab`` module (see ``SETUP_TAB``)."""

    CLI_ARGS: ClassVar[Any]
    """This tool's ``utils.cli_args`` module, providing ``parse()`` and
    ``was_launched_from_driver()``."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.error_logger, self.style = bootstrap_tool_app(
            self.root,
            self.APP_TITLE,
            self.WINDOW_NAME,
            self.TOOL_ID,
        )

        # -- Tk variables --------------------------------------------------
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")
        self.analysis_duration = tk.IntVar(value=90)
        saved_parallel = bool(
            _suite_config.load_value(self._setting_key("parallel_mode"), False)
        )
        workers_saved = _suite_config.load_value(self._setting_key("max_workers"), 4)
        saved_workers = workers_saved if isinstance(workers_saved, int) else 4
        self.parallel_mode = tk.BooleanVar(value=saved_parallel)
        self.max_workers = tk.IntVar(value=saved_workers)

        # Driver-mirrored run controls (Clear Logs / Parallel are display-only)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self._launched_from_driver = self.CLI_ARGS.was_launched_from_driver()

        # -- State --------------------------------------------------------
        self._log_path: str = ""
        self._dir_path: str = ""
        self.auto_end: bool = False
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # -- Worker slot pool ----------------------------------------------
        self.slot_vars = [tk.StringVar(value="IDLE") for _ in range(WORKER_SLOT_COUNT)]
        self._safe_slot_vars = [ThreadSafeSlotVar(self.root, v) for v in self.slot_vars]
        self.slot_queue: Queue[Any] = Queue()
        for i in range(WORKER_SLOT_COUNT):
            self.slot_queue.put(i)

        # -- Build UI -----------------------------------------------------
        self._build_ui()

        # -- Apply CLI arguments -------------------------------------------
        self._apply_cli_args()

        # -- Restore last-used directory (if not set by CLI) ----------------
        if not self.folder_path.get():
            last = _suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    def _setting_key(self, name: str) -> str:
        """Return this tool's ``audio_suite_config.json`` key for *name*."""
        return f"{self.SETTINGS_PREFIX}_{name}"

    # -- UI construction ---------------------------------------------------

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

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        tab_setup = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_processing = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_results = tk.Frame(self.notebook, bg=styles.BG_LIGHT)

        self.notebook.add(tab_setup, text=" 1. Setup ")
        self.notebook.add(tab_processing, text=" 2. Processing ")
        self.notebook.add(tab_results, text=" 3. Results ")

        widgets = self.SETUP_TAB.build(
            tab_setup,
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
            preset_names=_suite_config.list_presets(self.TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
        )
        self.start_btn: tk.Button = widgets["start_btn"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self._preset_combo = widgets["preset_combo"]

        proc_widgets = self.PROCESSING_TAB.build(tab_processing, self.slot_vars)
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]

        res_widgets = self.RESULTS_TAB.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]
        self.time_label: tk.Label = res_widgets["time_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]

        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # -- Presets -----------------------------------------------------------

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
        settings = _suite_config.load_preset(self.TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        _suite_config.save_preset(self.TOOL_ID, name, self._collect_settings())
        self._refresh_preset_list(_suite_config.list_presets(self.TOOL_ID))

    def _delete_preset(self, name: str) -> None:
        _suite_config.delete_preset(self.TOOL_ID, name)
        self._refresh_preset_list(_suite_config.list_presets(self.TOOL_ID))

    # -- CLI handling ------------------------------------------------------

    def _apply_cli_args(self) -> None:
        parsed = self.CLI_ARGS.parse()
        if not parsed.folder_path:
            return

        # Mirror the driver's run controls onto the Setup tab panel.
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

    # -- User actions ------------------------------------------------------

    def _browse_folder(self) -> None:
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _open_folder(self) -> None:
        """Open the source folder, since this tool processes files in-place."""
        folder_path = self.folder_path.get()
        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Source folder not available.")

    def _open_help(self) -> None:
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        self._open_log_standard()

    def start_processing(self) -> None:
        """Validate inputs and start the background analysis thread."""
        folder = self.folder_path.get()
        if not folder:
            messagebox.showwarning("Warning", "Please select a music directory first.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Error", "Selected path is not a valid directory.")
            return

        # Persist parallel processing settings
        _suite_config.save_value(
            self._setting_key("parallel_mode"), self.parallel_mode.get()
        )
        _suite_config.save_value(
            self._setting_key("max_workers"), self.max_workers.get()
        )

        self.start_btn.config(state="disabled")
        self.file_listbox.delete(0, tk.END)
        self.notebook.select(self._tab_processing)
        self.overall_status.set(self.STARTING_STATUS)

        threading.Thread(target=self._run, daemon=True).start()

    # -- Background thread --------------------------------------------------

    def _run(self) -> None:
        """Worker-thread entry point dispatched by :meth:`start_processing`.

        A subclass overrides this **only** to attach its own
        ``@handle_audio_errors`` context label, and then delegates straight to
        :meth:`_run_batch`.  Declared here so the dispatch site has a declared
        target and a subclass that forgets it fails loudly rather than at click
        time.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement _run()")

    def _run_analysis(self, run_kwargs: dict[str, Any]) -> None:
        """Invoke this tool's core analysis entry point.

        The single call that genuinely differs between the tools built on this
        scaffold, and therefore the only method a subclass has to override.

        Args:
            run_kwargs: Keyword arguments assembled by :meth:`_run_batch`.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _run_analysis()"
        )

    def _run_batch(self) -> None:
        """Set up the run, then hand off to this tool's analysis.

        Callers use the decorated ``_run`` on the subclass so the
        ``handle_audio_errors`` context names the tool.
        """
        dir_path = self.folder_path.get()
        is_dry_run = self.run_mode.get() == "Dry Run"
        duration = self.analysis_duration.get()
        parallel = self.parallel_mode.get()
        workers = self.max_workers.get()

        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            f"{self.SETTINGS_PREFIX}_dry_run_log.txt"
            if is_dry_run
            else f"{self.SETTINGS_PREFIX}_sync_log.txt",
        )
        self.progress["value"] = 0

        header = [
            f"{self.REPORT_HEADER}\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Analysis Duration: {duration} seconds\n",
            f"Parallel: {'Yes' if parallel else 'No'}\n",
            f"Workers: {workers}\n",
            "=" * 60 + "\n",
        ]

        with active_batch(self.TOOL_ID, "tag_edit"):
            self._run_analysis(
                {
                    "dir_path": dir_path,
                    "is_dry_run": is_dry_run,
                    "analysis_duration": duration,
                    "slot_vars": self._safe_slot_vars,
                    "slot_queue": self.slot_queue,
                    "on_progress": self._on_progress,
                    "on_complete": lambda **kw: self._on_complete(header=header, **kw),
                    "on_error": self._on_error,
                    "parallel_mode": parallel,
                    "max_workers": workers,
                }
            )

    # -- Callbacks ----------------------------------------------------------

    def _on_progress(
        self, processed: int, total: int, skipped: int, errors: int, display_text: str
    ) -> None:
        """Called from worker threads - schedule UI update on main thread."""
        self.root.after(
            0, self._update_progress_ui, processed, total, skipped, errors, display_text
        )

    def _update_progress_ui(
        self, processed: int, total: int, skipped: int, errors: int, display_text: str
    ) -> None:
        """Update progress UI elements (must run on main thread)."""
        self.progress["maximum"] = total
        self.progress["value"] = processed
        self.stats_label.config(
            text=f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}"
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

    def _on_complete(
        self,
        header: list[Any],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[Any],
    ) -> None:
        """Called on background thread - file I/O here, then schedule UI on
        main thread."""
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        analysed = processed - skipped - errors

        summary = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"Tagged/Analyzed: {analysed}\n",
            f"{self.SKIPPED_SUMMARY_LABEL}: {skipped}\n",
            f"Errors: {errors}\n",
            f"Time: {minutes:02d}:{seconds:02d}\n",
        ]
        all_entries = header + log_entries + summary

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(all_entries)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Error writing log: %s", mapped, exc_info=True)

        self.root.after(
            0,
            self._update_ui_on_complete,
            total,
            analysed,
            skipped,
            errors,
            minutes,
            seconds,
        )

        # Auto End is honoured from *either* source: the driver-issued CLI
        # bool, or the Setup-tab checkbox, which is editable on a standalone
        # launch.  Consulting only the bool left the checkbox inert there.
        if self.auto_end_var.get() or self.auto_end:
            all_entries.append("\n[Auto End enabled - closing in 2 seconds...]\n")
            try:
                with open(self._log_path, "w", encoding="utf-8") as f:
                    f.writelines(all_entries)
            except Exception as exc:
                logger.warning(
                    "Could not append auto-end marker: %s", exc, exc_info=True
                )
            self.root.after(2000, self.root.destroy)

    def _update_ui_on_complete(
        self,
        total: int,
        analysed: int,
        skipped: int,
        errors: int,
        minutes: int,
        seconds: int,
    ) -> None:
        """Update UI after analysis completes (must run on main thread)."""
        is_dry_run = self.run_mode.get() == "Dry Run"
        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=(
                f"Total: {total} files\n"
                f"Tagged/Analyzed: {analysed}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        )
        self.completion_label.config(
            text=self.DRY_RUN_COMPLETION_TEXT
            if is_dry_run
            else self.LIVE_COMPLETION_TEXT
        )
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

    def _on_error(self, message: str) -> None:
        """Called from worker threads - schedule error dialog on main thread."""
        self.root.after(0, self._show_error, message)

    def _show_error(self, message: str) -> None:
        """Show error dialog (must run on main thread)."""
        messagebox.showerror("Error", message)
        self.start_btn.config(state="normal")
