"""
app.py
TempoAnalyzerApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

The scheme-change chain lives here because it touches three layers:
  1. Update self._active_markings  (core)
  2. Save preference to config     (utils)
  3. Redraw reference table        (ui — via injected callable)
"""

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, Callable

from audio_suite_shared import platform_utils, styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.audio_formats import is_supported_format
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core import file_processor
from .core.tempo_schemes import DEFAULT_SCHEME, TEMPO_SCHEMES
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)
TOOL_ID = "tempo_analyzer"

# Locate suite root (app.py → tempo_analyzer/ → tool_root/ → suite_root/)


class TempoAnalyzerApp(UIHelperMixin):
    """Tempo Analyzer application GUI."""

    HELP_GUIDE = "Tempo_Analyzer_User_Guide.docx"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Tempo Analyzer & Tagger",
            "tempo_analyzer_window",
            "tempo_analyzer",
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")
        self.tempo_scheme = tk.StringVar()

        # Driver-mirrored run controls (Clear Logs / Parallel are display-only)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # ── Config + scheme state ─────────────────────────────────────────────
        saved = suite_config.load_value("tempo_scheme", DEFAULT_SCHEME)
        if not isinstance(saved, str) or saved not in TEMPO_SCHEMES:
            saved = DEFAULT_SCHEME
        self.tempo_scheme.set(saved)
        self._active_markings = TEMPO_SCHEMES[saved]

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

        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Build UI ──────────────────────────────────────────────────────────
        self._update_reference: Callable[..., Any] = lambda _: None  # filled below
        self._build_ui()

        # Populate reference table with initial scheme
        self._update_reference(self._active_markings)

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

        widgets = setup_tab.build(
            tab_setup,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            tempo_scheme=self.tempo_scheme,
            scheme_names=list(TEMPO_SCHEMES.keys()),
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
            on_scheme_change=self._on_scheme_change,
            on_preset_select=self._on_preset_selected,
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
        )
        self.start_btn: tk.Button = widgets["start_btn"]
        self._update_reference = widgets["update_reference"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self._preset_combo = widgets["preset_combo"]

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
        self.time_label: tk.Label = res_widgets["time_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]

        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # ── Scheme change ─────────────────────────────────────────────────────────

    def _on_scheme_change(self) -> None:
        """Update markings, persist preference, refresh reference table."""
        scheme = self.tempo_scheme.get()
        if scheme not in TEMPO_SCHEMES:
            return
        self._active_markings = TEMPO_SCHEMES[scheme]
        suite_config.save_value("tempo_scheme", scheme)
        self._update_reference(self._active_markings)

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "tempo_scheme": self.tempo_scheme.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "tempo_scheme" in settings:
            self.tempo_scheme.set(settings["tempo_scheme"])
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

        # Mirror the driver's run controls onto the Setup tab panel.
        self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        # Universal CLI handling
        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed, folder_var=self.folder_path, auto_start_func=self.start_processing
        )

        # Apply Tempo-specific scheme handling.
        # Setting the StringVar fires the trace_add("write", ...) binding in
        # setup_tab.py, which itself calls _on_scheme_change() — no need to
        # call it again explicitly here.
        if parsed.scheme and parsed.scheme in TEMPO_SCHEMES:
            self.tempo_scheme.set(parsed.scheme)

        # Auto-start if instructed by Master Driver
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
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        self._open_log_standard()

    def _open_folder(self) -> None:
        """Open the source folder since Tempo Analyzer processes files in-place."""
        folder_path = self.folder_path.get()
        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Source folder not available.")

    def start_processing(self) -> None:
        """Start processing with enhanced validation and error handling."""
        try:
            folder = self.folder_path.get().strip()

            # Enhanced validation with specific error types
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

            # Check for audio files
            has_audio = any(is_supported_format(f) for f in os.listdir(folder))

            if not has_audio:
                messagebox.showerror(
                    "No Audio Files",
                    f"No supported audio files found in:\n{folder}\n\n"
                    "Supported formats: MP3, FLAC, OGG, M4A, Opus, WAV, AIFF",
                )
                return

            self.start_btn.config(state="disabled")
            self.file_listbox.delete(0, tk.END)
            self.notebook.select(self._tab_processing)
            self.overall_status.set("Analyzing tempo markings...")

            threading.Thread(target=self._run, daemon=True).start()

        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Processing Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Processing Error",
                f"Failed to start processing:\n{user_message_for(mapped)}",
            )

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="tempo_analyzer_app_run")
    def _run(self) -> None:
        dir_path = self.folder_path.get()
        is_dry_run = self.run_mode.get() == "Dry Run"
        scheme_name = self.tempo_scheme.get()
        markings = self._active_markings  # snapshot for this run

        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            "tempo_dry_run_log.txt" if is_dry_run else "tempo_analysis_log.txt",
        )
        self.progress["value"] = 0

        header: list[str] = [
            "TEMPO ANALYSIS REPORT\n",
            f"Scheme: {scheme_name}\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            "=" * 60 + "\n",
        ]

        with active_batch("tempo_analyzer", "tag_edit"):
            file_processor.run_analysis(
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                markings=markings,
                scheme_name=scheme_name,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(header=header, **kw),
                on_error=self._on_error,
            )

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_progress(
        self, processed: int, total: int, skipped: int, errors: int, display_text: str
    ) -> None:
        """Called from worker threads — schedule UI update on main thread."""
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
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
    ) -> None:
        """Called on background thread — file I/O here, then schedule UI on
        main thread."""
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        analysed = processed - skipped - errors

        summary: list[str] = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"Tagged/Analyzed: {analysed}\n",
            f"Skipped (no BPM): {skipped}\n",
            f"Errors: {errors}\n",
            f"Time: {minutes:02d}:{seconds:02d}\n",
        ]
        all_entries = header + log_entries + summary

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(all_entries)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Error: %s", mapped, exc_info=True)

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

        if self.auto_end:
            all_entries.append("\n[Auto End enabled - closing in 2 seconds...]\n")
            try:
                with open(self._log_path, "w", encoding="utf-8") as f:
                    f.writelines(all_entries)
            except Exception as _exc:
                logger.warning(
                    "Could not rewrite log after auto-end: %s", _exc, exc_info=True
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
            text=f"Total: {total} files\n"
            f"Tagged/Analyzed: {analysed}\n"
            f"Skipped: {skipped}\n"
            f"Errors: {errors}"
        )
        self.completion_label.config(
            text="Analysis Complete!" if is_dry_run else "Tempo Tagging Complete!"
        )
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

    def _on_error(self, message: str) -> None:
        """Called from worker threads — schedule error dialog on main thread."""
        self.root.after(0, self._show_error, message)

    def _show_error(self, message: str) -> None:
        """Show error dialog (must run on main thread)."""
        messagebox.showerror("Error", message)
        self.start_btn.config(state="normal")
