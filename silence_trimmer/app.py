"""
app.py
SilenceTrimmerApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.
"""

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any

from audio_suite_shared import platform_utils, styles
from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS
from audio_suite_shared.ui_audition import AuditionMixin
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core import file_processor
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)
TOOL_ID = "silence_trimmer"


class _ThreadSafeSlotVar:
    """Wrap a tk.StringVar so that .set() is always scheduled on the main thread."""

    def __init__(self, root: tk.Tk, var: tk.StringVar) -> None:
        self._root = root
        self._var = var

    def set(self, value: str) -> None:
        self._root.after(0, self._var.set, value)

    def get(self) -> str:
        return self._var.get()


class SilenceTrimmerApp(UIHelperMixin, AuditionMixin):
    """Silence Trimmer application GUI."""

    HELP_GUIDE = "Silence_Trimmer_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Silence Trimmer & Fader",
            "silence_trimmer_window",
            "silence_trimmer",
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")
        self.fade_var = tk.BooleanVar(value=False)
        self.threshold = tk.IntVar(value=-50)
        self.fade_in_duration = tk.IntVar(value=500)
        self.fade_out_duration = tk.IntVar(value=1000)
        saved_parallel = bool(_suite_config.load_value("trim_parallel_mode", False))
        workers_saved = _suite_config.load_value("trim_max_workers", 4)
        saved_workers = workers_saved if isinstance(workers_saved, int) else 4
        self.parallel_mode = tk.BooleanVar(value=saved_parallel)
        self.max_workers = tk.IntVar(value=saved_workers)

        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # ── State ─────────────────────────────────────────────────────────────
        self._log_path: str = ""
        self._dir_path: str = ""
        self._run_was_dry_run: bool = False

        # ── Worker slot pool ──────────────────────────────────────────────────
        self.slot_vars = [tk.StringVar(value="IDLE") for _ in range(4)]
        self._safe_slot_vars = [
            _ThreadSafeSlotVar(self.root, v) for v in self.slot_vars
        ]
        self.slot_queue: Queue[Any] = Queue()
        for i in range(4):
            self.slot_queue.put(i)

        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Apply CLI arguments BEFORE building UI ────────────────────────────
        self._apply_cli_args()

        # ── Build UI ──────────────────────────────────────────────────────────
        self._build_ui()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last = _suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Construct the full application UI across three notebook tabs."""
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

        setup_state = setup_tab.build(
            tab_setup,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            threshold=self.threshold,
            fade_var=self.fade_var,
            fade_in_duration=self.fade_in_duration,
            fade_out_duration=self.fade_out_duration,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            driver_locked=self._launched_from_driver,
            parallel_mode=self.parallel_mode,
            max_workers=self.max_workers,
            preset_names=_suite_config.list_presets(TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
        )
        self.start_btn = setup_state["start_btn"]
        self._refresh_preset_list = setup_state["refresh_presets"]
        self._preset_combo = setup_state["preset_combo"]

        proc_widgets = processing_tab.build(tab_processing, self.slot_vars)
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]

        res_widgets = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
            on_play_original=self._play_original,
            on_play_result=self._play_result,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]
        self.time_label: tk.Label = res_widgets["time_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]
        self.setup_audition(res_widgets)

        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "threshold": self.threshold.get(),
            "fade_var": self.fade_var.get(),
            "fade_in_duration": self.fade_in_duration.get(),
            "fade_out_duration": self.fade_out_duration.get(),
            "parallel_mode": self.parallel_mode.get(),
            "max_workers": self.max_workers.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "threshold" in settings:
            self.threshold.set(settings["threshold"])
        if "fade_var" in settings:
            self.fade_var.set(settings["fade_var"])
        if "fade_in_duration" in settings:
            self.fade_in_duration.set(settings["fade_in_duration"])
        if "fade_out_duration" in settings:
            self.fade_out_duration.set(settings["fade_out_duration"])
        if "parallel_mode" in settings:
            self.parallel_mode.set(settings["parallel_mode"])
        if "max_workers" in settings:
            self.max_workers.set(int(settings["max_workers"]))
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])

    def _on_preset_selected(self, name: str) -> None:
        settings = _suite_config.load_preset(TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        _suite_config.save_preset(TOOL_ID, name, self._collect_settings())
        self._refresh_preset_list(_suite_config.list_presets(TOOL_ID))

    def _delete_preset(self, name: str) -> None:
        _suite_config.delete_preset(TOOL_ID, name)
        self._refresh_preset_list(_suite_config.list_presets(TOOL_ID))

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        """Parse and apply CLI arguments, triggering auto-start if instructed."""
        parsed = cli_args.parse()
        if not parsed.folder_path:
            return

        self.threshold.set(parsed.threshold)
        self.fade_var.set(parsed.apply_fade)
        if parsed.fade_in_ms is not None:
            self.fade_in_duration.set(parsed.fade_in_ms)
        if parsed.fade_out_ms is not None:
            self.fade_out_duration.set(parsed.fade_out_ms)

        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed, folder_var=self.folder_path, auto_start_func=self.start_processing
        )

        self.auto_end_var.set(parsed.auto_end)
        self.auto_start_var.set(parsed.auto_start)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

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

    def _open_help(self) -> None:
        """Open the tool help document."""
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        """Open the processing log file."""
        self._open_log_standard()

    def _open_folder(self) -> None:
        """Open the source folder since Silence Trimmer processes files in-place."""
        folder_path = self.folder_path.get()
        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Source folder not available.")

    def start_processing(self) -> None:
        """Validate inputs and start the trimming background thread."""
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
                    "Supported formats: MP3, FLAC, OGG, M4A, MP4, Opus, WAV, AIFF",
                )
                return

            try:
                thresh = self.threshold.get()
                if thresh > -20 or thresh < -80:
                    messagebox.showerror(
                        "Invalid Threshold",
                        "Silence threshold should be between -80 and -20 dB.",
                    )
                    return
            except (ValueError, TypeError) as exc:
                messagebox.showerror(
                    "Invalid Threshold", f"Invalid threshold value: {exc}"
                )
                return

            try:
                fade_in = self.fade_in_duration.get()
                fade_out = self.fade_out_duration.get()
                if fade_in < 100 or fade_in > 3000:
                    messagebox.showerror(
                        "Invalid Fade Duration",
                        "Fade-in duration must be between 100ms and 3000ms.",
                    )
                    return
                if fade_out < 100 or fade_out > 5000:
                    messagebox.showerror(
                        "Invalid Fade Duration",
                        "Fade-out duration must be between 100ms and 5000ms.",
                    )
                    return
            except (ValueError, TypeError) as exc:
                messagebox.showerror(
                    "Invalid Fade Duration", f"Invalid fade duration: {exc}"
                )
                return

            self._dir_path = folder

            # Persist parallel processing settings
            _suite_config.save_value("trim_parallel_mode", self.parallel_mode.get())
            _suite_config.save_value("trim_max_workers", self.max_workers.get())

            self.start_btn.config(state="disabled")
            self.file_listbox.delete(0, tk.END)
            self.progress["value"] = 0
            self.notebook.select(self._tab_processing)
            self.overall_status.set("Trimming silence...")

            self._run_was_dry_run = self.run_mode.get() == "Dry Run"
            self.prepare_in_place_audition(folder, SUPPORTED_EXTENSIONS)

            threading.Thread(target=self._run, daemon=True).start()

        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Processing Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Processing Error",
                f"Failed to start processing:\n{user_message_for(mapped)}",
            )

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="silence_trimmer_app_run")
    def _run(self) -> None:
        """Background thread: collect parameters and delegate to file_processor."""
        dir_path = self.folder_path.get()
        is_dry_run = self.run_mode.get() == "Dry Run"
        thresh = self.threshold.get()
        apply_fade = self.fade_var.get()
        fade_in = self.fade_in_duration.get()
        fade_out = self.fade_out_duration.get()
        parallel = self.parallel_mode.get()
        workers = self.max_workers.get()

        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            "trim_dry_run_log.txt" if is_dry_run else "trim_sync_log.txt",
        )
        self.progress["value"] = 0

        fade_info = (
            f"Fade-in: {fade_in}ms, Fade-out: {fade_out}ms"
            if apply_fade
            else "No fades"
        )
        header: list[str] = [
            "SILENCE TRIMMING REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Silence Threshold: {thresh} dB\n",
            f"Fades: {fade_info}\n",
            f"Workers: {workers}\n",
            "=" * 60 + "\n",
        ]

        with active_batch("silence_trimmer", "tag_edit"):
            file_processor.run_trimming(
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                threshold=thresh,
                apply_fade=apply_fade,
                fade_in_ms=fade_in,
                fade_out_ms=fade_out,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(header=header, **kw),
                on_error=self._on_error,
                parallel_mode=parallel,
                max_workers=workers,
            )

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_progress(
        self, processed: int, total: int, skipped: int, errors: int, display_text: str
    ) -> None:
        """Update progress bar and file list on the main thread."""
        self.progress["maximum"] = total
        self.progress["value"] = processed
        self.stats_label.config(
            text=f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}"
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

    def _on_complete(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
    ) -> None:
        """Write log, update results tab, and re-enable the start button."""
        is_dry_run = self.run_mode.get() == "Dry Run"
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        succeeded = processed - skipped - errors

        summary: list[str] = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"Processed: {succeeded}\n",
            f"Skipped (no silence): {skipped}\n",
            f"Errors: {errors}\n",
            f"Time: {minutes:02d}:{seconds:02d}\n",
        ]
        all_entries = header + log_entries + summary

        try:
            with open(self._log_path, "w", encoding="utf-8") as fh:
                fh.writelines(all_entries)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Log write failed: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Error",
                f"Could not write log file:\n{user_message_for(mapped)}",
            )

        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=(
                f"Total: {total} files\n"
                f"Processed: {succeeded}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        )
        self.completion_label.config(
            text="Analysis Complete!" if is_dry_run else "Silence Trimming Complete!"
        )
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

        if self._run_was_dry_run:
            self.set_audition_state(
                self._audition_original,
                None,
                "Dry Run — nothing written. Play Result is unavailable.",
            )
        elif self._audition_original is not None and self._audition_result is not None:
            name = self._audition_result.name
            self.set_audition_state(
                self._audition_original,
                self._audition_result,
                f"Audition ready — {name} (original vs result)",
            )
        else:
            self.set_audition_state(
                None, None, "No supported audio file found for audition."
            )

        if self.auto_end_var.get():
            all_entries.append("\n[Auto End enabled - closing in 2 seconds...]\n")
            try:
                with open(self._log_path, "w", encoding="utf-8") as fh:
                    fh.writelines(all_entries)
            except Exception as exc:
                logger.warning("Auto-end log rewrite failed: %s", exc, exc_info=True)
            self.root.update_idletasks()
            self.root.after(2000, self.root.destroy)

    def _on_error(self, message: str) -> None:
        """Display an error dialog and re-enable the start button."""
        messagebox.showerror("Error", message)
        self.start_btn.config(state="normal")
