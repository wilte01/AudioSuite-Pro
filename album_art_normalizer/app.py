"""
app.py — Album Art Normalizer: thin orchestrator that wires UI, core logic,
and utilities together. Contains no business logic itself; it only coordinates.
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import cast

from audio_suite_shared import styles, suite_config
from audio_suite_shared.app_bootstrap import BaseSuiteApp
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.exceptions import (
    handle_audio_errors,
)

from .core import file_processor
from .core.art_processor import (
    FOLDER_JPG_TARGET,
    RESOLUTION_MAP,
    FolderImageError,
    process_folder_jpg,
)
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "album_art_normalizer"


class ArtNormalizerApp(BaseSuiteApp):
    """Album Art Normalizer application GUI."""

    HELP_GUIDE = "Album_Art_Normalizer_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(
            root,
            "Album Art Normalizer",
            "art_normalizer_window",
            "album_art_normalizer",
            help_guide=self.HELP_GUIDE,
        )

        # Tk variables
        self.folder_path: tk.StringVar = tk.StringVar()
        self.resolution: tk.StringVar = tk.StringVar(value="800×800")
        self.run_mode: tk.StringVar = tk.StringVar(value="Dry Run")

        # Driver-mirrored run controls (Clear Logs / Parallel are display-only)
        self.auto_start_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.auto_end_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.clear_logs_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.parallel_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # Processing state
        self._log_entries: list[str] = []
        self._log_path: str = ""
        self._dir_path: str = ""

        # Build UI
        self._build_ui()

        # Apply CLI arguments
        self._apply_cli_args()

        # Restore last-used directory
        if not self.folder_path.get():
            last: str = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    def _build_ui(self) -> None:
        """Construct the full application UI."""
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

        self.notebook: ttk.Notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        tab_setup = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_processing = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_results = tk.Frame(self.notebook, bg=styles.BG_LIGHT)

        self.notebook.add(tab_setup, text=" Setup ")
        self.notebook.add(tab_processing, text=" Processing ")
        self.notebook.add(tab_results, text=" Results ")

        setup_widgets = setup_tab.build(
            tab_setup,
            folder_path=self.folder_path,
            resolution=self.resolution,
            run_mode=self.run_mode,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            driver_locked=self._launched_from_driver,
        )
        self.start_btn: tk.Button = cast(tk.Button, setup_widgets["start_btn"])

        proc_widgets = processing_tab.build(tab_processing)
        self.overall_status: tk.StringVar = cast(
            tk.StringVar, proc_widgets["overall_status"]
        )
        self.progress: ttk.Progressbar = cast(ttk.Progressbar, proc_widgets["progress"])
        self.stats_label: tk.Label = cast(tk.Label, proc_widgets["stats_label"])
        self.file_listbox: tk.Listbox = cast(tk.Listbox, proc_widgets["file_listbox"])

        res_widgets = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = cast(
            tk.Label, res_widgets["completion_label"]
        )
        self.time_label: tk.Label = cast(tk.Label, res_widgets["time_label"])
        self.summary_label: tk.Label = cast(tk.Label, res_widgets["summary_label"])

        self._tab_processing = tab_processing
        self._tab_results = tab_results

    def _apply_cli_args(self) -> None:
        """Parse and apply any command-line arguments."""
        parsed = cli_args.parse()
        if not parsed.folder_path:
            return

        # Mirror the driver's run controls onto the Setup tab panel.
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        should_auto_start: bool = self.cli_handler.apply_cli_args(
            parsed,
            folder_var=self.folder_path,
        )
        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    def _browse_folder(self) -> None:
        """Browse for a music directory."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def start_processing(self) -> None:
        """Validate inputs then launch the background thread."""
        folder = self.folder_path.get().strip()

        if not folder:
            messagebox.showwarning("No Directory", "Please select a music directory.")
            return

        if not os.path.exists(folder):
            messagebox.showerror(
                "Directory Not Found", f"Directory not found:\n{folder}"
            )
            return

        if not os.path.isdir(folder):
            messagebox.showerror(
                "Invalid Directory", f"Not a valid directory:\n{folder}"
            )
            return

        resolution_key = self.resolution.get()
        if resolution_key not in RESOLUTION_MAP:
            messagebox.showerror(
                "Invalid Resolution",
                f"Please select a valid resolution. Got: {resolution_key}",
            )
            return

        target = RESOLUTION_MAP[resolution_key]
        logger.info(
            "start_processing: folder=%s resolution=%s target=%dx%d",
            folder,
            resolution_key,
            target[0],
            target[1],
        )

        self.start_btn.config(state="disabled")
        self.notebook.select(self._tab_processing)
        self.overall_status.set("Normalising artwork...")

        threading.Thread(
            target=self._run_normalization,
            args=(folder, target),
            daemon=True,
        ).start()

    @handle_audio_errors(reraise=False, context="art_normalizer_app_run")
    def _run_normalization(self, directory: str, target_size: tuple[int, int]) -> None:
        """Background thread: handle folder.jpg then delegate to file_processor."""
        self._dir_path = directory
        self._log_entries = []

        def _append_log(msg: str) -> None:
            self._log_entries.append(msg)
            logger.info(msg)

        _append_log("=== Session started ===")
        _append_log(f"Directory: {directory}")
        _append_log(f"Embedded target: {target_size[0]}×{target_size[1]}")
        _append_log(f"folder.jpg target: {FOLDER_JPG_TARGET[0]}×{FOLDER_JPG_TARGET[1]}")
        _append_log("")

        # folder.jpg
        try:
            result = process_folder_jpg(Path(directory))
            if result is None:
                _append_log("folder.jpg not present — skipped.")
            else:
                _append_log(f"  {result}")
        except FolderImageError as exc:
            _append_log(f"  ✗ ERROR: {exc}")

        _append_log("")

        self.root.after(0, self._reset_progress_ui)

        with active_batch("album_art_normalizer", "tag_edit"):
            file_processor.run_normalization(
                dir_path=directory,
                target_size=target_size,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(
                    total=kw.get("total", 0),
                    processed=kw.get("processed", 0),
                    skipped=kw.get("skipped", 0),
                    errors=kw.get("errors", 0),
                    duration_secs=kw.get("duration_secs", 0.0),
                    log_entries=kw.get("log_entries", []),
                ),
                on_error=self._on_error,
            )

    def _reset_progress_ui(self) -> None:
        self.progress["value"] = 0
        self.stats_label.config(text="Processed: 0 | Images Updated: 0 | Errors: 0")
        self.file_listbox.delete(0, tk.END)

    def _on_progress(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        self._log_entries.append(display_text)
        self.root.after(
            0, self._update_progress_ui, processed, total, skipped, errors, display_text
        )

    def _update_progress_ui(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        self.progress["maximum"] = total
        self.progress["value"] = processed
        updated = processed - skipped - errors
        self.stats_label.config(
            text=(
                f"Processed: {processed} | Images Updated: {updated} | Errors: {errors}"
            )
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

    def _on_complete(
        self,
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
    ) -> None:
        self.root.after(
            0,
            self._update_ui_on_complete,
            total,
            processed,
            skipped,
            errors,
            duration_secs,
        )

    def _update_ui_on_complete(
        self,
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        updated = processed - skipped - errors

        # Write log file
        log_path = os.path.join(self._dir_path, "art_normalize_log.txt")
        self._log_path = log_path
        try:
            with open(log_path, "w", encoding="utf-8") as f:
                f.writelines(f"{line}\n" for line in self._log_entries)
        except OSError as exc:
            logger.error("Failed to write log '%s': %s", log_path, exc, exc_info=True)

        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=(
                f"Files examined: {total}\n"
                f"Images updated: {updated}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        )
        self.completion_label.config(text="Artwork Normalization Complete!")
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

        logger.info(
            "Processing complete — total=%d updated=%d"
            " skipped=%d errors=%d time=%02d:%02d",
            total,
            updated,
            skipped,
            errors,
            minutes,
            seconds,
        )

        if self.auto_end_var.get():
            self.root.after(2000, self.root.destroy)
