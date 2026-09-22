"""
app.py
GenreConsolidatorApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.
"""

import os
import threading
import tkinter as tk
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
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core import consolidator
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args
from .utils.cli_args import GenreTaggerArgs

TOOL_ID = "album_genre_tagger"


class GenreConsolidatorApp(UIHelperMixin):
    """Album Genre Tagger application GUI."""

    HELP_GUIDE = "AlbumGenre_Tagger_User_Guide.docx"

    def __init__(
        self, root: tk.Tk, cli_args_parsed: GenreTaggerArgs | None = None
    ) -> None:
        self.root = root
        # Pre-parsed args supplied by entry point to avoid a second parse.
        self._cli_args_parsed = cli_args_parsed

        self.error_logger, self.style = bootstrap_tool_app(
            self.root,
            "Album Genre Tagger",
            "album_genre_tagger_window",
            "album_genre_tagger",
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")
        self.min_coverage = tk.IntVar(value=50)
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
        # Help button above notebook
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

        # Three-tab notebook
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
        self.start_btn = setup_widgets["start_btn"]
        self._refresh_preset_list = setup_widgets["refresh_preset_list"]
        self._preset_combo = setup_widgets["preset_combo"]

        proc_widgets = processing_tab.build(tab_processing)
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
        self.time_label: tk.Label = res_widgets["time_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]
        self.genre_label: tk.Label = res_widgets["genre_label"]

        self._tab_processing = tab_processing
        self._tab_results = tab_results

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
        self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
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

    def _open_help(self) -> None:
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        self._open_log_standard()

    def _open_folder(self) -> None:
        """Open the source folder since Album Genre Tagger processes files in-place."""
        folder_path = self.folder_path.get()
        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Source folder not available.")

    def start_processing(self) -> None:
        """Start the album genre tagging process."""
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
        self.notebook.select(self._tab_processing)
        self.overall_status.set("Processing genres...")

        threading.Thread(target=self._run, daemon=True).start()

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="genre_tagger_app_run")
    def _run(self) -> None:
        dir_path = self.folder_path.get()
        is_dry_run = self.run_mode.get() == "Dry Run"
        self._dir_path = dir_path
        self._log_path = os.path.join(dir_path, "AlbumGenre_Tagger_Log.txt")

        self.progress["value"] = 0
        self.file_listbox.insert(tk.END, "=== PHASE 1: READING TITLEGENRE TAGS ===")

        with active_batch("album_genre_tagger", "tag_edit"):
            consolidator.run_analysis(
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                min_coverage=self.min_coverage.get(),
                on_phase1_progress=self._on_phase1_progress,
                on_coverage_fail=self._on_coverage_fail,
                on_phase2_progress=self._on_phase2_progress,
                on_complete=self._on_complete,
                on_error=self._on_error,
            )

    # ── Callbacks (called from background thread) ─────────────────────────────

    def _on_phase1_progress(
        self,
        processed: int,
        total: int,
        files_with_genre: int,
        errors: int,
        display_text: str,
        log_text: str,
    ) -> None:
        self.progress["maximum"] = total + 1  # +1 reserves space for write phase
        self.progress["value"] = processed
        self.stats_label.config(
            text=f"Processed: {processed} | With Genre: {files_with_genre}"
            f" | Errors: {errors}"
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)
        self.root.update_idletasks()

    def _on_coverage_fail(
        self,
        total: int,
        files_with_genre: int,
        coverage_pct: float,
        min_coverage: int,
        duration_secs: float,
        log_entries: list[Any],
    ) -> None:
        self._write_log(log_entries)
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)

        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=f"Total: {total} files\n"
            f"With TITLEGENRE: {files_with_genre} ({coverage_pct:.1f}%)\n"
            f"Required: {min_coverage}%\n\n"
            f"Status: FAILED - Insufficient coverage"
        )
        self.completion_label.config(text="Coverage Check Failed!")
        self.genre_label.config(text="")
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

        if self.auto_end:
            self.root.after(2000, self.root.destroy)

    def _on_phase2_progress(self, display_text: str, log_text: str) -> None:
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)
        self.root.update_idletasks()

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
    ) -> None:
        self._write_log(log_entries)
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        is_dry_run = self.run_mode.get() == "Dry Run"

        self.progress["value"] = total + 1
        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=f"Total: {total} files\n"
            f"With TITLEGENRE: {files_with_genre} ({coverage_pct:.1f}%)\n"
            f"Unique genres found: {len(unique_genres)}\n"
            f"Files {'would be ' if is_dry_run else ''}updated:"
            f" {write_count}\n"
            f"Errors: {read_errors + write_errors}"
        )
        self.genre_label.config(text=f"Consolidated ALBUMGENRE:\n{album_genre_string}")
        self.completion_label.config(
            text="Analysis Complete!" if is_dry_run else "Genre Consolidation Complete!"
        )
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

        if self.auto_end:
            log_entries.append("\n[Auto End enabled - closing in 2 seconds...]\n")
            self._write_log(log_entries)
            self.root.update_idletasks()
            self.root.after(2000, self.root.destroy)

    def _on_error(self, message: str) -> None:
        messagebox.showerror("Error", message)
        self.start_btn.config(state="normal")

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _write_log(self, log_entries: list[Any]) -> None:
        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(log_entries)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            self.error_logger.log_error(
                type(exc).__name__, f"Error: {mapped}", include_traceback=True
            )
            messagebox.showerror(
                "Error",
                f"Could not write log file:\n{user_message_for(mapped)}",
            )
