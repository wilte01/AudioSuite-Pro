"""
app.py
BPMAnalyzerApp — thin orchestrator that wires UI, core logic, and utilities together.
Contains no business logic itself; it only coordinates.

Changed in 1.2.0: records tracks that yielded no BPM as a run note, so a
batch report says so instead of only the tool's own log.
Changed in 1.4.0: the saved worker default, slot grid and report header all
resolve through ``default_max_workers()`` / ``DEFAULT_MAX_WORKERS`` (PLAN D56);
an over-grid typed count is logged rather than shown when unattended (D70).
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, cast

from audio_suite_shared import styles
from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.audio_formats import is_supported_format
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import (
    UniversalCLIHandler as UniversalCLIHandler,
)
from audio_suite_shared.constants import (
    DEFAULT_MAX_WORKERS,
    cap_workers_to_slot_grid,
    default_max_workers,
)
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.run_outcome import record_caveats, shortfall
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.tool_app_base import AnalysisTagToolApp
from audio_suite_shared.ui_common import cap_typed_workers

from .core import file_processor
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "bpm_analyzer"

#: The Master Driver keys this tool's batch step — and therefore its run note
#: — by the manifest id, which is shorter than the window key above.
DRIVER_TOOL_ID = "bpm"


class BPMAnalyzerApp(AnalysisTagToolApp):
    """BPM Analyzer application GUI."""

    # Name of the user-guide document expected alongside this script.
    HELP_GUIDE: str = "BPM_Analyzer_User_Guide.docx"

    TAGGED_LABEL: str = "Tagged/Analyzed"
    DRY_COMPLETE_LABEL: str = "Analysis Complete!"
    LIVE_COMPLETE_LABEL: str = "BPM Tagging Complete!"

    PRESET_KEY_PREFIX = "bpm"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "BPM Analyzer & Tagger",
            "bpm_analyzer_window",
            "bpm_analyzer",
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path: tk.StringVar = tk.StringVar()
        self.run_mode: tk.StringVar = tk.StringVar(value="Dry Run")
        self.bpm_range_min: tk.IntVar = tk.IntVar(value=75)
        self.bpm_range_max: tk.IntVar = tk.IntVar(value=175)
        self.analysis_duration: tk.IntVar = tk.IntVar(value=90)
        saved_parallel: bool = cast(
            bool, _suite_config.load_value("bpm_parallel_mode", False)
        )
        saved_workers: int = int(
            cast(
                str,
                _suite_config.load_value("bpm_max_workers", default_max_workers()),
            )
        )
        self.parallel_mode: tk.BooleanVar = tk.BooleanVar(value=saved_parallel)
        self.max_workers: tk.IntVar = tk.IntVar(value=saved_workers)

        # CLI attribute aliases for UniversalCLIHandler.
        self.bpm_min: tk.IntVar = self.bpm_range_min
        self.bpm_max: tk.IntVar = self.bpm_range_max
        self.duration: tk.IntVar = self.analysis_duration

        # Run Controls panel variables (driver handshake display state).
        self.auto_start_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.auto_end_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.clear_logs_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.parallel_var: tk.BooleanVar = tk.BooleanVar(value=False)

        # Master Driver handshake: any CLI argument means driver-launched,
        # in which case the Run Controls panel is locked to inherited values.
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # ── Processing state ─────────────────────────────────────────────────
        self._log_entries: list[str] = []
        self._log_path: str = ""
        self._dir_path: str = ""
        self.auto_end: bool = False

        # ── Worker slot pool ─────────────────────────────────────────────────
        self.slot_vars: list[tk.StringVar] = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self.slot_queue: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        # ── Preset support ────────────────────────────────────────────────────
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Build UI ──────────────────────────────────────────────────────────
        self._build_ui()
        assert self._refresh_preset_list is not None
        self._refresh_preset_list()

        # ── Apply CLI arguments ───────────────────────────────────────────────
        self._apply_cli_args()

        # Force UI refresh so Entry widgets display current variable values.
        self.root.update_idletasks()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last: str = _suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Construct the full application UI."""
        # Help button above the notebook.
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

        # Notebook with three tabs.
        self.notebook: ttk.Notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        tab_setup = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_processing = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_results = tk.Frame(self.notebook, bg=styles.BG_LIGHT)

        self.notebook.add(tab_setup, text=" 1. Setup ")
        self.notebook.add(tab_processing, text=" 2. Processing ")
        self.notebook.add(tab_results, text=" 3. Results ")

        setup_widgets: dict[str, Any] = setup_tab.build(
            tab_setup,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            bpm_range_min=self.bpm_range_min,
            bpm_range_max=self.bpm_range_max,
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
            on_preset_selected=self._on_preset_selected,
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
        )
        self.start_btn = setup_widgets["start_btn"]
        self._preset_combo = setup_widgets["preset_combo"]
        self._refresh_preset_list = setup_widgets["refresh_preset_list"]

        proc_widgets: dict[str, Any] = processing_tab.build(
            tab_processing, self.slot_vars
        )
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]

        res_widgets: dict[str, Any] = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]
        self.time_label: tk.Label = res_widgets["time_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]

        # Keep tab references for programmatic switching.
        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        """Parse and apply any command-line arguments supplied by the Master Driver."""
        parsed = cli_args.parse()
        self._apply_driver_cli_args(parsed)

    # ── Options (per-tool extras omitted) ─────────────────────────────────────

    def start_processing(self) -> None:
        """Validate inputs then launch the background analysis thread."""
        try:
            folder: str = self.folder_path.get().strip()

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

            try:
                has_audio: bool = any(
                    is_supported_format(f) for f in os.listdir(folder)
                )
                if not has_audio:
                    messagebox.showerror(
                        "No Audio Files",
                        f"No supported audio files found in:\n{folder}\n\n"
                        "Supported formats: MP3, FLAC, OGG, M4A, Opus, WAV, AIFF",
                    )
                    return
            except PermissionError as exc:
                messagebox.showerror(
                    "Access Denied",
                    f"Cannot access directory:\n{folder}\n\n{exc}",
                )
                return

            min_bpm: int = self.bpm_range_min.get()
            max_bpm: int = self.bpm_range_max.get()

            if min_bpm >= max_bpm:
                messagebox.showerror(
                    "Invalid BPM Range",
                    f"Minimum BPM ({min_bpm}) must be less than Maximum BPM "
                    f"({max_bpm}).",
                )
                return

            if not (40 <= min_bpm <= 300):
                messagebox.showerror(
                    "Invalid BPM Range",
                    f"Minimum BPM must be between 40 and 300 (current: {min_bpm}).",
                )
                return

            if not (60 <= max_bpm <= 400):
                messagebox.showerror(
                    "Invalid BPM Range",
                    f"Maximum BPM must be between 60 and 400 (current: {max_bpm}).",
                )
                return

            duration: int = self.analysis_duration.get()
            if not (10 <= duration <= 300):
                messagebox.showerror(
                    "Invalid Duration",
                    f"Analysis duration must be between 10 and 300 seconds "
                    f"(current: {duration}).",
                )
                return

            workers: int = self.max_workers.get()
            if workers < 1:
                messagebox.showerror(
                    "Invalid Workers",
                    f"Number of workers must be at least 1 (current: {workers}).",
                )
                return

            # A typed count above the fixed slot grid would hand a worker an
            # index past slot_vars and report each of those files as an
            # unexplained per-file error; cap it before the run is persisted.
            workers = cap_typed_workers(
                self.max_workers,
                self._safe_slot_vars,
                unattended=self._launched_from_driver,
            )

            # Persist parallel processing settings
            _suite_config.save_value("bpm_parallel_mode", self.parallel_mode.get())
            _suite_config.save_value("bpm_max_workers", workers)

            # All validations passed — start processing.
            self.start_btn.config(state="disabled")
            self.notebook.select(self._tab_processing)
            self.overall_status.set("Analyzing BPM...")
            is_dry_run: bool = self.run_mode.get() == "Dry Run"
            parallel: bool = self.parallel_mode.get()
            logger.info(
                "start_processing: folder=%s dry_run=%s bpm=[%d,%d] duration=%ds "
                "parallel=%s workers=%d",
                folder,
                is_dry_run,
                min_bpm,
                max_bpm,
                duration,
                parallel,
                workers,
            )

            threading.Thread(
                target=self._run_analysis,
                args=(
                    folder,
                    is_dry_run,
                    min_bpm,
                    max_bpm,
                    duration,
                    parallel,
                    workers,
                ),
                daemon=True,
            ).start()

        except Exception as exc:
            mapped = map_to_audio_error(exc, context={"action": "start_processing"})
            logger.error(
                "[%s] Validation error in start_processing: %s",
                type(mapped).__name__,
                mapped,
                exc_info=True,
            )
            messagebox.showerror(
                "Validation Error",
                f"Failed to validate inputs:\n{user_message_for(mapped)}",
            )

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="bpm_analyzer_app_run")
    def _run_analysis(
        self,
        dir_path: str,
        is_dry_run: bool,
        bpm_min: int,
        bpm_max: int,
        analysis_duration: int,
        parallel_mode: bool = False,
        max_workers: int | None = None,
    ) -> None:
        """Background thread: delegate to file_processor.run_analysis."""
        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path, "bpm_dry_run_log.txt" if is_dry_run else "bpm_sync_log.txt"
        )
        # Defensive: a preset or restored setting can bypass start_processing.
        requested_workers = (
            max_workers if max_workers is not None else default_max_workers()
        )
        effective_workers = cap_workers_to_slot_grid(
            requested_workers, self._safe_slot_vars
        )

        header: list[str] = [
            "BPM ANALYSIS REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"BPM Range: {bpm_min} - {bpm_max}\n",
            f"Analysis Duration: {analysis_duration} seconds\n",
            f"Parallel: {'Yes' if parallel_mode else 'No'}\n",
            f"Workers: {effective_workers}\n",
            "=" * 60 + "\n",
        ]

        self.root.after(0, self._reset_progress_ui)

        with active_batch("bpm_analyzer", "tag_edit"):
            file_processor.run_analysis(
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                min_bpm=bpm_min,
                max_bpm=bpm_max,
                analysis_duration=analysis_duration,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(header=header, **kw),
                on_error=self._on_error,
                parallel_mode=parallel_mode,
                max_workers=effective_workers,
            )

    # ── Completion ────────────────────────────────────────────────────────────

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
        """Record what the run could not analyse, then finish as usual.

        Runs on the worker thread before the shared base writes the report and
        schedules the Results update, so neither a damaged Tk nor an unwritable
        log can suppress the note the Master Driver reads.
        """
        self._record_run_note(total=total, errors=errors)
        super()._on_complete(
            header=header,
            total=total,
            processed=processed,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            log_entries=log_entries,
        )

    def _record_run_note(self, *, total: int, errors: int) -> None:
        """Record the tracks this run could not give a BPM to.

        BPM detection either returns a value or raises, so every file the run
        cannot analyse is already counted as an error; there is no separate
        skip path.  A clean run records nothing, which clears any earlier note.

        Args:
            total: Files the run attempted.
            errors: Files whose BPM detection failed.
        """
        record_caveats(
            DRIVER_TOOL_ID,
            shortfall(errors, total, "track", "yielded no BPM") if errors else "",
        )

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, int | bool | str]:
        """Collect current UI settings into a dict for preset storage."""
        return {
            "bpm_min": self.bpm_range_min.get(),
            "bpm_max": self.bpm_range_max.get(),
            "duration": self.analysis_duration.get(),
            "parallel_mode": self.parallel_mode.get(),
            "max_workers": self.max_workers.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, int | bool | str]) -> None:
        """Apply a preset dict to the UI variables."""
        self.bpm_range_min.set(int(settings.get("bpm_min", 75)))
        self.bpm_range_max.set(int(settings.get("bpm_max", 175)))
        self.analysis_duration.set(int(settings.get("duration", 90)))
        self.parallel_mode.set(bool(settings.get("parallel_mode", False)))
        self.max_workers.set(int(settings.get("max_workers", default_max_workers())))
        self.run_mode.set(str(settings.get("run_mode", "Dry Run")))
