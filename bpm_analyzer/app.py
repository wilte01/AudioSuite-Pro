"""
app.py
BPMAnalyzerApp — thin orchestrator that wires UI, core logic, and utilities together.
Contains no business logic itself; it only coordinates.

Changed in 1.2.0: records tracks that yielded no BPM as a run note, so a
batch report says so instead of only the tool's own log.
Changed in 1.4.0: the saved worker default, slot grid and report header all
resolve through ``default_max_workers()`` / ``DEFAULT_MAX_WORKERS`` (PLAN D56);
an over-grid typed count is logged rather than shown when unattended (D70).
Changed in 1.4.1: the Results summary and the driver's run note report how many
tracks were measured outside the configured BPM range (D109).
Changed in 2.6.0: the analysis duration starts at the shared
``DEFAULT_BPM_ANALYSIS_SECONDS`` and a preset with no duration falls back to
it, so the GUI, the Master Driver and the CLI hand the detector one window
(D139).

Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, the fifth window of
D8's wave 2), so the shell owns the Help bar and the Processing and Results
tabs; this tool keeps its Setup panel, its ``Tagged/Analyzed`` summary wording
and its out-of-band row. The report and the Results panel are written here now
that the window no longer inherits ``AnalysisTagToolApp``, and the presets keep
their existing keys through the shared ``ui_presets`` store. The run's mode is
snapshotted on the main thread in ``start_processing``, so the completion never
reads a Tk variable off the Tk thread.

Changed in 2.9.0: the run report's ``SUMMARY:`` footer is
``audio_suite_shared.run_report.summary_lines``, the one implementation
every window writes with (D36).
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, cast

from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.audio_formats import is_supported_format
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import (
    UniversalCLIHandler as UniversalCLIHandler,
)
from audio_suite_shared.constants import (
    DEFAULT_BPM_ANALYSIS_SECONDS,
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
from audio_suite_shared.run_report import summary_lines
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_common import cap_typed_workers
from audio_suite_shared.ui_presets import (
    delete_tool_preset,
    load_tool_preset,
    save_tool_preset,
)

from .core import file_processor
from .ui import setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "bpm_analyzer"

#: The Master Driver keys this tool's batch step — and therefore its run note
#: — by the manifest id, which is shorter than the window key above.
DRIVER_TOOL_ID = "bpm"


class BPMAnalyzerApp(SuiteApp):
    """BPM Analyzer application GUI."""

    title = "BPM Analyzer & Tagger"
    window_key = "bpm_analyzer_window"
    program_name = TOOL_ID
    #: Kept for the guide registry's scan; the shell reads ``guide_name``.
    HELP_GUIDE: str = "BPM_Analyzer_User_Guide.docx"
    guide_name = HELP_GUIDE
    completion_text: str = "BPM Analysis Complete!"
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" 1. Setup ", " 2. Processing ", " 3. Results ")

    #: Word used in the report for the processed-but-neither-skipped-nor-
    #: erroring files.
    TAGGED_LABEL: str = "Tagged/Analyzed"
    #: Results-tab completion captions, by run mode.
    DRY_COMPLETE_LABEL: str = "Analysis Complete!"
    LIVE_COMPLETE_LABEL: str = "BPM Tagging Complete!"
    #: The preset keys this tool has always written (``bpm_preset_<name>``).
    PRESET_KEY_PREFIX: str = "bpm"

    #: Set from argv in ``__init__``.  The default keeps an ``object.__new__``
    #: test shell on the interactive (modal-warning) path.
    _launched_from_driver: bool = False
    #: Set by ``_run_analysis``; the Results tab's Open Folder target.
    _dir_path: str = ""

    def __init__(self, root: tk.Tk) -> None:
        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path: tk.StringVar = tk.StringVar()
        self.run_mode: tk.StringVar = tk.StringVar(value="Dry Run")
        self.bpm_range_min: tk.IntVar = tk.IntVar(value=75)
        self.bpm_range_max: tk.IntVar = tk.IntVar(value=175)
        self.analysis_duration: tk.IntVar = tk.IntVar(
            value=DEFAULT_BPM_ANALYSIS_SECONDS
        )
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
        self.auto_end: bool = False
        # The run's mode, snapshotted by start_processing on the Tk thread.
        self._run_mode: str = ""

        # ── Worker slot pool ─────────────────────────────────────────────────
        # Built before super().__init__: the shell renders the grid from it.
        self.slot_vars: list[tk.StringVar] = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(root, self.slot_vars)
        self.slot_queue: Queue[int] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        # ── Preset support ────────────────────────────────────────────────────
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        super().__init__(root)

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

    # ── Shell tabs ────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the run controls, the BPM band, the duration and the presets."""
        widgets: dict[str, Any] = setup_tab.build(
            parent,
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
        self.start_btn = widgets["start_btn"]
        self._preset_combo = widgets["preset_combo"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self.controls_panel = widgets["controls_panel"]

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        """Parse and apply any command-line arguments supplied by the Master Driver."""
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

        # The band, the duration and the worker count reach the widgets by
        # name: the handler matches its parsed fields against this window.
        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed, folder_var=self.folder_path, auto_start_func=self.start_processing
        )

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    def _browse_folder(self) -> None:
        """Browse for a music directory with standard error handling."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _open_folder(self) -> None:
        """Open the source folder since BPM Analyzer tags files in place."""
        self._open_source_folder_standard()

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
            self.file_listbox.delete(0, tk.END)
            self.progress["value"] = 0
            self.stats_label.config(text=self.processing_stats_text)
            self.notebook.select(self.processing_frame)
            self.overall_status.set("Analyzing BPM...")
            is_dry_run: bool = self.run_mode.get() == "Dry Run"
            parallel: bool = self.parallel_mode.get()
            # Snapshot the mode on the main thread: the completion renders from
            # it, and the worker must not call .get() (see _run_analysis).
            self._run_mode = "Dry Run" if is_dry_run else "Live Update"
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

        with active_batch(TOOL_ID, "tag_edit"):
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

    # ── Callbacks (called from worker threads — all UI via root.after) ────────

    def _on_progress(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
        """Progress seam: hand the widget writes to the Tk thread."""
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
        """Render one progress tick (must run on the main thread)."""
        self._render_progress_standard(processed, total, display_text)
        self.stats_label.config(
            text=f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}"
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
        outside_range_files: list[dict[str, object]] | None = None,
        **_extra: Any,
    ) -> None:
        """Record what the run could not analyse, then write the report.

        Runs on the worker thread before the Results update is scheduled, so
        neither a damaged Tk nor an unwritable log can suppress the note the
        Master Driver reads.

        ``outside_range_files`` arrives from ``run_analysis``'s completion
        callback: files whose tempo was measured outside the configured band
        and tagged as measured (D108).  They are counted in the run summary and
        in the driver's note, never reported as skips - the tempo was written.

        Args:
            header: Report header lines for this run.
            total: Files the run set out to analyse.
            processed: Files it finished attempting.
            skipped: Files with no discernible beat.
            errors: Files that could not be analysed.
            duration_secs: Wall-clock run time.
            log_entries: The per-file log lines.
            outside_range_files: Records for tempos outside the band, each
                ``{"filename", "bpm", "min_bpm", "max_bpm"}``.
            **_extra: The other tool-specific completion fields the processor
                always publishes (``skipped_files``, ``error_files``).  They
                feed the CLI's ``--json`` output and are ignored here: rejecting
                one aborted the whole completion, so no report was written and
                the Results tab never appeared.
        """
        outside = list(outside_range_files or [])
        rows = self._outside_summary(total=total, outside=outside)
        self._record_run_note(total=total, errors=errors, outside=outside)

        tagged = processed - skipped - errors

        summary: list[str] = summary_lines(
            total=total,
            tagged=tagged,
            tagged_label=self.TAGGED_LABEL,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            rows=rows,
        )
        all_entries: list[str] = header + log_entries + summary

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(all_entries)
            logger.info("Log written to '%s'", self._log_path)
        except PermissionError as exc:
            logger.error(
                "Permission denied writing log '%s': %s",
                self._log_path,
                exc,
                exc_info=True,
            )
        except OSError as exc:
            logger.error(
                "OSError writing log '%s': %s", self._log_path, exc, exc_info=True
            )
        except Exception as exc:
            mapped = map_to_audio_error(exc, context={"log_path": self._log_path})
            logger.error(
                "[%s] Unexpected error writing log: %s",
                type(mapped).__name__,
                mapped,
                exc_info=True,
            )

        self.root.after(
            0,
            self._update_ui_on_complete,
            total,
            tagged,
            skipped,
            errors,
            duration_secs,
            rows,
        )

    @staticmethod
    def _band_text(record: dict[str, object]) -> str:
        """Return one record's band as ``"75-175"``, or ``""`` when it has none."""
        low = record.get("min_bpm")
        high = record.get("max_bpm")
        if isinstance(low, int) and isinstance(high, int):
            return f"{low}-{high}"
        return ""

    def _outside_summary(
        self, *, total: int, outside: list[dict[str, object]]
    ) -> list[tuple[str, str]]:
        """Build the run summary's out-of-band row, or nothing when clean.

        Args:
            total: Files the run attempted.
            outside: Records for tempos measured outside the band.

        Returns:
            One ``("Outside BPM range", "<n> of <total> tracks (band 75-175)")``
            row when any file missed the band, else an empty list.
        """
        if not outside:
            return []
        band = self._band_text(outside[0])
        suffix = f" (band {band})" if band else ""
        return [("Outside BPM range", f"{len(outside)} of {total} tracks{suffix}")]

    def _record_run_note(
        self,
        *,
        total: int,
        errors: int,
        outside: list[dict[str, object]] | None = None,
    ) -> None:
        """Record what this run could not analyse or could not place in the band.

        BPM detection either returns a value or raises, so every file the run
        cannot analyse is already counted as an error; there is no separate
        skip path.  A tempo outside the configured band is different: it was
        measured, tagged and counted as processed, so it gets its own phrase
        rather than inflating the error count.  A clean run records nothing,
        which clears any earlier note.

        Args:
            total: Files the run attempted.
            errors: Files whose BPM detection failed.
            outside: Records for tempos measured outside the band.
        """
        problems: list[str] = []
        if errors:
            problems.append(shortfall(errors, total, "track", "yielded no BPM"))
        missed = list(outside or [])
        if missed:
            band = self._band_text(missed[0])
            outcome = (
                f"measured outside the {band} BPM range"
                if band
                else "measured outside the configured BPM range"
            )
            problems.append(shortfall(len(missed), total, "track", outcome))
        record_caveats(DRIVER_TOOL_ID, *problems)

    def _update_ui_on_complete(
        self,
        total: int,
        tagged: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        summary_extras: list[tuple[str, str]],
    ) -> None:
        """Render the finished run (must run on the main thread).

        ``summary_extras`` is the row set :meth:`_on_complete` wrote into the
        report, so the panel cannot show a row the log does not have (D109).
        """
        rows: list[tuple[str, str]] = list(summary_extras)
        text: str = (
            f"Total: {total} files\n"
            f"{self.TAGGED_LABEL}: {tagged}\n"
            f"Skipped: {skipped}\n"
            f"Errors: {errors}"
        )
        for label, value in rows:
            text += f"\n{label}: {value}"
        self.summary_label.config(text=text)

        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        logger.info(
            "Processing complete - total=%d tagged=%d skipped=%d "
            "errors=%d time=%02d:%02d",
            total,
            tagged,
            skipped,
            errors,
            minutes,
            seconds,
        )

        # This window has always labelled a finished run by its mode; the shell
        # renders ``completion_text``, so point it at this run's wording first.
        self.completion_text = (
            self.DRY_COMPLETE_LABEL
            if self._run_mode == "Dry Run"
            else self.LIVE_COMPLETE_LABEL
        )
        self.render_completion(duration_secs=duration_secs, output_dir=self._dir_path)

        if self.auto_end:
            self.root.after(2000, self.root.destroy)

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
        self.analysis_duration.set(
            int(settings.get("duration", DEFAULT_BPM_ANALYSIS_SECONDS))
        )
        self.parallel_mode.set(bool(settings.get("parallel_mode", False)))
        self.max_workers.set(int(settings.get("max_workers", default_max_workers())))
        self.run_mode.set(str(settings.get("run_mode", "Dry Run")))

    def _on_preset_selected(self, name: str) -> None:
        """Load a named preset and apply its settings."""
        settings = load_tool_preset(self.PRESET_KEY_PREFIX, name)
        if settings is not None:
            self._apply_preset(cast("dict[str, int | bool | str]", settings))

    def _save_current_as_preset(self, name: str) -> None:
        """Save the current settings as a named preset."""
        save_tool_preset(self.PRESET_KEY_PREFIX, name, self._collect_settings())
        self._refresh_preset_list()

    def _delete_preset(self, name: str) -> None:
        """Delete a named preset."""
        delete_tool_preset(self.PRESET_KEY_PREFIX, name)
        self._refresh_preset_list()
