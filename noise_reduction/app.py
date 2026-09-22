"""
app.py
NoiseReductionApp — thin orchestrator for the Noise Reduction tool.

Thread-safety
-------------
All worker callbacks marshal UI mutations back onto the Tkinter main
thread via self.root.after(0, fn).
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, cast

from audio_suite_shared import styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_audition import AuditionMixin
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core.file_processor import run_noise_reduction
from .core.models import NoiseReductionParams
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "noise_reduction"


class NoiseReductionApp(UIHelperMixin, AuditionMixin):
    """Noise Reduction application GUI."""

    HELP_GUIDE = "Noise_Reduction_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.error_logger, self.style = bootstrap_tool_app(
            self.root,
            "Noise Reduction",
            "noise_reduction_window",
            TOOL_ID,
        )

        # ── Tk variables ────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")

        # Hum removal
        self.reduce_hum = tk.BooleanVar(value=False)
        self.hum_frequency = tk.IntVar(value=60)
        self.hum_harmonics = tk.IntVar(value=8)
        self.hum_quality = tk.DoubleVar(value=30.0)

        # Broadband noise
        self.reduce_broadband = tk.BooleanVar(value=False)
        self.noise_start_ms = tk.IntVar(value=0)
        self.noise_end_ms = tk.IntVar(value=500)
        self.gate_threshold_db = tk.DoubleVar(value=3.0)

        # Driver-mirrored
        self.auto_start_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.auto_end_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.clear_logs_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.parallel_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self._launched_from_driver: bool = cli_args.was_launched_from_driver()

        # ── State ───────────────────────────────────────────────────────
        self._log_path: str = ""
        self._run_was_dry_run: bool = False
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Worker slot pool ────────────────────────────────────────────
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        self._build_ui()
        self._apply_cli_args()

        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── UI ──────────────────────────────────────────────────────────────

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
            reduce_hum=self.reduce_hum,
            hum_frequency=self.hum_frequency,
            hum_harmonics=self.hum_harmonics,
            hum_quality=self.hum_quality,
            reduce_broadband=self.reduce_broadband,
            noise_start_ms=self.noise_start_ms,
            noise_end_ms=self.noise_end_ms,
            gate_threshold_db=self.gate_threshold_db,
            on_browse=self._on_browse,
            on_start=self._on_start,
            preset_names=suite_config.list_presets(TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            driver_locked=self._launched_from_driver,
        )
        self.start_btn = cast(tk.Button, setup_widgets["start_btn"])
        self._refresh_preset_list = setup_widgets["refresh_preset_list"]
        self._preset_combo = cast(ttk.Combobox, setup_widgets["preset_combo"])

        proc_widgets = processing_tab.build(tab_processing, self.slot_vars)
        self.overall_status = cast(tk.StringVar, proc_widgets["overall_status"])
        self.progress = cast(ttk.Progressbar, proc_widgets["progress"])
        self.stats_label = cast(tk.Label, proc_widgets["stats_label"])
        self.file_listbox = cast(tk.Listbox, proc_widgets["file_listbox"])

        res_widgets = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
            on_play_original=self._play_original,
            on_play_result=self._play_result,
        )
        self.completion_label = cast(tk.Label, res_widgets["completion_label"])
        self.summary_label = cast(tk.Label, res_widgets["summary_label"])
        self.time_label = cast(tk.Label, res_widgets["time_label"])
        self.setup_audition(res_widgets)

        self._tab_setup = tab_setup
        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # ── Presets ─────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "reduce_hum": self.reduce_hum.get(),
            "hum_frequency": self.hum_frequency.get(),
            "hum_harmonics": self.hum_harmonics.get(),
            "hum_quality": self.hum_quality.get(),
            "reduce_broadband": self.reduce_broadband.get(),
            "noise_start_ms": self.noise_start_ms.get(),
            "noise_end_ms": self.noise_end_ms.get(),
            "gate_threshold_db": self.gate_threshold_db.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        for key in (
            "reduce_hum",
            "hum_frequency",
            "hum_harmonics",
            "hum_quality",
            "reduce_broadband",
            "noise_start_ms",
            "noise_end_ms",
            "gate_threshold_db",
        ):
            if key in settings:
                var = getattr(self, key)
                var.set(settings[key])
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

    # ── CLI handling ────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        parsed = cli_args.parse()
        if not parsed.folder_path:
            return

        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed, folder_var=self.folder_path
        )

        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        if parsed.reduce_hum:
            self.reduce_hum.set(True)
        if parsed.hum_frequency:
            self.hum_frequency.set(parsed.hum_frequency)
        if parsed.hum_harmonics:
            self.hum_harmonics.set(parsed.hum_harmonics)
        if parsed.hum_quality:
            self.hum_quality.set(parsed.hum_quality)
        if parsed.reduce_broadband:
            self.reduce_broadband.set(True)
        if parsed.noise_start_ms:
            self.noise_start_ms.set(parsed.noise_start_ms)
        if parsed.noise_end_ms:
            self.noise_end_ms.set(parsed.noise_end_ms)
        if parsed.gate_threshold_db:
            self.gate_threshold_db.set(parsed.gate_threshold_db)
        if parsed.auto_end:
            self.auto_end_var.set(True)

        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        if should_auto_start:
            self.auto_start_var.set(True)
            self.root.after(500, self._on_start)

    # ── User actions ────────────────────────────────────────────────────

    def _on_browse(self) -> None:
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _on_start(self) -> None:
        folder = self.folder_path.get().strip()
        if not folder:
            messagebox.showwarning(
                "Noise Reduction", "Please select a music folder first."
            )
            return
        if not os.path.isdir(folder):
            messagebox.showerror(
                "Noise Reduction", "The selected folder does not exist."
            )
            return

        if not self.reduce_hum.get() and not self.reduce_broadband.get():
            messagebox.showwarning(
                "Noise Reduction",
                "Enable at least one of Hum Removal or Broadband Noise Reduction.",
            )
            return

        suite_config.save_last_directory(folder)

        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        self.overall_status.set("Running...")
        self.stats_label.config(
            text="Processed: 0 | Succeeded: 0 | Skipped: 0 | Errors: 0"
        )

        self.start_btn.config(state="disabled")
        self.notebook.select(self._tab_processing)

        is_dry_run = self.run_mode.get() == "Dry Run"
        self._run_was_dry_run = is_dry_run
        self.prepare_in_place_audition(folder, SUPPORTED_EXTENSIONS)

        params = NoiseReductionParams(
            reduce_hum=self.reduce_hum.get(),
            hum_frequency=self.hum_frequency.get(),
            hum_harmonics=self.hum_harmonics.get(),
            hum_quality=self.hum_quality.get(),
            reduce_broadband=self.reduce_broadband.get(),
            noise_start_ms=self.noise_start_ms.get(),
            noise_end_ms=self.noise_end_ms.get(),
            gate_threshold_db=self.gate_threshold_db.get(),
            dry_run=is_dry_run,
        )

        def _run_noise_reduction_with_undo() -> None:
            def _complete(**kw: Any) -> None:
                self.root.after(0, cast(Any, self._on_complete), **kw)

            def _fail(msg: str) -> None:
                self.root.after(0, self._on_error, msg)

            with active_batch("noise_reduction", "tag_edit"):
                run_noise_reduction(
                    folder,
                    params,
                    self._safe_slot_vars,
                    self.slot_queue,
                    self._on_progress,
                    _complete,
                    _fail,
                )

        self._worker = threading.Thread(
            target=_run_noise_reduction_with_undo,
            daemon=True,
        )
        self._worker.start()

    def _on_progress(
        self,
        processed: int,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        self.root.after(
            0,
            self._update_progress_ui,
            processed,
            total,
            succeeded,
            skipped,
            errors,
            display_text,
        )

    def _update_progress_ui(
        self,
        processed: int,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        self.progress["maximum"] = total
        self.progress["value"] = processed
        self.stats_label.config(
            text=f"Processed: {processed} | Succeeded: {succeeded} | Skipped: "
            f"{skipped} | Errors: {errors}"
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

    def _on_complete(
        self,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
    ) -> None:
        self.progress["value"] = 100
        self.overall_status.set("Complete.")

        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=(
                f"Total: {total} files\n"
                f"Reduced: {succeeded}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        )
        self.completion_label.config(text="Noise Reduction Complete!")
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

    def _on_error(self, message: str) -> None:
        messagebox.showerror("Noise Reduction", message)
        self.start_btn.config(state="normal")

    def _open_help(self) -> None:
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        self._open_log_standard()

    def _open_folder(self) -> None:
        self._open_folder_standard()


def main() -> None:
    """Standalone entry point: create the Tk root, run the app."""
    root = tk.Tk()
    NoiseReductionApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
