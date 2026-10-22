"""
app.py
AudioNormalizerApp -- thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

Changed in 1.4.0: the worker slot grid is sized from ``DEFAULT_MAX_WORKERS``
instead of a literal 4 (PLAN D56).

Changed in 1.4.1: ``_on_complete`` and ``_on_progress`` accept ``**_extra: Any``,
so a payload field the processor adds (D112) is ignored instead of aborting an
otherwise-finished run; ``tests/test_callback_payload_contract.py`` locks the
completion, progress and error seams.
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
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import (
    UniversalCLIHandler,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_audition import AuditionMixin
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core import file_processor
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "audio_normalizer"


class AudioNormalizerApp(UIHelperMixin, AuditionMixin):
    """Audio Normalizer application GUI."""

    HELP_GUIDE = "Audio_Normalizer_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Audio Normalizer - Optimized",
            "audio_normalizer_window",
            TOOL_ID,
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")
        self.target_lufs = tk.DoubleVar(value=-14.0)
        self.tolerance = tk.DoubleVar(value=0.5)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        # ── State ─────────────────────────────────────────────────────────────
        self._log_path: str = ""
        self._dir_path: str = ""
        self._run_was_dry_run: bool = False
        self.auto_end: bool = False
        self._driver_locked = was_launched_from_driver()
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Worker slot pool ──────────────────────────────────────────────────
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
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

        (
            self.start_btn,
            self._refresh_preset_list,
            self._preset_combo,
        ) = setup_tab.build(
            tab_setup,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            target_lufs=self.target_lufs,
            tolerance=self.tolerance,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            driver_locked=self._driver_locked,
            preset_names=suite_config.list_presets(TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
        )

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
            "target_lufs": self.target_lufs.get(),
            "tolerance": self.tolerance.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "target_lufs" in settings:
            self.target_lufs.set(settings["target_lufs"])
        if "tolerance" in settings:
            self.tolerance.set(settings["tolerance"])
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
        if not parsed.folder_path:
            return

        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed,
            folder_var=self.folder_path,
        )

        if hasattr(parsed, "target_lufs") and parsed.target_lufs is not None:
            self.target_lufs.set(parsed.target_lufs)
        if hasattr(parsed, "tolerance") and parsed.tolerance is not None:
            self.tolerance.set(parsed.tolerance)
        if parsed.live_mode is not None:
            if parsed.live_mode:
                mode = (
                    "Lossless Normalize"
                    if getattr(parsed, "normalization_mode", "normalise") == "lossless"
                    else "Normalize"
                )
            else:
                mode = "Dry Run"
            self.run_mode.set(mode)

        # Mirror driver display-only vars
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

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
        """Open the source folder since Audio Normalizer processes files in-place."""
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
        """Validate inputs and start the background processing thread."""
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
        self.overall_status.set("Normalizing audio...")

        self._run_was_dry_run = self.run_mode.get() == "Dry Run"
        self.prepare_in_place_audition(folder, SUPPORTED_EXTENSIONS)

        threading.Thread(target=self._run, daemon=True).start()

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="audio_normalizer_app_run")
    def _run(self) -> None:
        dir_path = self.folder_path.get()
        run_mode = self.run_mode.get()
        is_dry_run = run_mode == "Dry Run"
        normalization_mode = (
            "lossless" if run_mode == "Lossless Normalize" else "normalise"
        )
        target_lufs = self.target_lufs.get()
        tolerance = self.tolerance.get()

        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            "normalization_dry_run_log.txt"
            if is_dry_run
            else "audio_normalization_log.txt",
        )
        self.progress["value"] = 0

        mode_label = (
            "DRY RUN"
            if is_dry_run
            else "LOSSLESS NORMALIZE (MP3 global_gain)"
            if normalization_mode == "lossless"
            else "NORMALIZE (FFmpeg re-encode)"
        )
        header = [
            "AUDIO NORMALIZATION REPORT\n",
            f"Mode: {mode_label}\n",
            f"Target LUFS: {target_lufs}\n",
            f"Tolerance: {tolerance} LUFS\n",
            "=" * 60 + "\n",
        ]

        with active_batch("audio_normalizer", "tag_edit"):
            file_processor.run_parallel_process(
                dir_path=dir_path,
                target_lufs=target_lufs,
                tolerance=tolerance,
                is_dry_run=is_dry_run,
                normalization_mode=normalization_mode,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(header=header, **kw),
                on_error=self._on_error,
            )

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_progress(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
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
        **_extra: Any,
    ) -> None:
        is_dry_run = self.run_mode.get() == "Dry Run"
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        normalised = processed - skipped - errors

        summary = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"Normalized: {normalised}\n",
            f"Skipped (within tolerance): {skipped}\n",
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
            messagebox.showerror(
                "Error",
                f"Could not write log file:\n{user_message_for(mapped)}",
            )

        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=(
                f"Total: {total} files\n"
                f"Normalized: {normalised}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        )
        self.completion_label.config(
            text="Normalization Complete!" if not is_dry_run else "Dry Run Complete!"
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
                with open(self._log_path, "w", encoding="utf-8") as f:
                    f.writelines(all_entries)
            except Exception as exc:
                logger.warning(
                    "Could not append auto-end marker: %s", exc, exc_info=True
                )
            self.root.update_idletasks()
            self.root.after(2000, self.root.destroy)

    def _on_error(self, message: str) -> None:
        messagebox.showerror("Error", message)
        self.start_btn.config(state="normal")
