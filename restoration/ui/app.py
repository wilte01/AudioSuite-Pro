"""Tkinter window for the Restoration (declip) tool.

Built on ``SuiteApp`` — the suite's one window shell — so the notebook, the
Processing and Results tabs, the run report and the worker hand-off are the
shell's, and this module supplies the declip settings panel, the run and its
wording.  The before/after audition row is the shell's ``audition_row``: the
run rewrites its sources in place, so Play Original keeps the snapshot the
mixin takes before the batch starts.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
Changed in 2.9.0: the window adopts ``SuiteApp`` (C1 stage 2, D34).  Its two
one-line tab delegates are gone, the run writes a report View Log can open, and
the worker publishes through the shell's queue instead of marshalling with
``root.after``; the run's settings are snapshotted on the Tk thread so the
worker reads no Tk variable.
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from queue import Queue
from tkinter import messagebox
from typing import Any, ClassVar

from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.styles import bootstrap_theme
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_presets import (
    delete_tool_preset,
    load_tool_preset,
    save_tool_preset,
)

from ..core.declipper import DEFAULT_MAX_RUN_MS, DEFAULT_THRESHOLD
from ..core.file_processor import run_declipping
from ..utils import cli_args
from . import setup_tab

logger = logging.getLogger(__name__)

DRY_RUN = "Dry Run"
LIVE_UPDATE = "Live Update"
DRIVER_TOOL_ID = "restoration"

#: The report a run leaves beside the folder it repaired; View Log opens it.
RUN_REPORT_DRY_RUN = "restoration_dry_run_log.txt"
RUN_REPORT_LIVE = "restoration_sync_log.txt"


class RestorationApp(SuiteApp):
    """Restoration (declip) application window."""

    title = "Restoration (Declip)"
    window_key = "restoration_window"
    program_name = DRIVER_TOOL_ID
    #: Kept for the guide registry's scan; the shell reads ``guide_name``.
    HELP_GUIDE = "Restoration_User_Guide.docx"
    guide_name = HELP_GUIDE
    completion_text = "Declip Complete!"
    #: Every file the run visits is attempted and the ones it rewrote are
    #: "repaired"; the report and the stats line both use that word.
    TAGGED_LABEL = "Repaired"
    processing_stats_text = "Processed: 0 | Repaired: 0 | Skipped: 0 | Errors: 0"
    #: The batch overwrites its sources, so the shared audition row can play
    #: the snapshot taken before the batch against the repaired file.
    audition_row = True

    #: Config-key prefix for the shared preset methods.  A ``ClassVar`` on the
    #: old base, so it must stay one here: an instance annotation is an
    #: incompatible override and mypy rejects it.
    PRESET_KEY_PREFIX: ClassVar[str] = DRIVER_TOOL_ID

    #: The manifest id the window has always declared; ``program_name`` above
    #: is the shell's copy of the same value.
    TOOL_ID: str = DRIVER_TOOL_ID

    #: Set from argv in ``__init__``.  The default keeps an ``object.__new__``
    #: test shell on the interactive (modal-warning) path.
    _launched_from_driver: bool = False
    #: Built by the shell from the Setup panel.
    _setup_frame: Any = None
    #: The run's folder and wording, snapshotted on the Tk thread by
    #: ``start_processing`` so the completion reads no Tk variable.
    _run_mode: str = ""
    _run_folder: str = ""
    _run_was_dry_run: bool = False

    def __init__(self, root: tk.Tk, *, apply_argv: bool = True) -> None:
        """Build the window, its variables and its worker pool.

        Args:
            root: The Tk root the window is built in.
            apply_argv: Whether to apply the Master-Driver handshake from
                ``sys.argv``.  A direct caller passes False.
        """
        self.folder_path: tk.StringVar = tk.StringVar()
        self.run_mode: tk.StringVar = tk.StringVar(value=DRY_RUN)
        self.threshold: tk.DoubleVar = tk.DoubleVar(value=DEFAULT_THRESHOLD)
        self.max_run: tk.IntVar = tk.IntVar(value=DEFAULT_MAX_RUN_MS)

        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        #: The worker grid's labels.  The processor writes the thread-safe
        #: wrappers; the Tk thread draws the plain variables.
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for worker in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(worker)

        #: Where the run's report goes; blank until a run starts, which makes
        #: View Log say so instead of opening the suite log.
        self._log_path: str = ""

        self._preset_refresh: Any = None

        self._launched_from_driver = apply_argv and cli_args.looks_like_driver_argv()

        super().__init__(root)
        if apply_argv:
            self._apply_cli_args(cli_args.parse())

        self.root.update_idletasks()

        if not self.folder_path.get():
            last: str = _suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Shell tabs ───────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder, the declip settings, the presets and the start."""
        widgets: dict[str, Any] = setup_tab.build(
            parent,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            threshold=self.threshold,
            max_run=self.max_run,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            preset_names=_suite_config.list_presets(self.TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
            driver_locked=self._launched_from_driver,
        )
        self._setup_frame = widgets["setup_frame"]
        self.start_btn = widgets["start_btn"]
        self._preset_refresh = widgets.get("refresh_preset_list")
        self.controls_panel = widgets["controls_panel"]

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self, parsed: Any) -> None:
        """Apply a parsed Master-Driver handshake onto the controls.

        Every route that writes a control has to reach the same widget the
        user's own edit would: a threshold or plateau width passed in argv and
        never applied here would leave the window showing the defaults while
        the run used the driver's values.

        Args:
            parsed: The per-tool ``cli_args.parse()`` dataclass.
        """
        if parsed.live_mode is not None:
            self.run_mode.set(LIVE_UPDATE if parsed.live_mode else DRY_RUN)
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        self._apply_tool_cli_options(parsed)

        if not parsed.folder_path:
            return

        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed,
            folder_var=self.folder_path,
            auto_start_func=self.start_processing,
        )
        if should_auto_start:
            self.root.after(1500, self.start_processing)

    def _apply_tool_cli_options(self, parsed: Any) -> None:
        """Mirror this tool's driver flags onto the Setup controls.

        Args:
            parsed: The per-tool ``cli_args.parse()`` dataclass.
        """
        if parsed.threshold:
            self.threshold.set(float(parsed.threshold))
        if parsed.run_ms:
            self.max_run.set(int(parsed.run_ms))

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        """Browse for a music directory, remembering the choice."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    # ── Run ───────────────────────────────────────────────────────────────────

    def _reset_progress_ui(self) -> None:
        """Reset the bar and the counters (must be called on the Tk thread)."""
        self.progress["value"] = 0
        self.stats_label.config(text=self.processing_stats_text)

    def _validate_start(self) -> str | None:
        """Reject a threshold or plateau width the DSP cannot honour.

        Returns:
            A message to show instead of starting, or None.
        """
        threshold = float(self.threshold.get())
        if not 0.0 < threshold <= 1.0:
            return "The clipping threshold must be greater than 0 and at most 1."
        if int(self.max_run.get()) < 1:
            return "The maximum plateau width must be at least 1 ms."
        return None

    def start_processing(self) -> None:
        """Validate the inputs, then launch the declip batch on a worker."""
        folder = self.folder_path.get().strip()
        if not folder:
            messagebox.showerror(
                "No Directory Selected",
                "Please select a music folder containing audio files.",
            )
            return
        if not os.path.isdir(folder):
            messagebox.showerror(
                "Directory Not Found",
                f"The selected folder does not exist:\n{folder}",
            )
            return
        message = self._validate_start()
        if message is not None:
            messagebox.showwarning(self.title, message)
            return

        threshold = float(self.threshold.get())
        max_run = int(self.max_run.get())
        is_dry_run = self.run_mode.get() == DRY_RUN
        self._run_mode = DRY_RUN if is_dry_run else LIVE_UPDATE
        self._run_was_dry_run = is_dry_run
        self._run_folder = folder
        self._log_path = os.path.join(
            folder, RUN_REPORT_DRY_RUN if is_dry_run else RUN_REPORT_LIVE
        )
        header = [
            "RESTORATION (DECLIP) REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Directory: {folder}\n",
            f"Clipping threshold: {threshold:.2f} of the file's own peak\n",
            f"Max plateau width: {max_run} ms\n",
            "=" * 60 + "\n",
        ]

        _suite_config.save_last_directory(folder)
        self.start_btn.config(state=tk.DISABLED)
        self.notebook.select(self.processing_frame)
        self._reset_progress_ui()
        self.overall_status.set("Running...")
        self.prepare_in_place_audition(folder, SUPPORTED_EXTENSIONS)
        self._start_worker(
            self._run_batch, (folder, is_dry_run, threshold, max_run, header)
        )

    def _run_batch(
        self,
        folder: str,
        is_dry_run: bool,
        threshold: float,
        max_run: int,
        header: list[str],
    ) -> None:
        """Run the declip batch on the worker thread the shell started.

        Args:
            folder: The directory the run repairs in place.
            is_dry_run: Whether the run writes nothing.
            threshold: The clipping threshold, snapshotted on the Tk thread.
            max_run: The maximum plateau width in ms, likewise.
            header: The report header this run started with.
        """
        run_declipping(
            folder,
            is_dry_run,
            threshold,
            max_run,
            self._safe_slot_vars,
            self.slot_queue,
            on_progress=self._on_progress,
            on_complete=lambda **payload: self._finish_run(header=header, **payload),
            on_error=self._on_error,
        )

    # ── Callbacks (queued from the batch's thread — no widget writes) ──

    def _on_progress(
        self,
        processed: int,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
        """Queue one progress tick for the Tk thread's poller.

        Called from the batch's own thread, so it only queues; the tick is
        written by ``_dispatch_ui_message`` (AGENTS.md).

        Args:
            processed: Files finished so far.
            total: Files the run will attempt.
            succeeded: Files repaired (or would be, in a dry run) so far.
            skipped: Files left alone so far.
            errors: Files that could not be processed so far.
            display_text: The per-file line the processor published.
            **_extra: The other progress fields the processor publishes.
        """
        self._ui_updates.put(
            (
                "progress",
                processed,
                total,
                succeeded,
                skipped,
                errors,
                display_text,
            )
        )

    def _on_error(self, message: str) -> None:
        """Queue a fatal run error for the Tk thread's poller.

        The processor publishes this from the batch's thread and the shell's
        handler raises a dialog, so it must run on the Tk thread only.

        Args:
            message: The user-facing message the processor published.
        """
        self._ui_updates.put(("error", message))

    def _dispatch_ui_message(self, message: tuple[Any, ...]) -> None:
        """Render one queued message on the Tk thread."""
        kind = message[0]
        if kind == "progress":
            _, processed, total, succeeded, skipped, errors, display_text = message
            self._render_progress_standard(processed, total, display_text)
            self.stats_label.config(
                text=(
                    f"Processed: {processed} | {self.TAGGED_LABEL}: {succeeded} "
                    f"| Skipped: {skipped} | Errors: {errors}"
                )
            )
        elif kind == "error":
            _, text = message
            super()._on_error(text)
        elif kind == "complete":
            _, total, succeeded, skipped, errors, duration_secs = message
            self._render_finish(total, succeeded, skipped, errors, duration_secs)

    def _finish_run(
        self,
        header: list[str],
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        **_extra: Any,
    ) -> None:
        """Write this run's report, then queue the Results update.

        Runs on the batch's own thread: the report is written here, and every
        widget write is queued for the Tk poller.  The six declared fields are
        required, so a payload that drops one raises with its name rather than
        rendering a plausible zero; ``**_extra`` absorbs the fields this render
        does not read (the batch also publishes ``processed``).

        Args:
            header: Report header lines for this run.
            total: Files the run visited.
            succeeded: Files repaired (or would be, in a dry run).
            skipped: Files left alone.
            errors: Files that could not be processed.
            duration_secs: Wall-clock run time.
            log_entries: The per-file report lines.
            **_extra: The other completion fields the processor publishes; a
                handler that rejected one would abort the completion, so the
                report would never be written.
        """
        self._write_run_report_standard(
            header=header,
            log_entries=log_entries,
            rows=(),
            total=total,
            tagged=succeeded,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
        )
        self._ui_updates.put(
            ("complete", total, succeeded, skipped, errors, duration_secs)
        )

    def _render_finish(
        self,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Render the finished run (must run on the main thread).

        Args:
            total: Files the run visited.
            succeeded: Files repaired (or would be, in a dry run).
            skipped: Files left alone.
            errors: Files that could not be processed.
            duration_secs: Wall-clock run time.
        """
        self.summary_label.config(
            text=(
                f"Total: {total} files\n"
                f"{self.TAGGED_LABEL}: {succeeded}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        )
        self._render_audition()
        self.render_completion(duration_secs=duration_secs, output_dir=self._run_folder)
        if self.auto_end_var.get():
            self.root.after(2000, self.root.destroy)

    def _render_audition(self) -> None:
        """Point the audition row at the half of the run it can play.

        A dry run writes nothing, so Play Result has nothing to open; a live
        run overwrote the source, so the snapshot captured at the start is the
        "original" half and the source path is the result.
        """
        if self._run_was_dry_run:
            self.set_audition_state(
                self._audition_original,
                None,
                "Dry Run — nothing written. Play Result is unavailable.",
            )
        elif self._audition_original is not None and self._audition_result is not None:
            self.set_audition_state(
                self._audition_original,
                self._audition_result,
                f"Audition ready — {self._audition_result.name} (original vs result)",
            )

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        """Read the settings a preset stores.

        Returns:
            The settings, keyed as this tool's presets have always been.
        """
        return {
            "threshold": float(self.threshold.get()),
            "max_run": int(self.max_run.get()),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        """Apply a stored preset onto the controls.

        Args:
            settings: The dict ``_collect_settings`` produced.
        """
        if "threshold" in settings:
            self.threshold.set(float(settings["threshold"]))
        if "max_run" in settings:
            self.max_run.set(int(settings["max_run"]))
        if "run_mode" in settings:
            self.run_mode.set(str(settings["run_mode"]))

    def _on_preset_selected(self, name: str) -> None:
        """Load a named preset and apply its settings."""
        settings = load_tool_preset(self.PRESET_KEY_PREFIX, name)
        if settings is not None:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        """Save the current settings as a named preset."""
        save_tool_preset(self.PRESET_KEY_PREFIX, name, self._collect_settings())
        if self._preset_refresh is not None:
            self._preset_refresh()

    def _delete_preset(self, name: str) -> None:
        """Delete a named preset."""
        delete_tool_preset(self.PRESET_KEY_PREFIX, name)
        if self._preset_refresh is not None:
            self._preset_refresh()


def main() -> None:
    """Standalone entry point: create the Tk root and run the window."""
    root = tk.Tk()
    bootstrap_theme()
    app = RestorationApp(root)
    app.root.mainloop()
