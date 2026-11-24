"""
app.py — MetadataScrubberApp orchestrator.
Wires UI, core logic, and utilities. Contains no business logic itself.

Tag preference persistence:
  - On Browse & Scan: load the kept-tag set from the shared suite config and
    pass it to populate_tags() so previously-kept tags are auto-ticked.
  - On completion of a LIVE run: save the ticked set back to the shared config
    (rolling 'last used' preference; dry runs don't update prefs).

Changed in 2.5.0: the kept-tag preference is read from and written to the
shared suite config through ``tag_prefs``; no tool-local file is touched.

Changed in 1.2.0: records the files a run could not scrub (and any it skipped)
from the completion counts as the run's note, so a Master Driver batch reports
them on the Metadata Scrubber step instead of only in the run log.

Changed in 1.4.1: ``_on_complete`` and ``_on_progress`` accept ``**_extra: Any``,
so a payload field the processor adds (D112) is ignored instead of aborting an
otherwise-finished run; ``tests/test_callback_payload_contract.py`` locks the
completion, progress and error seams.
Changed in 2.9.0: the progress tick is the shared mixin helper (C1).
Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2), so the shell owns
the Help bar and the Processing and Results tabs; the worker pool is built
before the shell renders its grid, and the finished run renders through the
shell after ``_on_complete`` has written the report on the worker thread.

Changed in 2.9.0: the run report's ``SUMMARY:`` footer is
``audio_suite_shared.run_report.summary_lines``, the one implementation
every window writes with (D36).
Changed in 2.9.0: the preset trio (select, save, delete) is the shell's,
so this window declares the settings a preset carries and keeps only that (D58).
"""

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox
from typing import Any

from audio_suite_shared import suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.run_outcome import record_caveats, shortfall
from audio_suite_shared.run_report import summary_lines
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars

from .core import scrubber, tag_scanner
from .ui import setup_tab
from .utils import cli_args, tag_prefs

logger = logging.getLogger(__name__)

TOOL_ID = "metadata_scrubber"

#: Manifest id the Master Driver keys this tool's batch step by; a note
#: recorded under any other key is never read.  Locked to the manifest by
#: ``tests/test_run_outcome_contract.py``.
DRIVER_TOOL_ID = "scrubber"


class MetadataScrubberApp(SuiteApp):
    """Metadata Scrubber application GUI."""

    title = "Metadata Scrubber & Tagger"
    window_key = "metadata_scrubber_window"
    program_name = TOOL_ID
    guide_name = "Metadata_Scrubber_User_Guide.docx"
    completion_text = "Metadata Scrubbing Complete!"
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" 1. Setup ", " 2. Processing ", " 3. Results ")

    #: The key these presets live under in the shared store.
    TOOL_ID = TOOL_ID
    #: The settings a preset carries, in the order it has always stored them.
    PRESET_FIELDS = (
        "run_mode",
        "preserve_lyrics",
        "preserve_album_artist",
        "preserve_embedded_art",
    )

    def __init__(self, root: tk.Tk) -> None:
        # Tk variables
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self.preserve_lyrics = tk.BooleanVar(value=True)
        self.preserve_album_artist = tk.BooleanVar(value=True)
        self.preserve_embedded_art = tk.BooleanVar(value=True)

        # Master Driver handshake: any CLI argument means driver-launched,
        # in which case the Run Controls panel is locked to inherited values.
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # The handshake state the CLI handler writes and _do_scan/_on_complete
        # read; the shell base no longer supplies these.
        self.auto_start = False
        self.auto_end = False

        # The shell renders the worker grid from these before the tabs exist,
        # so the pool has to be ready before ``SuiteApp.__init__`` runs.
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self.slot_queue: Queue[int] = Queue()
        for index in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(index)

        # The Setup tab's run controls call the handler while the shell builds
        # the window, so it has to exist before the shell runs.
        self.cli_handler = UniversalCLIHandler(self)

        self._dir_path = ""

        super().__init__(root)
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self._apply_cli_args()

        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)
                self.root.after(500, self._do_scan)

    # ── Setup tab ─────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the run controls, presets and tag list into *parent*."""
        self._setup_tab: setup_tab.SetupTab = setup_tab.SetupTab(
            parent,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            preserve_lyrics=self.preserve_lyrics,
            preserve_album_artist=self.preserve_album_artist,
            preserve_embedded_art=self.preserve_embedded_art,
            on_browse_scan=self._browse_and_scan,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
            preset_names=suite_config.list_presets(TOOL_ID),
            on_save_preset=self.store_preset,
            on_delete_preset=self.remove_preset,
            on_preset_selected=self.use_preset,
        )
        self.start_btn = self._setup_tab.start_btn
        self.controls_panel = self._setup_tab.controls_panel
        self._refresh_preset_list = self._setup_tab.refresh_preset_list

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
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

        should_auto_start = self.cli_handler.apply_cli_args(
            parsed, folder_var=self.folder_path, auto_start_func=self._do_scan
        )

        self.root.after(500, self._do_scan)

        if should_auto_start:
            self.root.after(1000, self.start_processing)

    # ── User actions ──────────────────────────────────────────────────────────

    def _do_scan(self) -> None:
        folder = self.folder_path.get()
        if not folder:
            return

        def _report_scan_error(msg: str) -> None:
            # showerror returns a str; discard it to satisfy the callback contract.
            messagebox.showerror("Error", msg)

        discovered = tag_scanner.scan_custom_tags(
            folder,
            on_error=_report_scan_error,
        )

        previously_kept = tag_prefs.load_kept_tags()
        self._setup_tab.populate_tags(discovered, previously_kept=previously_kept)

        if self.auto_start:
            self.root.after(500, self.start_processing)

    def _browse_and_scan(self) -> None:
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )
        self._do_scan()

    def start_processing(self) -> None:
        folder = self.folder_path.get()
        if not folder:
            messagebox.showwarning("Warning", "Please select a music directory first.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Error", "Selected path is not a valid directory.")
            return

        self.start_btn.config(state="disabled")
        self.notebook.select(self.processing_frame)
        self.overall_status.set("Scrubbing metadata...")

        preserve_list = self._setup_tab.get_preserve_list()
        preserve_lyrics = self.preserve_lyrics.get()
        preserve_album_artist = self.preserve_album_artist.get()
        preserve_embedded_art = self.preserve_embedded_art.get()
        is_live = self.run_mode.get() == "Live Update"

        threading.Thread(
            target=self._run_scrubbing,
            args=(
                preserve_list,
                preserve_lyrics,
                preserve_album_artist,
                preserve_embedded_art,
                is_live,
            ),
            daemon=True,
        ).start()

    @handle_audio_errors(reraise=False, context="metadata_scrubber_app_run")
    def _run_scrubbing(
        self,
        preserve_list: list[Any],
        preserve_lyrics: bool,
        preserve_album_artist: bool,
        preserve_embedded_art: bool,
        is_live: bool,
    ) -> None:
        dir_path = self.folder_path.get()
        is_dry_run = not is_live
        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            "metadata_dry_run_log.txt" if is_dry_run else "metadata_scrubbing_log.txt",
        )

        preserve_display = ", ".join(preserve_list) if preserve_list else "None"
        header = [
            "METADATA SCRUBBING REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Preserved Tags: {preserve_display}\n",
            f"Lyrics Preserved: {'Yes' if preserve_lyrics else 'No'}\n",
            f"Album Artist Preserved: {'Yes' if preserve_album_artist else 'No'}\n",
            f"Embedded Art Preserved: {'Yes' if preserve_embedded_art else 'No'}\n",
            "=" * 60 + "\n",
        ]

        self.progress["value"] = 0
        self.stats_label.config(text="Processed: 0 | Skipped: 0 | Errors: 0")

        with active_batch("metadata_scrubber", "tag_edit"):
            scrubber.run_scrubbing(
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                preserve_list=preserve_list,
                preserve_lyrics=preserve_lyrics,
                preserve_album_artist=preserve_album_artist,
                preserve_embedded_art=preserve_embedded_art,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(
                    header=header, is_live=is_live, preserve_list=preserve_list, **kw
                ),
                on_error=self._on_error,
            )

    def _on_progress(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
        """Thread-safe progress handler: touch the widgets on the Tk thread."""
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
        self._render_progress_standard(processed, total, display_text)
        self.stats_label.config(
            text=f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}"
        )

    def _on_complete(
        self,
        header: list[Any],
        is_live: bool,
        preserve_list: list[Any],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[Any],
        **_extra: Any,
    ) -> None:
        """Completion seam: write the report here, render it on the Tk thread."""
        self._write_run_report(
            header=header,
            total=total,
            processed=processed,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            log_entries=log_entries,
        )

        if is_live:
            tag_prefs.save_kept_tags(preserve_list)

        self._record_run_note(total=total, skipped=skipped, errors=errors)
        self.root.after(
            0,
            self._update_ui_on_complete,
            is_live,
            total,
            processed,
            skipped,
            errors,
            duration_secs,
        )

        if self.auto_end:
            self._append_auto_end_note()
            self.root.update_idletasks()
            self.root.after(2000, self.root.destroy)

    def _write_run_report(
        self,
        *,
        header: list[Any],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[Any],
    ) -> None:
        """Serialise the run report View Log opens; a failed write is shown."""
        succeeded = processed - skipped - errors

        summary = summary_lines(
            total=total,
            tagged=succeeded,
            tagged_label="Successfully processed",
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
        )
        self._log_entries = [*header, *log_entries, *summary]

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(self._log_entries)
        except OSError as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Log write failed: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Error",
                f"Could not write log file:\n{user_message_for(mapped)}",
            )

    def _append_auto_end_note(self) -> None:
        """Append the auto-end line to the report; a failed rewrite only warns."""
        self._log_entries.append("\n[Auto End enabled - closing in 2 seconds...]\n")
        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(self._log_entries)
        except OSError as exc:
            logger.warning("Could not rewrite log for auto-end: %s", exc, exc_info=True)

    def _update_ui_on_complete(
        self,
        is_live: bool,
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Render the finished run (must run on the main thread)."""
        succeeded = processed - skipped - errors
        self.summary_label.config(
            text=f"Total: {total} files\n"
            f"Successfully processed: {succeeded}\n"
            f"Skipped: {skipped}\n"
            f"Errors: {errors}"
        )
        # A dry run has always shown its own heading; the shell renders
        # ``completion_text``, so point it at this run's wording first.
        self.completion_text = (
            "Metadata Scrubbing Complete!" if is_live else "Analysis Complete!"
        )
        self.render_completion(duration_secs=duration_secs, output_dir=self._dir_path)

    def _record_run_note(self, *, total: int, skipped: int, errors: int) -> None:
        """Record the files this run did not manage to scrub.

        The Results tab shows the same two counts; this is the one-line version
        the Master Driver reads after the window closes.  A run that scrubbed
        every file records nothing, which clears any earlier note.

        Args:
            total: Files the run attempted.
            skipped: Files it deliberately left alone.
            errors: Files it could not process.
        """
        record_caveats(
            DRIVER_TOOL_ID,
            shortfall(errors, total, "file", "could not be scrubbed") if errors else "",
            shortfall(skipped, total, "file", "were skipped") if skipped else "",
        )
