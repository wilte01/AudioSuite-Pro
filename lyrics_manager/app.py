"""
app.py
LyricsManagerApp — thin orchestrator that wires UI, core logic, and utilities together.
Contains no business logic itself; it only coordinates.

Changed in 1.4.0: the saved worker default, slot grid and report header all
resolve through ``default_max_workers()`` / ``DEFAULT_MAX_WORKERS`` (PLAN D56);
an over-grid typed count is logged rather than shown when unattended (D70).

Changed in 2.9.0: the source-folder opener is the shared mixin helper (A1).

Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, the sixth window of
D8's wave 2), so the shell owns the Help bar and the Processing and Results
tabs; this tool keeps its Setup panel, its ``Tagged/Updated`` summary wording
and its per-mode completion heading. The report and the Results panel are
written here now that the window no longer inherits ``AnalysisTagToolApp``, and
the presets keep their existing keys through the shared ``ui_presets`` store.
The run's mode is snapshotted on the main thread in ``start_processing``, so the
completion never reads a Tk variable off the Tk thread.

Changed in 2.9.0: the run report's ``SUMMARY:`` footer is
``audio_suite_shared.run_report.summary_lines``, the one implementation
every window writes with (D36).
Changed in 2.9.0: the preset trio (select, save, delete) is the shell's,
so this window keeps only its own settings mapping (D58).
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox
from typing import Any, ClassVar, cast

from audio_suite_shared import suite_config as _suite_config
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
from audio_suite_shared.run_report import summary_lines
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_common import cap_typed_workers

from .core import file_processor
from .core.providers import get_provider
from .ui import setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "lyrics_manager"


class LyricsManagerApp(SuiteApp):
    """Lyrics Manager application GUI."""

    title = "Lyrics Manager"
    window_key = "lyrics_manager_window"
    program_name = TOOL_ID
    #: Kept for the guide registry's scan; the shell reads ``guide_name``.
    HELP_GUIDE: str = "Lyrics_Manager_User_Guide.docx"
    guide_name = HELP_GUIDE
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" 1. Setup ", " 2. Processing ", " 3. Results ")

    #: Word used in the report for the processed-but-neither-skipped-nor-
    #: erroring files.
    TAGGED_LABEL: str = "Tagged/Updated"
    #: Results-tab completion captions, by run mode.
    DRY_COMPLETE_LABEL: str = "Lyric Lookup Complete!"
    LIVE_COMPLETE_LABEL: str = "Lyrics Tagging Complete!"
    #: The heading the tab shows before a run; a finished run replaces it with
    #: the wording for its mode, which starts here.
    completion_text: str = DRY_COMPLETE_LABEL
    #: The preset keys this tool has always written (``lyrics_preset_<name>``).
    PRESET_KEY_PREFIX: ClassVar[str] = "lyrics"

    #: Set from argv in ``__init__``.  The default keeps an ``object.__new__``
    #: test shell on the interactive (modal-warning) path.
    _launched_from_driver: bool = False
    #: Set by ``_run_fetch``; the Results tab's Open Folder target.
    _dir_path: str = ""

    def __init__(self, root: tk.Tk) -> None:
        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path: tk.StringVar = tk.StringVar()
        self.run_mode: tk.StringVar = tk.StringVar(value="Dry Run")
        self.provider: tk.StringVar = tk.StringVar(
            value=str(_suite_config.load_value("lyrics_provider", "lrclib"))
        )
        self.request_timeout: tk.StringVar = tk.StringVar(
            value=str(_suite_config.load_value("lyrics_request_timeout", 10.0))
        )
        self.skip_existing: tk.BooleanVar = tk.BooleanVar(
            value=bool(_suite_config.load_value("lyrics_skip_existing", True))
        )
        self.plain_fallback: tk.BooleanVar = tk.BooleanVar(
            value=bool(_suite_config.load_value("lyrics_plain_fallback", True))
        )
        saved_parallel: bool = cast(
            bool, _suite_config.load_value("lyrics_parallel_mode", False)
        )
        saved_workers: int = int(
            cast(
                str,
                _suite_config.load_value("lyrics_max_workers", default_max_workers()),
            )
        )
        self.parallel_mode: tk.BooleanVar = tk.BooleanVar(value=saved_parallel)
        self.max_workers: tk.IntVar = tk.IntVar(value=saved_workers)

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

        super().__init__(root)

        self._refresh_preset_names()

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
        """Emit the run controls, the lyric source and the preset row."""
        widgets: dict[str, Any] = setup_tab.build(
            parent,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            provider=self.provider,
            request_timeout=self.request_timeout,
            skip_existing=self.skip_existing,
            plain_fallback=self.plain_fallback,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
            parallel_mode=self.parallel_mode,
            max_workers=self.max_workers,
            on_preset_selected=self.use_preset,
            on_save_preset=self.store_preset,
            on_delete_preset=self.remove_preset,
        )
        self.start_btn = widgets["start_btn"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self.controls_panel = widgets["controls_panel"]

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        """Parse and apply any command-line arguments supplied by the Master Driver."""
        parsed = cli_args.parse()

        # Mirror the inherited driver arguments onto the Run Controls panel
        # before any early return so the display always reflects exactly what
        # the Master Driver passed, then the tool's own options.
        self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)
        self.provider.set(parsed.provider)
        self.request_timeout.set(str(parsed.request_timeout))
        self.skip_existing.set(parsed.skip_existing)
        self.plain_fallback.set(parsed.plain_fallback)

        if not parsed.folder_path:
            return

        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed, folder_var=self.folder_path, auto_start_func=self.start_processing
        )

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        """Browse for a music directory with standard error handling."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _open_folder(self) -> None:
        """Open the source folder in the system file manager."""
        self._open_source_folder_standard()

    def start_processing(self) -> None:
        """Validate inputs then launch the background lookup thread."""
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

            provider_name: str = self.provider.get().strip()
            if not provider_name:
                messagebox.showerror(
                    "No Lyric Source",
                    "Please select a lyric source provider.",
                )
                return

            try:
                get_provider(provider_name)
            # Changed in 2.4.1: BLE001 triage (WP-7 of
            # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
            # BLE001 boundary: an unknown source is named in a dialog
            except Exception as exc:  # noqa: BLE001
                mapped = map_to_audio_error(exc, context={"provider": provider_name})
                messagebox.showerror(
                    "Unknown Lyric Source",
                    f"'{provider_name}' is not a registered lyric source.\n\n"
                    f"{user_message_for(mapped)}",
                )
                return

            try:
                timeout: float = float(self.request_timeout.get().strip())
            except ValueError:
                messagebox.showerror(
                    "Invalid Timeout",
                    "Request Timeout must be a number of seconds.",
                )
                return
            if timeout <= 0:
                messagebox.showerror(
                    "Invalid Timeout",
                    "Request Timeout must be greater than zero.",
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

            # Persist settings
            _suite_config.save_value("lyrics_provider", self.provider.get())
            _suite_config.save_value("lyrics_request_timeout", timeout)
            _suite_config.save_value("lyrics_skip_existing", self.skip_existing.get())
            _suite_config.save_value("lyrics_plain_fallback", self.plain_fallback.get())
            _suite_config.save_value("lyrics_parallel_mode", self.parallel_mode.get())
            _suite_config.save_value("lyrics_max_workers", workers)

            # All validations passed — start processing.
            self.start_btn.config(state="disabled")
            self.progress["value"] = 0
            self.stats_label.config(text=self.processing_stats_text)
            self.notebook.select(self.processing_frame)
            self.overall_status.set("Looking up lyrics...")
            is_dry_run: bool = self.run_mode.get() == "Dry Run"
            parallel: bool = self.parallel_mode.get()
            # Snapshot the mode on the main thread: the completion renders from
            # it, and the worker must not call .get() (see _run_fetch).
            self._run_mode = "Dry Run" if is_dry_run else "Live Update"
            logger.info(
                "start_processing: folder=%s dry_run=%s provider=%s timeout=%s "
                "skip_existing=%s plain_fallback=%s parallel=%s workers=%d",
                folder,
                is_dry_run,
                provider_name,
                timeout,
                self.skip_existing.get(),
                self.plain_fallback.get(),
                parallel,
                workers,
            )

            threading.Thread(
                target=self._run_fetch,
                args=(
                    folder,
                    is_dry_run,
                    provider_name,
                    timeout,
                    self.skip_existing.get(),
                    self.plain_fallback.get(),
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

    @handle_audio_errors(reraise=False, context="lyrics_manager_app_run")
    def _run_fetch(
        self,
        dir_path: str,
        is_dry_run: bool,
        provider_name: str,
        request_timeout: float,
        skip_existing: bool,
        plain_fallback: bool,
        parallel_mode: bool = False,
        max_workers: int | None = None,
    ) -> None:
        """Background thread: delegate to file_processor.run_fetch."""
        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            "lyrics_dry_run_log.txt" if is_dry_run else "lyrics_sync_log.txt",
        )
        # Defensive: a preset or restored setting can bypass start_processing.
        requested_workers = (
            max_workers if max_workers is not None else default_max_workers()
        )
        effective_workers = cap_workers_to_slot_grid(
            requested_workers, self._safe_slot_vars
        )

        header: list[str] = [
            "LYRIC LOOKUP REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Provider: {provider_name}\n",
            f"Request Timeout: {request_timeout} seconds\n",
            f"Skip Existing Lyrics: {'Yes' if skip_existing else 'No'}\n",
            f"Store Unsynced Lyrics: {'Yes' if plain_fallback else 'No'}\n",
            f"Parallel: {'Yes' if parallel_mode else 'No'}\n",
            f"Workers: {effective_workers}\n",
            "=" * 60 + "\n",
        ]

        with active_batch(TOOL_ID, "tag_edit"):
            file_processor.run_fetch(
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                provider_name=provider_name,
                request_timeout=request_timeout,
                skip_existing=skip_existing,
                plain_fallback=plain_fallback,
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
        **_extra: Any,
    ) -> None:
        """Write the run report, then hand the Results update to the Tk thread.

        Runs on the worker thread before the Results update is scheduled, so
        neither a damaged Tk nor an unwritable log can suppress the report.

        Args:
            header: Report header lines for this run.
            total: Files the run set out to look up.
            processed: Files it finished attempting.
            skipped: Files that already had lyrics (or no match to store).
            errors: Files that could not be looked up or tagged.
            duration_secs: Wall-clock run time.
            log_entries: The per-file log lines.
            **_extra: The other tool-specific completion fields the processor
                always publishes (``skipped_files``, ``error_files``).  They
                feed the CLI's ``--json`` output and are ignored here: rejecting
                one aborted the whole completion, so no report was written and
                the Results tab never appeared.
        """
        tagged = processed - skipped - errors

        summary: list[str] = summary_lines(
            total=total,
            tagged=tagged,
            tagged_label=self.TAGGED_LABEL,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
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
        )

    def _update_ui_on_complete(
        self,
        total: int,
        tagged: int,
        skipped: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Render the finished run (must run on the main thread)."""
        text: str = (
            f"Total: {total} files\n"
            f"{self.TAGGED_LABEL}: {tagged}\n"
            f"Skipped: {skipped}\n"
            f"Errors: {errors}"
        )
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
            "provider": self.provider.get(),
            "request_timeout": self.request_timeout.get(),
            "skip_existing": self.skip_existing.get(),
            "plain_fallback": self.plain_fallback.get(),
            "parallel_mode": self.parallel_mode.get(),
            "max_workers": self.max_workers.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, int | bool | str]) -> None:
        """Apply a preset dict to the UI variables."""
        self.provider.set(str(settings.get("provider", "lrclib")))
        self.request_timeout.set(str(settings.get("request_timeout", 10.0)))
        self.skip_existing.set(bool(settings.get("skip_existing", True)))
        self.plain_fallback.set(bool(settings.get("plain_fallback", True)))
        self.parallel_mode.set(bool(settings.get("parallel_mode", False)))
        self.max_workers.set(int(settings.get("max_workers", default_max_workers())))
        self.run_mode.set(str(settings.get("run_mode", "Dry Run")))
