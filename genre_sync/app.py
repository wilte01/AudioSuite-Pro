"""
app.py
GenreSetterApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.
"""

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any

from audio_suite_shared import platform_utils, styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core import file_processor, log_builder
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "genre_sync"


class GenreSetterApp(UIHelperMixin):
    """Genre Sync application GUI."""

    HELP_GUIDE = "Genre_Sync_User_Guide.docx"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Genre Sync",
            "genre_sync_window",
            "genre_sync",
        )

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
        self._log_path: str = ""
        self._dir_path: str = ""
        self.auto_end: bool = False
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Worker slot pool ──────────────────────────────────────────────────
        self.slot_vars = [tk.StringVar(value="IDLE") for _ in range(4)]
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(4):
            self.slot_queue.put(i)

        # ── Build UI ──────────────────────────────────────────────────────────
        self._build_ui()

        # ── Apply CLI arguments ───────────────────────────────────────────────
        self._apply_cli_args()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── UI construction ───────────────────────────────────────────────────────

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

        setup_widgets = setup_tab.build(
            tab_setup,
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
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
        )
        self.start_btn = setup_widgets["start_btn"]
        self._refresh_preset_list = setup_widgets["refresh_preset_list"]
        self._preset_combo = setup_widgets["preset_combo"]

        proc_widgets = processing_tab.build(tab_processing, self.slot_vars)
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]

        res_widgets = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]
        self.time_label: tk.Label = res_widgets["time_label"]

        self._tab_setup = tab_setup
        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])

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
        folder_path = self.folder_path.get()
        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Source folder not available.")

    def _open_help(self) -> None:
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        self._open_log_standard()

    def _reset_ui(self) -> None:
        self.notebook.select(self._tab_setup)
        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        self.stats_label.config(
            text="Processed: 0 | Updated: 0 | Skipped: 0 | Errors: 0"
        )

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
        self.notebook.select(self._tab_processing)
        self.overall_status.set("Processing genre fields...")

        threading.Thread(target=self._run, daemon=True).start()

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="genre_sync_app_run")
    def _run(self) -> None:
        dir_path = self.folder_path.get()
        is_dry_run = self.run_mode.get() == "Dry Run"
        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            "genre_dry_run_log.txt" if is_dry_run else "genre_sync_log.txt",
        )
        self.progress["value"] = 0

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
    ) -> None:
        self.progress["maximum"] = total
        self.progress["value"] = processed
        self.stats_label.config(
            text=f"Processed: {processed} | Updated: {updated}"
            f" | Skipped: {skipped} | Errors: {errors}"
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

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
        is_dry_run = self.run_mode.get() == "Dry Run"
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)

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
            messagebox.showerror(
                "Error",
                f"Could not write log file:\n{user_message_for(mapped)}",
            )

        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=f"Total: {total} files\n"
            f"Updated: {updated}\n"
            f"Skipped (already correct): {skipped}\n"
            f"No genre fields: {no_genre}\n"
            f"Errors: {errors}"
        )
        self.completion_label.config(
            text="Analysis Complete!" if is_dry_run else "Genre Update Complete!"
        )
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

        if self.auto_end:
            log_lines.append("\n[Auto End enabled - closing in 2 seconds...]\n")
            try:
                with open(self._log_path, "w", encoding="utf-8") as f:
                    f.writelines(log_lines)
            except Exception as _exc:
                logger.warning("Swallowed exception: %s", _exc, exc_info=True)
            self.root.update_idletasks()
            self.root.after(2000, self.root.destroy)

    def _on_error(self, message: str) -> None:
        messagebox.showerror("Error", message)
        self.start_btn.config(state="normal")
