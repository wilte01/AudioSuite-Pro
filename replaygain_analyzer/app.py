"""
app.py
ReplayGainAnalyzerApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.
"""

import argparse
import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, cast

from audio_suite_shared import platform_utils, styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_dataclasses import validate_target_lufs
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core import file_processor
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)
TOOL_ID = "replaygain_analyzer"


class ReplayGainAnalyzerApp(UIHelperMixin):
    """ReplayGain Analyzer application GUI."""

    HELP_GUIDE = "ReplayGain_Analyzer_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "ReplayGain Analyzer & Tagger",
            "replaygain_analyzer_window",
            "replaygain_analyzer",
        )

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
        self._dir_path: str = ""
        self.auto_end: bool = False

        # ── Worker slot pool ──────────────────────────────────────────────────
        self.slot_vars = [tk.StringVar(value="IDLE") for _ in range(4)]
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(4):
            self.slot_queue.put(i)

        # ── Preset UI placeholders ────────────────────────────────────────────
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
            on_preset_selected=self._on_preset_selected,
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
        )
        self.start_btn = setup_widgets["start_btn"]
        self._preset_combo = setup_widgets["preset_combo"]
        self._refresh_preset_list = setup_widgets["refresh_preset_list"]

        proc_widgets = processing_tab.build(tab_processing, self.slot_vars)
        self.overall_status = cast(tk.StringVar, proc_widgets["overall_status"])
        self.progress = cast(ttk.Progressbar, proc_widgets["progress"])
        self.stats_label = cast(tk.Label, proc_widgets["stats_label"])
        self.tree = cast(ttk.Treeview, proc_widgets["tree"])

        res_widgets = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label = cast(tk.Label, res_widgets["completion_label"])
        self.time_label = cast(tk.Label, res_widgets["time_label"])
        self.summary_label = cast(tk.Label, res_widgets["summary_label"])

        self._tab_processing = tab_processing
        self._tab_results = tab_results

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

    # ── Preset support ────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {"target_lufs": self.target_lufs.get(), "run_mode": self.run_mode.get()}

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "target_lufs" in settings:
            self.target_lufs.set(settings["target_lufs"])
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

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        """Browse for folder with enhanced error handling."""
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
        """Open the source folder since ReplayGain Analyzer processes files in-place."""
        folder_path = self.folder_path.get()
        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Source folder not available.")

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
            for item in self.tree.get_children():
                self.tree.delete(item)
            self.notebook.select(self._tab_processing)
            self.overall_status.set("Analyzing ReplayGain values...")

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
        dir_path = self.folder_path.get()
        is_dry_run = self.run_mode.get() == "Dry Run"
        target = float(self.target_lufs.get())

        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            "replaygain_dry_run_log.txt" if is_dry_run else "replaygain_sync_log.txt",
        )
        self.root.after(0, lambda: setattr(self.progress, "value", 0))

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
                on_progress=self._on_file_progress,
                on_folder_complete=self._on_folder_complete,
                on_complete=lambda **kw: self._on_complete(header=header, **kw),
                on_error=self._on_error,
                apply_lossless_gain=(
                    not is_dry_run and self.apply_lossless_gain_var.get()
                ),
            )

    # ── Callbacks (called from background thread — all UI via root.after) ─────

    def _on_file_progress(self, processed: int, total: int, errors: int) -> None:
        def _update_progress(
            p: int = processed, t: int = total, e: int = errors
        ) -> None:
            self.progress.configure(maximum=t, value=p)
            self.stats_label.config(text=f"Processed: {p} | Errors: {e}")

        self.root.after(0, _update_progress)

    def _on_folder_complete(
        self,
        folder_path: str,
        files_data: list[Any],
        album_gain_str: str,
        album_peak_str: str,
        tag_results: list[Any],
        log_header: str,
    ) -> None:
        for file_data, status, tg_str, tp_str in tag_results:

            def _insert_row(
                n: Any = file_data["name"],
                lufs: Any = file_data["lufs"],
                tg: Any = tg_str,
                ag: str = album_gain_str,
                s: Any = status,
            ) -> None:
                self.tree.insert("", "end", values=(n, f"{lufs:.2f}", tg, ag, s))

            self.root.after(0, _insert_row)

    def _on_complete(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int = 0,
        errors: int = 0,
        duration_secs: float = 0.0,
        log_entries: list[str] | None = None,
    ) -> None:
        if log_entries is None:
            log_entries = []
        is_dry_run = self.run_mode.get() == "Dry Run"
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        succeeded = processed - errors

        summary: list[str] = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"Successfully processed: {succeeded}\n",
            f"Errors: {errors}\n",
            f"Time: {minutes:02d}:{seconds:02d}\n",
        ]

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

        def _update_ui() -> None:
            self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
            self.summary_label.config(
                text=f"Total: {total} files\n"
                f"Successfully processed: {succeeded}\n"
                f"Errors: {errors}"
            )
            self.completion_label.config(
                text="Analysis Complete!"
                if is_dry_run
                else "ReplayGain Tagging Complete!"
            )
            self.notebook.select(self._tab_results)
            self.start_btn.config(state="normal")
            if self.auto_end:
                self.root.after(2000, self.root.destroy)

        self.root.after(0, _update_ui)

    def _on_error(self, message: str) -> None:
        def _show_error(m: str = message) -> None:
            messagebox.showerror("Error", m)
            self.start_btn.config(state="normal")

        self.root.after(0, _show_error)
