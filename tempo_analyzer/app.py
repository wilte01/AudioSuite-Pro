"""
app.py
TempoAnalyzerApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

The scheme-change chain lives here because it touches three layers:
  1. Update self._active_markings  (core)
  2. Save preference to config     (utils)
  3. Redraw reference table        (ui — via injected callable)

Changed in 1.2.0: records tracks with no BPM tag to derive a marking from as
a run note, so a batch report says so instead of only the tool's own log.
Changed in 1.4.0: the worker slot grid is sized from ``DEFAULT_MAX_WORKERS``
instead of a literal 4 (PLAN D56).

Changed in 1.4.1: ``_on_complete`` and ``_on_progress`` accept ``**_extra: Any``,
so a payload field the processor adds (D112) is ignored instead of aborting an
otherwise-finished run; ``tests/test_callback_payload_contract.py`` locks the
completion, progress and error seams.

Changed in 2.7.0: the blind-``except`` boundary is named for the BLE001 triage
(WP-7 of ``PLAN_2026-11-03_2.4.1_stop_the_drift.md``, section 10).

Changed in 2.9.0: the source-folder opener is the shared mixin helper (A1).
Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, the third window of
D8's wave 2), so the shell owns the Help bar and the Processing and Results
tabs; this tool keeps its Setup panel and its per-run completion wording. The
run's folder, mode, scheme and markings are snapshotted on the main thread in
``start_processing``, so the worker and the completion never read a Tk variable
off the Tk thread.
"""

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, Callable

from audio_suite_shared import suite_config
from audio_suite_shared.audio_formats import is_supported_format
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.run_outcome import record_caveats, shortfall
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars

from .core import file_processor
from .core.tempo_schemes import DEFAULT_SCHEME, TEMPO_SCHEMES, MarkingList
from .ui import setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)
TOOL_ID = "tempo_analyzer"

#: The Master Driver keys this tool's batch step — and therefore its run note
#: — by the manifest id, which is shorter than the window key above.
DRIVER_TOOL_ID = "tempo"


class TempoAnalyzerApp(SuiteApp):
    """Tempo Analyzer application GUI."""

    title = "Tempo Analyzer & Tagger"
    window_key = "tempo_analyzer_window"
    program_name = TOOL_ID
    #: Kept for the guide registry's scan; the shell reads ``guide_name``.
    HELP_GUIDE = "Tempo_Analyzer_User_Guide.docx"
    guide_name = HELP_GUIDE
    # The heading the Results tab opens with; a finished run sets its own.
    completion_text = "Tempo Analysis Complete!"

    def __init__(self, root: tk.Tk):
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
        self.auto_end: bool = False
        # The run's inputs, snapshotted by start_processing on the Tk thread.
        self._run_path: str = ""
        self._run_mode: str = ""
        self._run_scheme: str = ""
        self._run_markings: MarkingList = TEMPO_SCHEMES[saved]

        # ── Worker slot pool ──────────────────────────────────────────────────
        # Built before super().__init__: the shell renders the grid from it.
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # The Setup tab replaces this while the shell builds it.
        self._update_reference: Callable[..., Any] = lambda _: None

        super().__init__(root)

        # Populate reference table with initial scheme
        self._update_reference(self._active_markings)

        # ── Apply CLI arguments ───────────────────────────────────────────────
        self._apply_cli_args()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Shell tabs ────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the run controls, the scheme selector and the reference table."""
        widgets = setup_tab.build(
            parent,
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
        self.controls_panel = widgets["controls_panel"]

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

    def _open_folder(self) -> None:
        """Open the source folder since Tempo Analyzer processes files in-place."""
        self._open_source_folder_standard()

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
            self.progress["value"] = 0
            self.notebook.select(self.processing_frame)
            self.overall_status.set("Analyzing tempo markings...")

            # Snapshot the run's inputs on the main thread: the worker and the
            # completion must never call .get() off the Tk thread (see _run).
            self._run_path = folder
            self._run_mode = self.run_mode.get()
            self._run_scheme = self.tempo_scheme.get()
            self._run_markings = self._active_markings

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
        """Analyse the folder on a worker thread.

        Thread safety: this runs off the Tk main thread, so it must not touch
        a widget or call ``.get()`` on a Tk variable. The inputs are the
        snapshot ``start_processing`` took on the main thread, and every UI
        write goes through ``root.after(0, ...)``.
        """
        dir_path = self._run_path
        is_dry_run = self._run_mode == "Dry Run"
        scheme_name = self._run_scheme
        markings = self._run_markings

        self._log_path = os.path.join(
            dir_path,
            "tempo_dry_run_log.txt" if is_dry_run else "tempo_analysis_log.txt",
        )

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
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
        """Called from worker threads — schedule UI update on main thread."""
        self.root.after(
            0, self._update_progress_ui, processed, total, skipped, errors, display_text
        )

    def _update_progress_ui(
        self, processed: int, total: int, skipped: int, errors: int, display_text: str
    ) -> None:
        """Update progress UI elements (must run on main thread)."""
        self._render_progress_standard(processed, total, display_text)
        self.stats_label.config(
            text=f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}"
        )

    def _on_complete(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        **_extra: Any,
    ) -> None:
        """Called on background thread — file I/O here, then schedule UI on
        main thread."""
        self._record_run_note(total=total, skipped=skipped, errors=errors)

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
            duration_secs,
        )

        if self.auto_end:
            all_entries.append("\n[Auto End enabled - closing in 2 seconds...]\n")
            try:
                with open(self._log_path, "w", encoding="utf-8") as f:
                    f.writelines(all_entries)
            except Exception as _exc:  # noqa: BLE001 - log rewrite before close
                logger.warning(
                    "Could not rewrite log after auto-end: %s", _exc, exc_info=True
                )
            self.root.after(2000, self.root.destroy)

    def _record_run_note(self, *, total: int, skipped: int, errors: int) -> None:
        """Record the tracks this run could not derive a tempo marking for.

        A track is skipped when it carries no BPM tag (or no tag block at all),
        so the marking the run exists to compute has nothing to be derived
        from.  A clean run records nothing, which clears any earlier note.

        Args:
            total: Files the run attempted.
            skipped: Files with no BPM tag to derive a marking from.
            errors: Files whose tags could not be read or written.
        """
        record_caveats(
            DRIVER_TOOL_ID,
            shortfall(skipped, total, "track", "had no BPM tag to derive a tempo from")
            if skipped
            else "",
            shortfall(errors, total, "track", "could not be analyzed")
            if errors
            else "",
        )

    def _update_ui_on_complete(
        self,
        total: int,
        analysed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Render the finished run (must run on the main thread)."""
        self.summary_label.config(
            text=f"Total: {total} files\n"
            f"Tagged/Analyzed: {analysed}\n"
            f"Skipped: {skipped}\n"
            f"Errors: {errors}"
        )
        # This window has always labelled a finished run by its mode; the shell
        # renders ``completion_text``, so point it at this run's wording first.
        self.completion_text = (
            "Analysis Complete!"
            if self._run_mode == "Dry Run"
            else "Tempo Tagging Complete!"
        )
        self.render_completion(duration_secs=duration_secs, output_dir=self._run_path)
