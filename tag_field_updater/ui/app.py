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
Changed in 2.2.1: the window is a peer in every other respect too (U4).  The app
is an `AnalysisTagToolApp`, so the run drives the shared progress/completion
handlers, the browse dialog is the shared one (initial directory, last-directory
memory), the argv handshake is the positional one every folder tool reads, and
the edition writes the run report into the scanned folder
(`tag_field_updater_dry_run_log.txt` / `tag_field_updater_sync_log.txt`) that
View Log opens — the per-file detail the tool used to keep only in
`logs/tag_field_updater.log`.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk
from typing import Any

from audio_suite_shared import styles
from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.run_outcome import record_caveats, shortfall
from audio_suite_shared.styles import bootstrap_theme
from audio_suite_shared.tool_app_base import AnalysisTagToolApp

from ..core.filename_patterns import PatternError
from ..core.processor import TagProcessor, run_scan
from ..utils import cli_args
from ..utils import config as action_config
from . import processing_tab, results_tab, setup_tab

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


class TagFieldUpdaterApp(AnalysisTagToolApp):
    """Tkinter GUI application for Tag Field Updater."""

    #: Manifest id, used by the shared preset/scaffold hooks.
    TOOL_ID: str = DRIVER_TOOL_ID

    #: Shipped guide the Help button opens.  Registered in
    #: ``audio_suite_shared.platform_utils.guide_to_program``; an empty value
    #: would make the inherited ``_open_help`` a silent no-op.
    HELP_GUIDE = "Tag_Field_Updater_User_Guide.docx"

    TAGGED_LABEL: str = "Files read"
    DRY_COMPLETE_LABEL: str = "Scan Complete!"
    LIVE_COMPLETE_LABEL: str = "Tag Update Complete!"

    #: Rows the finished run adds to the summary in the report and the Results
    #: tab.  A tuple replaced per completion, never mutated in place, so a
    #: finished run's row cannot survive into the next one.
    _summary_rows: tuple[tuple[str, str], ...] = ()

    def __init__(self, root: tk.Tk, *, apply_argv: bool = True) -> None:
        """Initialize the application window, variables, and processor.

        Args:
            root: The Tk root the window is built in.
            apply_argv: Whether to apply the Master-Driver handshake from
                ``sys.argv``.  The ``--directory`` module entry pre-populates
                the source itself, and its own flag is not part of the
                handshake, so it opts out.
        """
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Tag Field Updater",
            "tag_field_updater_window",
            "tag_field_updater",
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path: tk.StringVar = tk.StringVar()
        #: The strip's Mode value.  The only writer of "Dry Run" on behalf of
        #: the filename source is ``_on_filename_mode_toggled``.
        self.run_mode: tk.StringVar = tk.StringVar(value=DRY_RUN)
        self.filename_mode: tk.BooleanVar = tk.BooleanVar(value=False)
        self.only_fill_blanks: tk.BooleanVar = tk.BooleanVar(value=True)
        self.action_group: tk.StringVar = tk.StringVar()

        #: Mirrors of the driver's orchestration strip.  Auto Start/Auto End
        #: are honoured (the shared handshake and ``_update_ui_on_complete``);
        #: Clear Logs and Parallel are display-only because the driver
        #: executes them.
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        #: Read by ``UniversalCLIHandler`` from the parsed handshake and by the
        #: shared completion handler, which closes the window when it is set.
        self.auto_end: bool = False

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

        self._build_ui()
        if apply_argv:
            self._apply_cli_args()

        # Force UI refresh so Entry widgets display current variable values.
        self.root.update_idletasks()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last: str = _suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Window construction ───────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Build the window: Help bar, three standard tabs, shared Setup strip.

        Everything is packed rather than gridded, so the notebook, the source
        entry and the pattern box all grow with the window — the shape every
        peer window has (maintenance items U1 and U3).
        """
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

        tab_setup_frame = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_processing_frame = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_results_frame = tk.Frame(self.notebook, bg=styles.BG_LIGHT)

        self.notebook.add(tab_setup_frame, text=" 1. Setup ")
        self.notebook.add(tab_processing_frame, text=" 2. Processing ")
        self.notebook.add(tab_results_frame, text=" 3. Results ")

        setup_widgets: dict[str, Any] = setup_tab.build(
            tab_setup_frame,
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
        self.setup_frame = setup_widgets["setup_frame"]
        self.start_btn: tk.Button = setup_widgets["start_btn"]
        self.stop_btn: tk.Button = setup_widgets["stop_btn"]
        self.patterns_text: tk.Text = setup_widgets["patterns_text"]
        self.group_combo: ttk.Combobox = setup_widgets["group_combo"]
        self.controls_panel = setup_widgets["controls_panel"]

        # Single-threaded scan: the shared tab's slot grid is not requested.
        proc_widgets: dict[str, Any] = processing_tab.build(tab_processing_frame)
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        #: The shared status line, driven exactly like every peer's.
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.overall_status.set("Ready")

        res_widgets: dict[str, Any] = results_tab.build(
            tab_results_frame,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]
        self.time_label: tk.Label = res_widgets["time_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]

        self._tab_processing = tab_processing_frame
        self._tab_results = tab_results_frame

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        """Parse and apply the Master Driver's argv onto the controls."""
        self._apply_driver_cli_args(cli_args.parse())

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
        # dialog here, not a half-tagged library later.
        dry_run = self.run_mode.get() == DRY_RUN
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
                    patterns, only_fill_blanks=self.only_fill_blanks.get()
                )
            except PatternError as exc:
                messagebox.showerror("Filename Pattern", str(exc))
                return
        else:
            self.processor.use_filename_patterns(())

        fill_mode = (
            "only fill blanks" if self.only_fill_blanks.get() else "overwrite existing"
        )
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

        self.start_btn.config(state="disabled")
        self.stop_btn.config(state=tk.NORMAL)
        self.notebook.select(self._tab_processing)
        self.file_listbox.delete(0, tk.END)
        self._reset_progress_ui()
        self.overall_status.set("Scanning...")
        logger.info(
            "start_processing: folder=%s dry_run=%s source=%s",
            folder,
            dry_run,
            "filenames" if patterns else "slash-rule",
        )

        threading.Thread(
            target=self._run_scan,
            args=(folder, dry_run, patterns, header),
            daemon=True,
        ).start()

    @handle_audio_errors(reraise=False, context="tag_field_updater_app_run")
    def _run_scan(
        self,
        folder: str,
        is_dry_run: bool,
        patterns: tuple[str, ...],
        header: list[str],
    ) -> None:
        """Background thread: delegate to :func:`processor.run_scan`.

        The report path is set here, before completion, because the shared
        completion handler writes the report it is handed to ``_log_path``.

        Args:
            folder: Root directory to walk.
            is_dry_run: Whether the run may write.
            patterns: Filename patterns for this run; empty for the slash rule.
            header: Report header lines for this run.
        """
        self._out_dir = folder
        self._log_path = os.path.join(
            folder, RUN_REPORT_DRY_RUN if is_dry_run else RUN_REPORT_LIVE
        )
        run_scan(
            folder,
            is_dry_run=is_dry_run,
            patterns=patterns,
            only_fill_blanks=self.only_fill_blanks.get(),
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
        """Record the run's summary rows and note, then finish as usual.

        Bound by the wiring lambda rather than overriding ``_on_complete``:
        this tool's payload carries two counts the shared base never learns
        (``updated``, ``audio_files``), and a required field an override adds
        to the supertype's signature is a type error.  Declaring them required
        is the point — a default is how a dropped field becomes a plausible
        zero in the summary.

        Runs on the worker thread before the shared base writes the report and
        schedules the Results update, so neither a damaged Tk nor an unwritable
        report can suppress the note the Master Driver reads.

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
        rows: list[tuple[str, str]] = []
        if audio_files:
            verb = "would update" if self.run_mode.get() == DRY_RUN else "updated"
            rows.append(("Audio files", f"{audio_files} of {total} files"))
            rows.append(("Files " + verb, f"{updated} of {audio_files}"))
        self._summary_rows = tuple(rows)
        self._record_run_note(total=total, skipped=skipped, errors=errors)
        self.root.after(0, self._disable_stop)
        super()._on_complete(
            header=header,
            total=total,
            processed=processed,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            log_entries=log_entries,
            **_extra,
        )

    def _summary_extras(self) -> list[tuple[str, str]]:
        """Return this run's rows for the report and the Results panel."""
        return list(self._summary_rows)

    def _disable_stop(self) -> None:
        """Disable the Stop button (main thread; after a finished run)."""
        self.stop_btn.config(state=tk.DISABLED)

    def _show_error_dialog(self, message: str) -> None:
        """Report a fatal error and hand the controls back."""
        super()._show_error_dialog(message)
        self._disable_stop()

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
