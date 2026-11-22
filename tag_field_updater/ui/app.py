"""Tkinter UI for Tag Field Updater.

Provides the graphical user interface for scanning and updating tag fields.

Changed in 1.0.1: parses the driver's argv and adds a Dry Run checkbox wired to the CLI
mode.

Changed in 1.2.0: records the files a scan skipped (unsupported format or no
readable tags) and the ones it could not update as the run's note, so a Master
Driver batch reports them on the Tag Field Updater step instead of only in the
completion dialog and the run log.
Changed in 2.2.0: the filename source (functional backlog F-01) — a pattern
box, the only-fill-blanks switch and saved action groups.  Turning the mode on
selects Dry Run, so the default is the CLI's default and choosing Live Update is
the explicit decision to write.
Changed in 2.2.1: the window is built on the suite's shared pieces (maintenance
item U1) — the palette Help bar, a three-tab notebook, the shared Processing tab
(progress bar, file list, status line) and Results tab (View Log / Open Folder),
so the tool no longer shares nothing with its peers.  The rules panel is now a
pointer at the Help guide, and the directory entry and pattern box grow with the
window instead of being cut at a fixed width.
Changed in 2.2.1: the Setup tab is a `BaseSetupFrame` (U3), so the shared Run
Controls strip supplies the source row, the Mode combobox and the driver's
orchestration display, and the start button is the suite's full-width one.  The
strip's Mode is the only write path for dry/live, and `_on_filename_mode_toggled`
remains the only place that forces Dry Run.
Changed in 2.2.1: the window is a peer in every other respect too (U4).  At the
time the app was an `AnalysisTagToolApp`, so the run drove the shared
progress/completion handlers, the browse dialog was the shared one (initial
directory, last-directory memory), the argv handshake was the positional one
every folder tool reads, and the edition wrote the run report into the scanned
folder (`tag_field_updater_dry_run_log.txt` /
`tag_field_updater_sync_log.txt`) that View Log opens — the per-file detail the
tool used to keep only in `logs/tag_field_updater.log`.

Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, D8's wave 3), so the
shell owns the Help bar and the Processing and Results tabs and this tool keeps
its Setup panel.  The run report and the Results summary are written here again
now that the window no longer inherits ``AnalysisTagToolApp``, with the
``SUMMARY:`` footer every peer writes, and ``start_processing`` snapshots the
run's mode, folder and only-fill-blanks choice on the Tk thread — the worker and
the completion used to call ``.get()`` on those variables from the scan's
thread.  Every callback the scan publishes — the progress tick, the run error
and the completion — is a message on a ``SimpleQueue`` a poller the Tk thread
starts drains, because ``_run_scan`` is a raw ``threading.Thread`` and may not
call ``root.after`` or a widget at all.  View Log and Open Folder are the
shell's.

Changed in 2.9.0: that poller is the shared ``event_pump.pump_events``, so the
drain loop and its finished-run drain are the suite's one implementation (B2).

Changed in 2.9.0: the window keeps no tick id.  It has no close handler, so
nothing could ever cancel the pending tick, and a destroyed root drops its
``after`` callbacks itself (D30).

Changed in 2.9.0: the shell owns the hand-off - ``_start_worker`` builds the
queue and starts the thread, and ``_poll_ui_updates`` is inherited - so this
window supplies only ``_dispatch_ui_message`` (D31).

Changed in 2.9.0: the run report is the shell's ``_write_run_report_standard``,
so this window supplies only the run's rows (D32).
"""

from __future__ import annotations

import logging
import os
import sys
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.run_outcome import record_caveats, shortfall
from audio_suite_shared.styles import bootstrap_theme
from audio_suite_shared.suite_app import SuiteApp

from ..core.filename_patterns import PatternError
from ..core.processor import TagProcessor, run_scan
from ..utils import cli_args
from ..utils import config as action_config
from . import setup_tab

logger = logging.getLogger(__name__)

#: Manifest id the Master Driver keys this tool's batch step by; a note
#: recorded under any other key is never read.  Locked to the manifest by
#: ``tests/test_run_outcome_contract.py``.
DRIVER_TOOL_ID = "tag_field_updater"

#: This program's own diagnostic log - what ``configure_logging("tag_field_updater")``
#: writes, and where the per-program detail goes.  The literal lives here once:
#: the user guide names the file, and ``tests/test_guide_claims.py`` requires a
#: name a guide quotes to exist in the code that writes it.
PROGRAM_LOG_NAME = "tag_field_updater.log"

#: The run report the window writes into the folder it scanned, in the shape
#: every peer uses (``<prefix>_dry_run_log.txt`` beside ``<prefix>_sync_log.txt``).
#: It is what the Results tab's View Log button opens.
RUN_REPORT_DRY_RUN = "tag_field_updater_dry_run_log.txt"
RUN_REPORT_LIVE = "tag_field_updater_sync_log.txt"

#: The two labels the shared Run Controls strip binds its Mode combobox to.
#: They are the Master Driver's own strings: a translated label would make a
#: driven panel disagree with the tab that launched it.
DRY_RUN = "Dry Run"
LIVE_UPDATE = "Live Update"
RUN_MODES = (DRY_RUN, LIVE_UPDATE)


class TagFieldUpdaterApp(SuiteApp):
    """Tkinter GUI application for Tag Field Updater."""

    title = "Tag Field Updater"
    window_key = "tag_field_updater_window"
    program_name = DRIVER_TOOL_ID
    #: Shipped guide the Help button opens.  Registered in
    #: ``audio_suite_shared.platform_utils.guide_to_program``; an empty value
    #: would make the shell's Help button a silent no-op.
    HELP_GUIDE = "Tag_Field_Updater_User_Guide.docx"
    guide_name = HELP_GUIDE
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" 1. Setup ", " 2. Processing ", " 3. Results ")

    #: Nothing is tagged or analysed here beyond the fields the rule touches, so
    #: the shared "processed" count is "files read".
    TAGGED_LABEL: str = "Files read"
    DRY_COMPLETE_LABEL: str = "Scan Complete!"
    LIVE_COMPLETE_LABEL: str = "Tag Update Complete!"
    #: The heading the tab shows before a run; a finished run replaces it with
    #: the wording for its mode, which starts here.
    completion_text: str = DRY_COMPLETE_LABEL

    #: The manifest id the window has always declared (tests and the driver read
    #: it); ``program_name`` above is the shell's copy of the same value.
    TOOL_ID: str = DRIVER_TOOL_ID

    #: Set from argv in ``__init__``.  The default keeps an ``object.__new__``
    #: test shell on the interactive (modal-warning) path.
    _launched_from_driver: bool = False
    #: Read by the completion, which closes the window when it is set.
    auto_end: bool = False
    #: Built by the shell from the Setup panel.
    _setup_frame: Any = None
    #: The run's mode and folder, snapshotted on the Tk thread by
    #: ``start_processing`` so the completion reads no Tk variable.
    _run_mode: str = ""
    _run_folder: str = ""

    def __init__(self, root: tk.Tk, *, apply_argv: bool = True) -> None:
        """Initialize the application window, variables, and processor.

        Args:
            root: The Tk root the window is built in.
            apply_argv: Whether to apply the Master-Driver handshake from
                ``sys.argv``.  The ``--directory`` module entry pre-populates
                the source itself, and its own flag is not part of the
                handshake, so it opts out.
        """
        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path: tk.StringVar = tk.StringVar()
        #: The strip's Mode value.  The only writer of "Dry Run" on behalf of
        #: the filename source is ``_on_filename_mode_toggled``.
        self.run_mode: tk.StringVar = tk.StringVar(value=DRY_RUN)
        self.filename_mode: tk.BooleanVar = tk.BooleanVar(value=False)
        self.only_fill_blanks: tk.BooleanVar = tk.BooleanVar(value=True)
        self.action_group: tk.StringVar = tk.StringVar()

        #: Mirrors of the driver's orchestration strip.  Auto Start/Auto End
        #: are honoured (the handshake and the completion); Clear Logs and
        #: Parallel are display-only because the driver executes them.
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        #: Master Driver handshake: the panel is locked when it launched this
        #: process, so the args it passed cannot be edited mid-batch.  A
        #: caller that opted out of the handshake (the ``--directory`` module
        #: entry) was not launched by the driver, whatever its argv length says.
        self._launched_from_driver = apply_argv and cli_args.was_launched_from_driver()

        #: Initialize processor -- the window keeps the instance so Stop can
        #: signal the scan it started.
        self.processor = TagProcessor()

        #: Filled at the start of a run with the report path inside the scanned
        #: folder; blank until then, which makes View Log say so instead of
        #: opening the suite log.
        self._log_path: str = ""

        super().__init__(root)
        # The shared Processing tab starts at "Waiting..."; this window has
        # always said "Ready" until a run begins.
        self.overall_status.set("Ready")
        if apply_argv:
            self._apply_cli_args(cli_args.parse())

        # Force UI refresh so Entry widgets display current variable values.
        self.root.update_idletasks()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last: str = _suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Shell tabs ───────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the filename source, the field pointer and the run controls."""
        widgets: dict[str, Any] = setup_tab.build(
            parent,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            filename_mode=self.filename_mode,
            only_fill_blanks=self.only_fill_blanks,
            action_group=self.action_group,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            on_stop=self.stop_processing,
            on_filename_mode_toggled=self._on_filename_mode_toggled,
            on_load_group=self.load_action_group,
            on_save_group=self.save_action_group,
            group_names=sorted(action_config.load_action_groups()),
            driver_locked=self._launched_from_driver,
            modes=RUN_MODES,
        )
        self._setup_frame = widgets["setup_frame"]
        self.start_btn = widgets["start_btn"]
        self.stop_btn = widgets["stop_btn"]
        self.patterns_text: tk.Text = widgets["patterns_text"]
        self.group_combo: ttk.Combobox = widgets["group_combo"]
        self.controls_panel = widgets["controls_panel"]

    # ── User actions ──────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        """Browse for a music directory, remembering the choice."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self, parsed: cli_args.TagFieldUpdaterArgs) -> None:
        """Apply a parsed Master-Driver handshake onto the controls.

        Every route that writes a control has to reach the same widget the
        user's own edit would, and the auto-start has to be scheduled rather
        than run inside ``__init__``, so the window is drawn first.

        Args:
            parsed: The per-tool ``cli_args.parse()`` dataclass.
        """
        self.run_mode.set(LIVE_UPDATE if parsed.live_mode else DRY_RUN)
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)
        self.auto_end = bool(parsed.auto_end)

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

    # ── Filename source (F-01) ────────────────────────────────────────────────

    def _on_filename_mode_toggled(self) -> None:
        """Make the filename mode dry by default.

        A filename parse is a guess about a naming convention: a wrong split
        writes plausible wrong tags, and the file looks tagged afterwards.  So
        enabling the mode selects Dry Run, and writing is an explicit choice of
        Live Update.
        """
        if self.filename_mode.get():
            self.run_mode.set(DRY_RUN)
            self.overall_status.set(
                "Filename mode: Dry Run selected. Choose Live Update to write "
                "the parsed values."
            )

    def _patterns_from_box(self) -> tuple[str, ...]:
        """Return the non-blank pattern lines in the box, in order.

        Returns:
            The patterns as typed; empty when the box is blank.
        """
        raw = self.patterns_text.get("1.0", "end").splitlines()
        return tuple(line.strip() for line in raw if line.strip())

    def load_action_group(self) -> None:
        """Fill the pattern box and write mode from the selected action group."""
        name = self.action_group.get().strip()
        if not name:
            return
        group = action_config.get_action_group(name)
        if group is None:
            messagebox.showwarning(
                "Action Group", f"Action group {name!r} is not saved any more."
            )
            self.group_combo["values"] = sorted(action_config.load_action_groups())
            return
        self.patterns_text.delete("1.0", "end")
        self.patterns_text.insert("1.0", "\n".join(group.patterns))
        self.only_fill_blanks.set(group.only_fill_blanks)
        self.filename_mode.set(True)
        self._on_filename_mode_toggled()
        self.overall_status.set(f"Loaded action group {name!r}.")

    def save_action_group(self) -> None:
        """Save the pattern box's contents under a name the user chooses."""
        patterns = self._patterns_from_box()
        if not patterns:
            messagebox.showwarning(
                "Action Group", "Add at least one filename pattern first."
            )
            return
        name = simpledialog.askstring(
            "Save Action Group", "Name for this pattern set:", parent=self.root
        )
        if not name:
            return
        try:
            saved = action_config.save_action_group(
                name, patterns, only_fill_blanks=self.only_fill_blanks.get()
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Action Group", str(exc))
            return
        self.group_combo["values"] = sorted(action_config.load_action_groups())
        self.action_group.set(saved.name)
        self.overall_status.set(f"Saved action group {saved.name!r}.")

    # ── Run ───────────────────────────────────────────────────────────────────

    def start_processing(self) -> None:
        """Validate inputs, then launch the scan worker thread."""
        folder = self.folder_path.get().strip()

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

        # Resolve the source before the thread starts: a bad pattern is a
        # dialog here, not a half-tagged library later.  The mode and the write
        # choice are read once, so the report header, the processor and the
        # worker's snapshot cannot disagree about what this run will do.
        run_mode = self.run_mode.get()
        dry_run = run_mode == DRY_RUN
        only_fill_blanks = self.only_fill_blanks.get()
        patterns: tuple[str, ...] = ()
        if self.filename_mode.get():
            patterns = self._patterns_from_box()
            if not patterns:
                messagebox.showwarning(
                    "Filename Pattern",
                    "Add at least one filename pattern, or untick filename mode.",
                )
                return
            try:
                self.processor.use_filename_patterns(
                    patterns, only_fill_blanks=only_fill_blanks
                )
            except PatternError as exc:
                messagebox.showerror("Filename Pattern", str(exc))
                return
        else:
            self.processor.use_filename_patterns(())

        fill_mode = "only fill blanks" if only_fill_blanks else "overwrite existing"
        source_line = (
            "Source: filenames\n"
            f"Patterns: {' | '.join(patterns)}\n"
            f"Write mode: {fill_mode}\n"
            if patterns
            else "Source: slash rule (a bare '/' becomes '; ')\n"
        )
        header: list[str] = [
            "TAG FIELD UPDATE REPORT\n",
            f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}\n",
            f"Directory: {folder}\n",
            source_line,
            "=" * 60 + "\n",
        ]

        # Snapshot what the worker and the completion render from, on the Tk
        # thread: neither may call .get().
        self._run_mode = run_mode
        self._run_folder = folder
        self._log_path = os.path.join(
            folder, RUN_REPORT_DRY_RUN if dry_run else RUN_REPORT_LIVE
        )

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state=tk.NORMAL)
        self.notebook.select(self.processing_frame)
        self.file_listbox.delete(0, tk.END)
        self._reset_progress_ui()
        self.overall_status.set("Scanning...")
        logger.info(
            "start_processing: folder=%s dry_run=%s source=%s",
            folder,
            dry_run,
            "filenames" if patterns else "slash-rule",
        )

        self._start_worker(
            self._run_scan, (folder, dry_run, patterns, header, only_fill_blanks)
        )

    @handle_audio_errors(reraise=False, context="tag_field_updater_app_run")
    def _run_scan(
        self,
        folder: str,
        is_dry_run: bool,
        patterns: tuple[str, ...],
        header: list[str],
        only_fill_blanks: bool,
    ) -> None:
        """Background thread: delegate to :func:`processor.run_scan`.

        Args:
            folder: Root directory to walk.
            is_dry_run: Whether the run may write.
            patterns: Filename patterns for this run; empty for the slash rule.
            header: Report header lines for this run.
            only_fill_blanks: The run's write mode, snapshotted on the Tk thread.
        """
        run_scan(
            folder,
            is_dry_run=is_dry_run,
            patterns=patterns,
            only_fill_blanks=only_fill_blanks,
            on_progress=self._on_progress,
            on_complete=lambda **kw: self._finish_run(header=header, **kw),
            on_error=self._on_error,
            processor=self.processor,
        )

    def stop_processing(self) -> None:
        """Request the processor to stop and update the status line."""
        self.processor.stop()
        self.overall_status.set("Stopping...")

    # ── Completion ────────────────────────────────────────────────────────────

    def _finish_run(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        updated: int,
        audio_files: int,
        **_extra: Any,
    ) -> None:
        """Write this run's report, then queue the Results update.

        Bound by the wiring lambda rather than overriding a shell handler: this
        tool's payload carries two counts the shell never learns (``updated``,
        ``audio_files``), and a required field an override adds to the
        supertype's signature is a type error.  Declaring them required is the
        point — a default is how a dropped field becomes a plausible zero in the
        summary.

        Runs on the scan's own thread: the report is written here, and every
        widget write is queued for the Tk poller.

        Args:
            header: Report header lines for this run.
            total: Files the walk visited.
            processed: Files it finished visiting.
            skipped: Files left alone (unsupported format, or a name no pattern
                matched).
            errors: Files that could not be updated.
            duration_secs: Wall-clock run time.
            log_entries: The per-file report lines.
            updated: Files whose tags were rewritten (or would be, in a dry run).
            audio_files: Files that carried a supported audio extension.
            **_extra: The other completion fields the processor publishes (the
                skipped/error records the CLI's ``--json`` output consumes);
                they are ignored here.  A handler that rejected one would abort
                the completion, so the report would never be written.
        """
        rows: tuple[tuple[str, str], ...] = ()
        if audio_files:
            verb = "would update" if self._run_mode == DRY_RUN else "updated"
            rows = (
                ("Audio files", f"{audio_files} of {total} files"),
                ("Files " + verb, f"{updated} of {audio_files}"),
            )
        self._record_run_note(total=total, skipped=skipped, errors=errors)
        tagged = processed - skipped - errors
        self._write_run_report_standard(
            header=header,
            log_entries=log_entries,
            rows=rows,
            total=total,
            tagged=tagged,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
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
            tagged: Files read without being skipped or erroring.
            skipped: Files left alone.
            errors: Files that could not be updated.
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
        self.stop_btn.config(state=tk.DISABLED)
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

    def _record_run_note(self, *, total: int, skipped: int, errors: int) -> None:
        """Record the files this scan skipped or could not update.

        The report and the Results tab carry the same counts; this is the
        one-line version the Master Driver reads after the window closes.  A
        clean scan records nothing, which clears any earlier note.

        Args:
            total: Files the walk visited.
            skipped: Files left alone.
            errors: Files that could not be updated.
        """
        record_caveats(
            DRIVER_TOOL_ID,
            shortfall(errors, total, "file", "could not be updated") if errors else "",
            shortfall(
                skipped,
                total,
                "file",
                "were skipped (unsupported format or no readable tags)",
            )
            if skipped
            else "",
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
            skipped: Files left alone so far.
            errors: Files that could not be updated so far.
            display_text: The per-file line the processor published.
            **_extra: The other progress fields the processor publishes.
        """
        self._ui_updates.put(
            ("progress", processed, total, skipped, errors, display_text)
        )

    def _on_error(self, message: str) -> None:
        """Queue a fatal run error for the Tk thread's poller.

        The processor publishes this from the scan's thread and the shell's
        handler raises a dialog, so it must run on the Tk thread only.

        Args:
            message: The user-facing message the processor published.
        """
        self._ui_updates.put(("error", message))

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
            self.stop_btn.config(state=tk.DISABLED)
        elif kind == "complete":
            _, total, tagged, skipped, errors, duration_secs, rows = message
            self._render_finish(total, tagged, skipped, errors, duration_secs, rows)

    # ── Shared run plumbing ───────────────────────────────────────────────────

    def _reset_progress_ui(self) -> None:
        """Reset the bar and the counters (must be called on the Tk thread)."""
        self.progress["value"] = 0
        self.stats_label.config(text=self.processing_stats_text)


def main(directory: str | None = None) -> None:
    """Main entry point for the Tag Field Updater application.

    The driver's handshake is applied by the window itself (as every peer's
    does): ``TagFieldUpdaterApp`` mirrors the Mode, Auto Start/Auto End and the
    display flags onto the Run Controls strip, locks the panel when the driver
    launched the process, and schedules the scan only when the driver asked for
    it.  A path passed to this function directly — the ``--directory`` module
    entry — keeps its documented immediate-start behaviour.

    Args:
        directory: Optional path to pre-populate the source field and scan
            immediately.  When ``None``, the Master-Driver / CLI argv is
            applied by the window instead.
    """
    root = tk.Tk()
    bootstrap_theme()
    apply_argv = directory is None and cli_args.looks_like_driver_argv()
    app = TagFieldUpdaterApp(root, apply_argv=apply_argv)

    if directory is not None:
        if not os.path.exists(directory):
            logger.error("Launch directory does not exist: %s", directory)
            sys.exit(1)
        if not os.path.isdir(directory):
            logger.error("Launch path is not a directory: %s", directory)
            sys.exit(1)

        app.folder_path.set(directory)
        app.start_processing()

    app.root.mainloop()
