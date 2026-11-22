# Changed in 2.6.0: exact-duplicate mode (F-E9) — the Setup control, the driver
# flag that mirrors it, and the run it configures.
# Changed in 2.4.0: duplicate dispositions and ASX stubs.
"""Tkinter window for the Duplicate Finder.

The window is a ``SuiteApp`` on the suite's three standard tabs, with a
``BaseSetupFrame`` Setup tab: the Run Controls strip supplies the source row,
the shared browse dialog and the Mode combobox, so a driven launch is locked and
the driver's Auto Start/Auto End are honoured.  The shell owns the Help bar and
the Processing and Results tabs; this tool keeps its Setup panel, its scan
report and its preset store.  The scan runs through
``core.file_processor.run_duplicate_scan`` — the ``run_*`` entry point taking
``on_progress`` / ``on_complete`` / ``on_error`` — and each run writes its report
into the folder it scanned, which is what the Results tab's View Log opens.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.

Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, the first window of
D8's wave 3), so the shell owns the Help bar and the Processing and Results tabs
and this tool keeps its Setup panel.  The scan report and the Results panel are
written here now that the window no longer inherits ``AnalysisTagToolApp``: the
report is serialised on the run's thread and the widget writes are marshalled,
and the run's mode, disposition and folder are snapshotted on the Tk thread in
``start_processing`` so the completion never reads a Tk variable off it.  Every
callback the scan publishes — progress, the run error and the completion — is a
message on a ``SimpleQueue`` that a poller the Tk thread starts drains, because
``_run_scan`` is a raw ``threading.Thread`` and may not call ``root.after`` or a
widget at all.  The drain passes the tick's line straight through, and the run
note reads the disposition ``start_processing`` snapshotted rather than a Tk
variable.  The presets keep their existing keys through the shared
``ui_presets`` store, and View Log / Open Folder are the shell's.

Changed in 2.9.0: that poller is the shared ``event_pump.pump_events``, so the
drain loop and its finished-run drain are the suite's one implementation (B2).

Changed in 2.9.0: the window keeps no tick id.  It has no close handler, so
nothing could ever cancel the pending tick, and a destroyed root drops its
``after`` callbacks itself (D30).
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from queue import SimpleQueue
from tkinter import messagebox
from typing import Any, ClassVar

from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.event_pump import pump_events
from audio_suite_shared.exceptions import handle_audio_errors, map_to_audio_error
from audio_suite_shared.run_outcome import record_caveats, shortfall
from audio_suite_shared.styles import bootstrap_theme
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.ui_presets import (
    delete_tool_preset,
    load_tool_preset,
    save_tool_preset,
)

from ..core.disposition import (
    DEFAULT_DISPOSITION,
    label_for,
    normalize,
    uses_trash,
)
from ..core.file_processor import (
    UNDO_OPERATION,
    default_quarantine_dir,
    run_duplicate_scan,
)
from ..core.models import DEFAULT_EXACT_MODE, DEFAULT_THRESHOLD, ScanSettings
from ..utils import cli_args
from . import setup_tab

logger = logging.getLogger(__name__)

#: Manifest id the Master Driver keys this tool's batch step by; a note recorded
#: under any other string is never read (``tests/test_run_outcome_contract.py``).
DRIVER_TOOL_ID = "duplicate_finder"

#: The run reports the window writes into the folder it scanned, in the shape
#: every peer uses.  The literal lives here once: the user guide quotes the
#: names and ``tests/test_guide_claims.py`` requires a quoted name to exist in
#: the code that writes it.
RUN_REPORT_DRY_RUN = "duplicate_finder_dry_run_log.txt"
RUN_REPORT_LIVE = "duplicate_finder_sync_log.txt"

DRY_RUN = "Dry Run"
LIVE_UPDATE = "Live Update"


class DuplicateFinderApp(SuiteApp):
    """Tkinter window for the Duplicate Finder."""

    title = "Duplicate Finder"
    window_key = "duplicate_finder_window"
    program_name = DRIVER_TOOL_ID
    #: Kept for the guide registry's scan; the shell reads ``guide_name``.
    HELP_GUIDE = "Duplicate_Finder_User_Guide.docx"
    guide_name = HELP_GUIDE
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" 1. Setup ", " 2. Processing ", " 3. Results ")

    #: Nothing is tagged or analysed here: every file is fingerprinted and then
    #: either grouped or kept, so the shared "processed" count is "files scanned".
    TAGGED_LABEL: str = "Files scanned"
    DRY_COMPLETE_LABEL: str = "Duplicate Scan Complete!"
    LIVE_COMPLETE_LABEL: str = "Duplicate Handling Complete!"
    #: The heading the tab shows before a run; a finished run replaces it with
    #: the wording for its mode, which starts here.
    completion_text: str = DRY_COMPLETE_LABEL

    #: Config-key prefix for the shared preset methods.  A ``ClassVar`` on the
    #: old base, so it must stay one here: an instance annotation is an
    #: incompatible override and mypy rejects it.
    PRESET_KEY_PREFIX: ClassVar[str] = DRIVER_TOOL_ID

    #: The manifest id the window has always declared (tests and the undo GUI
    #: read it); ``program_name`` above is the shell's copy of the same value.
    TOOL_ID: str = DRIVER_TOOL_ID

    #: Messages the scan's thread queues for the Tk poller; built per run.
    _ui_updates: SimpleQueue[tuple[Any, ...]]
    #: The scan's thread; the poller stops when it ends.
    _run_thread: threading.Thread | None = None

    #: Set from argv in ``__init__``.  The default keeps an ``object.__new__``
    #: test shell on the interactive (modal-warning) path.
    _launched_from_driver: bool = False
    #: Read by the completion, which closes the window when it is set.
    auto_end: bool = False
    #: Built by the shell from the Setup panel.
    _setup_frame: Any = None
    #: The run's mode, disposition and folder, snapshotted on the Tk thread by
    #: ``start_processing`` so the completion reads no Tk variable.
    _run_mode: str = ""
    _run_disposition: str = ""
    _run_folder: str = ""

    def __init__(self, root: tk.Tk, *, apply_argv: bool = True) -> None:
        """Build the window, its variables and its run controls.

        Args:
            root: The Tk root the window is built in.
            apply_argv: Whether to apply the Master-Driver handshake from
                ``sys.argv``.  A direct caller passes False.
        """
        self.folder_path: tk.StringVar = tk.StringVar()
        self.run_mode: tk.StringVar = tk.StringVar(value=DRY_RUN)
        self.threshold: tk.DoubleVar = tk.DoubleVar(value=DEFAULT_THRESHOLD)
        self.quarantine_dir: tk.StringVar = tk.StringVar()
        self.disposition: tk.StringVar = tk.StringVar(value=DEFAULT_DISPOSITION)
        self.exact_mode: tk.StringVar = tk.StringVar(value=DEFAULT_EXACT_MODE)

        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

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
        """Emit the folder, the similarity settings, the presets and the start."""
        widgets: dict[str, Any] = setup_tab.build(
            parent,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            threshold=self.threshold,
            quarantine_dir=self.quarantine_dir,
            disposition=self.disposition,
            exact_mode=self.exact_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse_folder,
            on_browse_quarantine=self._browse_quarantine_folder,
            on_disposition_changed=self._set_disposition,
            on_start=self.start_processing,
            preset_names=_suite_config.list_presets(self.TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
            driver_locked=self._launched_from_driver,
        )
        self.start_btn = widgets["start_btn"]
        self._preset_refresh = widgets.get("refresh_preset_list")
        self._setup_frame = widgets.get("setup_frame")
        self.controls_panel = widgets["controls_panel"]
        self._set_disposition(DEFAULT_DISPOSITION)

    # ── CLI handling ───────────────────────────────────────────────────

    def _apply_cli_args(self, parsed: Any) -> None:
        """Apply a parsed Master-Driver handshake onto the controls.

        Every route that writes a control has to reach the same widget the
        user's own edit would: a threshold or quarantine folder passed in argv
        and never applied here would leave the window showing the defaults
        while the run used the driver's values.

        Args:
            parsed: The per-tool ``cli_args.parse()`` dataclass.
        """
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
        if parsed.quarantine_dir:
            self.quarantine_dir.set(parsed.quarantine_dir)
        if parsed.exact_mode:
            self.exact_mode.set(parsed.exact_mode)
        self._set_disposition(parsed.disposition)
        self.auto_end = bool(parsed.auto_end)

    # ── User actions ──────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        """Browse for a music directory, remembering the choice."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _browse_quarantine_folder(self) -> None:
        """Browse for the quarantine folder, remembering the choice."""
        self._browse_folder_standard(
            title="Select Quarantine Folder",
            path_variable=self.quarantine_dir,
            save_last_dir=False,
        )

    def _set_disposition(self, value: str) -> None:
        """Apply a disposition everywhere the choice is reflected.

        Every route that writes the value — the combobox event, a preset load
        and the driver argv — calls this one function, so the variable and the
        dependent controls cannot disagree.

        Args:
            value: The selected disposition (raw or an alias).
        """
        canonical = normalize(value)
        self.disposition.set(canonical)
        frame = getattr(self, "_setup_frame", None)
        if frame is not None:
            frame.apply_disposition(canonical)

    # ── Run ─────────────────────────────────────────────────────────────

    def _reset_progress_ui(self) -> None:
        """Reset the bar and the counters (must be called on the Tk thread)."""
        self.progress["value"] = 0
        self.stats_label.config(text=self.processing_stats_text)

    def start_processing(self) -> None:
        """Validate the inputs, then launch the scan on a worker thread."""
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

        threshold = float(self.threshold.get())
        if not 0.0 < threshold <= 1.0:
            messagebox.showerror(
                "Invalid Threshold",
                "The similarity threshold must be greater than 0 and at most 1.",
            )
            return

        dry_run = self.run_mode.get() == DRY_RUN
        disposition = normalize(self.disposition.get())
        quarantine = ""
        if disposition == DEFAULT_DISPOSITION:
            quarantine = self.quarantine_dir.get().strip() or default_quarantine_dir(
                folder
            )
            if not dry_run and os.path.normcase(os.path.abspath(quarantine)) == (
                os.path.normcase(os.path.abspath(folder))
            ):
                messagebox.showerror(
                    "Invalid Quarantine Folder",
                    "The quarantine folder cannot be the folder being scanned.",
                )
                return

        if not dry_run and uses_trash(disposition) and not self._launched_from_driver:
            if not messagebox.askyesno(
                "Remove duplicates?",
                f"{label_for(disposition)} sends every duplicate to the "
                "Recycle Bin. The kept copy is never modified. Continue?",
            ):
                return

        self._log_path = os.path.join(
            folder, RUN_REPORT_DRY_RUN if dry_run else RUN_REPORT_LIVE
        )
        # Snapshot what the completion renders from, on the Tk thread: the
        # worker and its handler must not call .get().
        self._run_mode = self.run_mode.get()
        self._run_disposition = disposition
        self._run_folder = folder
        self.start_btn.config(state="disabled")
        self.notebook.select(self.processing_frame)
        self.file_listbox.delete(0, tk.END)
        self._reset_progress_ui()
        self.overall_status.set("Scanning...")
        logger.info(
            "start_processing: folder=%s dry_run=%s threshold=%.2f",
            folder,
            dry_run,
            threshold,
        )

        # A fresh queue per run: the poller drains it and stops with the run's
        # thread, so no message from an earlier run can reach a row.
        self._ui_updates = SimpleQueue()
        self._run_thread = threading.Thread(
            target=self._run_scan,
            args=(
                folder,
                dry_run,
                threshold,
                quarantine,
                disposition,
                str(self.exact_mode.get()),
            ),
            daemon=True,
        )
        self._run_thread.start()
        self._poll_ui_updates()

    @handle_audio_errors(reraise=False, context="duplicate_finder_app_run")
    def _run_scan(
        self,
        folder: str,
        is_dry_run: bool,
        threshold: float,
        quarantine: str,
        disposition: str,
        exact_mode: str,
    ) -> None:
        """Background thread: run the scan inside this run's undo batch.

        The report's header lines come from the processor's own payload rather
        than a second copy built here: two sources for one header drift, and
        the payload's version is the one the CLI prints.

        Args:
            folder: The directory to scan.
            is_dry_run: Whether the run may move files.
            threshold: Bit-error threshold for this run.
            quarantine: Destination folder for a live run; blank when the
                disposition does not use it.
            disposition: What the live run does with each duplicate.
            exact_mode: Off, only, or also exact-duplicate matching.
        """
        settings = ScanSettings(
            threshold=threshold,
            quarantine_dir=quarantine,
            disposition=disposition,
            exact_mode=exact_mode,  # type: ignore[arg-type]
        )
        with active_batch(self.TOOL_ID, UNDO_OPERATION):
            run_duplicate_scan(
                folder,
                is_dry_run,
                settings,
                on_progress=self._on_progress,
                on_complete=self._finish_run,
                on_error=self._on_error,
            )

    # ── Callbacks (queued from the scan's thread — no widget writes) ──

    def _on_progress(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
        """Queue one progress tick for the Tk thread's poller.

        Called from the scan's own thread, so it only queues; the tick is
        written by ``_dispatch_ui_message`` (AGENTS.md).

        Args:
            processed: Files finished so far.
            total: Files the run will attempt.
            skipped: Files without a fingerprint so far.
            errors: Files that could not be moved so far.
            display_text: The per-file line the processor published.
            **_extra: The other progress fields the processor publishes.
        """
        self._ui_updates.put(
            ("progress", processed, total, skipped, errors, display_text)
        )

    def _on_error(self, message: str) -> None:
        """Queue a fatal run error for the Tk thread's poller.

        The processor publishes this from the scan's thread and the shell's
        handler raises a dialog, so it must be called from the Tk thread only.

        Args:
            message: The user-facing message the processor published.
        """
        self._ui_updates.put(("error", message))

    def _poll_ui_updates(self) -> None:
        """Apply the run's queued messages while its thread is alive.

        The loop is the suite's ``event_pump.pump_events``: it drains in order,
        re-arms while the run's thread lives, and drains once more after it
        ends, so the completion queued as the worker exited still renders.  The
        tick id is dropped: with no close handler there is nothing to cancel.
        """
        pump_events(
            self.root,
            self._ui_updates,
            self._dispatch_ui_message,
            is_running=lambda: (
                self._run_thread is not None and self._run_thread.is_alive()
            ),
            next_tick=self._poll_ui_updates,
        )

    def _dispatch_ui_message(self, message: tuple[Any, ...]) -> None:
        """Render one queued message on the Tk thread."""
        kind = message[0]
        if kind == "progress":
            _, processed, total, skipped, errors, display_text = message
            self._render_progress_standard(processed, total, display_text)
            self.stats_label.config(
                text=(f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}")
            )
        elif kind == "error":
            _, text = message
            super()._on_error(text)
        elif kind == "complete":
            _, total, tagged, skipped, errors, duration_secs, rows = message
            self._render_finish(total, tagged, skipped, errors, duration_secs, rows)

    # ── Completion ────────────────────────────────────────────────────

    def _finish_run(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        groups: int,
        exact_groups: int,
        duplicates: int,
        quarantined: int,
        deleted: int,
        stubbed: int,
        **_extra: Any,
    ) -> None:
        """Write this run's report, then queue the Results update.

        Wired as the ``on_complete`` handler itself rather than overriding the
        shell's: this tool's payload carries counts the shell never learns
        (``groups``, ``duplicates``, ``quarantined``), and a required field an
        override adds to a supertype's signature is a type error.  Declaring
        them required is the point — a default is how a dropped field becomes a
        plausible zero in the summary.

        Runs on the scan's own thread: the report is written here, and every
        widget write is queued for the Tk poller.

        Args:
            header: Report header lines for this run.
            total: Files the walk visited.
            processed: Files it finished visiting.
            skipped: Files it could not fingerprint.
            errors: Files it could not move.
            duration_secs: Wall-clock run time.
            log_entries: The per-file report lines.
            groups: Duplicate groups found, exact and fingerprint alike.
            exact_groups: How many of those were exact (byte or PCM) groups.
            duplicates: Files identified as duplicates.
            quarantined: Files actually moved (always 0 in a dry run).
            deleted: Files moved to the Recycle Bin.
            stubbed: Files replaced by a verified ASX stub.
            **_extra: Other completion fields; ignored here rather than
                rejected, so a payload that grows cannot abort a finished run.
        """
        disposition = normalize(self._run_disposition)
        dry_run = self._run_mode == DRY_RUN
        if disposition == DEFAULT_DISPOSITION:
            verb = "would quarantine" if dry_run else "quarantined"
            handled = quarantined
        elif disposition == "delete":
            verb = "would delete" if dry_run else "deleted"
            handled = deleted
        else:
            verb = "would stub" if dry_run else "stubbed"
            handled = stubbed
        rows: tuple[tuple[str, str], ...] = (
            ("Duplicate groups", str(groups)),
            ("Exact groups", str(exact_groups)),
            ("Duplicate files", str(duplicates)),
            (f"Files {verb}", str(handled)),
            ("Without a fingerprint", str(skipped)),
        )
        self._record_run_note(
            total=total, skipped=skipped, errors=errors, disposition=disposition
        )

        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        tagged = processed - skipped - errors
        summary: list[str] = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"{self.TAGGED_LABEL}: {tagged}\n",
            f"Skipped: {skipped}\n",
            f"Errors: {errors}\n",
        ]
        summary.extend(f"{label}: {value}\n" for label, value in rows)
        summary.append(f"Time: {minutes:02d}:{seconds:02d}\n")

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(header + log_entries + summary)
            logger.info("Log written to '%s'", self._log_path)
        except Exception as exc:
            # The audio work is already done by the time the report is
            # serialised, so a failed write is logged, never raised (AGENTS.md).
            mapped = map_to_audio_error(exc, context={"log_path": self._log_path})
            logger.error(
                "[%s] Could not write log '%s': %s",
                type(mapped).__name__,
                self._log_path,
                mapped,
                exc_info=True,
            )

        self._ui_updates.put(
            ("complete", total, tagged, skipped, errors, duration_secs, rows)
        )

    def _render_finish(
        self,
        total: int,
        tagged: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        rows: tuple[tuple[str, str], ...],
    ) -> None:
        """Render the finished run (must run on the main thread).

        Args:
            total: Files the walk visited.
            tagged: Files that were scanned without being skipped or erroring.
            skipped: Files without a fingerprint.
            errors: Files that could not be moved.
            duration_secs: Wall-clock run time.
            rows: This run's extra summary rows, as the completion message
                carries them.
        """
        text: str = (
            f"Total: {total} files\n"
            f"{self.TAGGED_LABEL}: {tagged}\n"
            f"Skipped: {skipped}\n"
            f"Errors: {errors}"
        )
        for label, value in rows:
            text += f"\n{label}: {value}"
        self.summary_label.config(text=text)
        # This window has always labelled a finished run by its mode; the shell
        # renders ``completion_text``, so point it at this run's wording first.
        self.completion_text = (
            self.DRY_COMPLETE_LABEL
            if self._run_mode == DRY_RUN
            else self.LIVE_COMPLETE_LABEL
        )
        self.render_completion(duration_secs=duration_secs, output_dir=self._run_folder)
        if self.auto_end:
            self.root.after(2000, self.root.destroy)

    def _record_run_note(
        self, *, total: int, skipped: int, errors: int, disposition: str = ""
    ) -> None:
        """Record what this run could not fingerprint or move, for the driver.

        Runs on the scan's thread, so it reads the run's snapshotted
        disposition and never a Tk variable.

        Args:
            total: Files the walk visited.
            skipped: Files without a fingerprint.
            errors: Files that could not be moved.
            disposition: The run's disposition, used in the caveat wording.
        """
        action = {
            "quarantine": "quarantined",
            "delete": "deleted",
            "asx-stub": "stubbed",
        }.get(normalize(disposition), "handled")
        record_caveats(
            DRIVER_TOOL_ID,
            shortfall(errors, total, "file", f"could not be {action}")
            if errors
            else "",
            shortfall(skipped, total, "file", "had no readable fingerprint")
            if skipped
            else "",
        )

    # ── Presets ───────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        """Return the settings a preset stores."""
        return {
            "threshold": float(self.threshold.get()),
            "quarantine_dir": self.quarantine_dir.get(),
            "disposition": normalize(self.disposition.get()),
            "exact_mode": str(self.exact_mode.get()),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        """Apply a loaded preset onto this tool's variables."""
        if "threshold" in settings:
            self.threshold.set(float(settings["threshold"]))
        if "quarantine_dir" in settings:
            self.quarantine_dir.set(str(settings["quarantine_dir"]))
        if "exact_mode" in settings:
            self.exact_mode.set(str(settings["exact_mode"]))
        self._set_disposition(str(settings.get("disposition", DEFAULT_DISPOSITION)))
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
    apply_argv = cli_args.looks_like_driver_argv()
    app = DuplicateFinderApp(root, apply_argv=apply_argv)
    app.root.mainloop()
