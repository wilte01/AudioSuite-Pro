"""Tkinter UI for the Tag Editor.

The Tag Editor is the suite's interactive grid: the load walk fills a table of
files and their editable tag values, and the user applies validated single-field
edits, bulk transformations or a CSV import to the rows they select.

Changed in 2.2.1: the window is built on the suite's shared pieces (maintenance
item U5) — the palette Help bar, a three-tab notebook, the shared Processing tab
(progress bar, per-file list, status line) and Results tab (View Log / Open
Folder) — and the Setup tab is a ``BaseSetupFrame``, so the shared Run Controls
strip supplies the source row, the browse dialog, the Mode combobox and the
driver's orchestration display.  The app is an ``AnalysisTagToolApp``: the load
walk and every apply run go through the processor's ``run_*`` entry points, so
the run drives the shared progress/completion handlers, the browse dialog is the
shared one (initial directory, last-directory memory), the argv handshake is the
positional one every folder tool reads, and each run writes its report into the
scanned folder (``tag_editor_scan_log.txt`` for the load walk,
``tag_editor_dry_run_log.txt`` / ``tag_editor_sync_log.txt`` for an apply), which
is the file View Log opens.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from audio_suite_shared import styles
from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.exceptions import AudioSuiteError, handle_audio_errors
from audio_suite_shared.styles import bootstrap_theme
from audio_suite_shared.tool_app_base import AnalysisTagToolApp

from ..core.csv_io import build_import_plan, export_csv
from ..core.processor import (
    FIELD_LABELS,
    EditResult,
    FieldEdit,
    TagEditorProcessor,
    TagRow,
    build_bulk_edits,
    normalize_field,
    run_apply,
    run_scan,
)
from ..utils import cli_args
from . import processing_tab, results_tab, setup_tab

logger = logging.getLogger(__name__)

#: Manifest id the Master Driver keys this tool's batch step by.
DRIVER_TOOL_ID = "tag_editor"

#: This program's own diagnostic log - what ``configure_logging("tag_editor")``
#: writes, and where the per-program detail goes.
PROGRAM_LOG_NAME = "tag_editor.log"

#: The run reports the window writes into the folder it scanned.  A load walk
#: and an apply run are different runs: the walk reports what it read, the apply
#: reports what it changed, so the walk has its own name instead of posing as a
#: dry run of an edit.
RUN_REPORT_SCAN = "tag_editor_scan_log.txt"
RUN_REPORT_DRY_RUN = "tag_editor_dry_run_log.txt"
RUN_REPORT_LIVE = "tag_editor_sync_log.txt"

#: The two labels the shared Run Controls strip binds its Mode combobox to.
#: They are the Master Driver's own strings.
DRY_RUN = "Dry Run"
LIVE_UPDATE = "Live Update"
RUN_MODES = (DRY_RUN, LIVE_UPDATE)

#: The summary's middle line, per run kind: a load walk reads, an apply changes.
SCAN_LABEL = "Files read"
APPLY_LABEL = "Files changed"


class TagEditorApp(AnalysisTagToolApp):
    """Interactive grid for editing common tag fields across audio files."""

    #: Manifest id, used by the shared preset/scaffold hooks.
    TOOL_ID: str = DRIVER_TOOL_ID

    #: Shipped guide the Help button opens.  Registered in
    #: ``audio_suite_shared.platform_utils.guide_to_program``; an empty value
    #: would make the inherited ``_open_help`` a silent no-op.
    HELP_GUIDE = "Tag_Editor_User_Guide.docx"

    TAGGED_LABEL: str = SCAN_LABEL
    DRY_COMPLETE_LABEL: str = "Apply Complete!"
    LIVE_COMPLETE_LABEL: str = "Tags Written!"

    #: Rows the finished run adds to the summary in the report and the Results
    #: tab.  A tuple replaced per completion, never mutated in place, so a
    #: finished run's row cannot survive into the next one.
    _summary_rows: tuple[tuple[str, str], ...] = ()

    def __init__(self, root: tk.Tk, *, apply_argv: bool = True) -> None:
        """Initialise the Tag Editor window.

        Args:
            root: Tk root window.
            apply_argv: Whether to apply the Master-Driver handshake from
                ``sys.argv``.  The ``--directory`` module entry pre-populates
                the source itself and starts the walk, so it opts out.
        """
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Tag Editor",
            "tag_editor_window",
            "tag_editor",
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path: tk.StringVar = tk.StringVar()
        #: The strip's Mode value; the only write path for dry/live.
        self.run_mode: tk.StringVar = tk.StringVar(value=DRY_RUN)
        self.field_var: tk.StringVar = tk.StringVar(value="title")
        self.value_var: tk.StringVar = tk.StringVar()
        self.clear_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.bulk_operation_var: tk.StringVar = tk.StringVar(value="Set Blank")
        self.bulk_field_var: tk.StringVar = tk.StringVar(value="genre")
        self.second_field_var: tk.StringVar = tk.StringVar(value="album_artist")
        self.case_mode_var: tk.StringVar = tk.StringVar(value="Title Case")

        #: Mirrors of the driver's orchestration strip.  Auto Start/Auto End are
        #: honoured; Clear Logs and Parallel are display-only because the
        #: driver executes them.
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        #: Read by ``UniversalCLIHandler`` from the parsed handshake and by the
        #: shared completion handler, which closes the window when it is set.
        self.auto_end: bool = False

        #: Master Driver handshake: the panel is locked when it launched this
        #: process.  A caller that opted out is not a driven launch, whatever
        #: its argv length says.
        self._launched_from_driver = apply_argv and cli_args.was_launched_from_driver()

        #: The grid's model: iid (the file path) -> (path, editable values).
        self._rows: dict[str, tuple[Path, dict[str, str | None]]] = {}

        #: The processor is kept so Stop can signal the walk it started.
        self.processor = TagEditorProcessor()

        #: Filled at the start of a run with the report path inside the scanned
        #: folder; blank until then, which makes View Log say so instead of
        #: opening the suite log.
        self._log_path: str = ""

        #: Per-apply-run context the completion handler adds to the report and
        #: the summary (CSV bookkeeping), captured before the thread starts so
        #: the completion signature stays the processor's payload plus the
        #: report header.
        self._pending_extra_entries: tuple[str, ...] = ()
        self._pending_extra_summary: tuple[tuple[str, str], ...] = ()
        self._pending_warnings: tuple[str, ...] = ()

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
        """Build the window: Help bar, three standard tabs, shared Setup strip."""
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
            field_var=self.field_var,
            value_var=self.value_var,
            clear_var=self.clear_var,
            bulk_operation_var=self.bulk_operation_var,
            bulk_field_var=self.bulk_field_var,
            second_field_var=self.second_field_var,
            case_mode_var=self.case_mode_var,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            on_stop=self.stop_processing,
            on_apply_selection=self.apply_selection,
            on_apply_bulk=self.apply_bulk_selection,
            on_import_csv=self.import_csv,
            on_export_csv=self.export_csv,
            on_tree_select=self._on_tree_select,
            driver_locked=self._launched_from_driver,
            modes=RUN_MODES,
        )
        self.setup_frame = setup_widgets["setup_frame"]
        self.start_btn: tk.Button = setup_widgets["start_btn"]
        self.stop_btn: tk.Button = setup_widgets["stop_btn"]
        self.tree: ttk.Treeview = setup_widgets["tree"]
        self.value_entry: tk.Entry = setup_widgets["value_entry"]
        self.controls_panel = setup_widgets["controls_panel"]

        # Single-threaded walks: the shared tab's slot grid is not requested.
        proc_widgets: dict[str, Any] = processing_tab.build(tab_processing_frame)
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
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

    # ── Load run ──────────────────────────────────────────────────────────────

    def start_processing(self) -> None:
        """Validate the source folder, then launch the load walk."""
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

        self.TAGGED_LABEL = SCAN_LABEL
        self._summary_rows = ()
        self._pending_extra_entries = ()
        self._pending_extra_summary = ()
        self._pending_warnings = ()
        self._log_path = os.path.join(folder, RUN_REPORT_SCAN)
        header: list[str] = [
            "TAG EDITOR REPORT\n",
            "Action: load library\n",
            f"Directory: {folder}\n",
            "=" * 60 + "\n",
        ]

        self._prepare_run("Scanning library...")
        logger.info("start_processing: folder=%s", folder)
        threading.Thread(
            target=self._run_scan,
            args=(folder, header),
            daemon=True,
        ).start()

    @handle_audio_errors(reraise=False, context="tag_editor_app_scan")
    def _run_scan(self, folder: str, header: list[str]) -> None:
        """Background thread: delegate to :func:`processor.run_scan`.

        The report path is set before the walk starts, because the shared
        completion handler writes the report it is handed to ``_log_path``.

        Args:
            folder: Root directory to walk.
            header: Report header lines for this run.
        """
        run_scan(
            folder,
            on_progress=self._on_progress,
            on_complete=lambda **kw: self._finish_scan(header=header, **kw),
            on_error=self._on_error,
            processor=self.processor,
        )

    def stop_processing(self) -> None:
        """Request the running walk to stop and update the status line."""
        self.processor.stop()
        self.overall_status.set("Stopping...")

    def _finish_scan(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        rows: list[TagRow],
        **_extra: Any,
    ) -> None:
        """Fill the grid from the walk's rows, then finish as every peer does.

        Bound by the wiring lambda rather than overriding ``_on_complete``: the
        payload carries ``rows``, which the shared base never learns, and a
        required field an override adds to the supertype's signature is a type
        error.

        Runs on the worker thread before the shared base writes the report, so
        the grid fill is marshalled onto the Tk thread.

        Args:
            header: Report header lines for this run.
            total: Files the walk visited.
            processed: Files it finished visiting.
            skipped: Files left alone (unsupported format).
            errors: Files whose tags could not be read.
            duration_secs: Wall-clock run time.
            log_entries: The per-file report lines.
            rows: The loaded grid rows.
            **_extra: Any other completion field the processor publishes.
        """
        self.TAGGED_LABEL = SCAN_LABEL
        self._summary_rows = (
            (("Audio files", f"{len(rows)} of {total} files"),) if total else ()
        )
        self.root.after(0, self._fill_grid, rows)
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

    def _fill_grid(self, rows: list[TagRow]) -> None:
        """Replace the grid with *rows* (main thread).

        Args:
            rows: The rows the load walk produced, in walk order.
        """
        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        for row in rows:
            iid = str(row.path)
            values = tuple(row.values.get(field) or "" for field in FIELD_LABELS)
            self.tree.insert("", "end", iid=iid, values=(row.path.name, *values))
            self._rows[iid] = (row.path, dict(row.values))
        self.overall_status.set(f"Loaded {len(rows)} audio file(s)")

    # ── Apply runs ────────────────────────────────────────────────────────────

    def apply_selection(self) -> None:
        """Apply the selected field edit to every highlighted row."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Tag Editor", "Select at least one file row.")
            return
        path = self._rows.get(selection[0])
        if path is None:
            messagebox.showwarning("Tag Editor", "Load the grid before editing.")
            return
        try:
            field = normalize_field(self.field_var.get())
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return

        value = None if self.clear_var.get() else self.value_var.get()
        edits = [
            FieldEdit(path=self._rows[iid][0], field=field, value=value)
            for iid in selection
            if iid in self._rows
        ]
        label = FIELD_LABELS.get(field, field)
        self._start_apply(edits, action=f"Single field edit: {label}")

    def apply_bulk_selection(self) -> None:
        """Apply the selected bulk operation to every highlighted row."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Tag Editor", "Select at least one file row.")
            return
        rows = [
            TagRow(path=self._rows[iid][0], values=dict(self._rows[iid][1]))
            for iid in selection
            if iid in self._rows
        ]
        if not rows:
            messagebox.showwarning("Tag Editor", "Load the grid before editing.")
            return
        operation = self.bulk_operation_var.get()
        try:
            edits = build_bulk_edits(
                rows,
                operation,
                self.bulk_field_var.get(),
                second_field=self.second_field_var.get(),
                case_mode=self.case_mode_var.get(),
            )
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return
        if not edits:
            self.overall_status.set(
                f"{operation}: no changes — every selected row already matches."
            )
            return
        self._start_apply(edits, action=f"Bulk operation: {operation}")

    def import_csv(self) -> None:
        """Apply a CSV of per-file field edits to the loaded library."""
        directory = self.folder_path.get().strip()
        if not directory:
            messagebox.showerror(
                "Tag Editor", "Select a music library directory first."
            )
            return
        selected = filedialog.askopenfilename(
            title="Import Tag CSV",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not selected:
            return
        try:
            plan = build_import_plan(Path(selected), Path(directory))
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return

        extra_summary: list[tuple[str, str]] = [
            ("CSV rows read", str(plan.row_count)),
        ]
        if plan.ignored_columns:
            extra_summary.append(("Ignored columns", ", ".join(plan.ignored_columns)))
        self._start_apply(
            plan.edits,
            action=f"CSV import: {Path(selected).name}",
            extra_entries=tuple(
                f"[SKIPPED]   CSV row: {row_error}\n" for row_error in plan.row_errors
            ),
            extra_summary=tuple(extra_summary),
            warnings=tuple(plan.row_errors),
        )

    def export_csv(self) -> None:
        """Write the loaded grid to a CSV file."""
        if not self._rows:
            messagebox.showwarning("Tag Editor", "Load the grid before exporting.")
            return
        selected = filedialog.asksaveasfilename(
            title="Export Tag CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
        )
        if not selected:
            return
        rows = [
            TagRow(path=path, values=dict(values))
            for path, values in self._rows.values()
        ]
        directory = self.folder_path.get().strip()
        try:
            written = export_csv(
                rows,
                Path(selected),
                Path(directory) if directory else None,
            )
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return
        self.overall_status.set(f"Exported {written} file row(s) to {selected}")

    def _start_apply(
        self,
        edits: list[FieldEdit],
        *,
        action: str,
        extra_entries: tuple[str, ...] = (),
        extra_summary: tuple[tuple[str, str], ...] = (),
        warnings: tuple[str, ...] = (),
    ) -> None:
        """Prepare the run UI and launch an apply run on a worker thread.

        Args:
            edits: The field edits to apply.
            action: What the run is doing, for the report header.
            extra_entries: Report lines the run adds beyond its edit lines
                (CSV row failures).
            extra_summary: Extra summary rows for the report and Results panel.
            warnings: Messages the finished run shows in a dialog (CSV rows
                that could not be planned).
        """
        folder = self.folder_path.get().strip()
        if not folder:
            messagebox.showerror(
                "Tag Editor", "Select a music library directory first."
            )
            return
        if not edits:
            self.overall_status.set(f"{action}: no edits to apply.")
            return

        is_dry_run = self.run_mode.get() == DRY_RUN
        self._log_path = os.path.join(
            folder, RUN_REPORT_DRY_RUN if is_dry_run else RUN_REPORT_LIVE
        )
        self.TAGGED_LABEL = APPLY_LABEL
        self._summary_rows = ()
        self._pending_extra_entries = extra_entries
        self._pending_extra_summary = extra_summary
        self._pending_warnings = warnings

        files = len({str(edit.path) for edit in edits})
        header: list[str] = [
            "TAG EDITOR REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Directory: {folder}\n",
            f"Action: {action}\n",
            f"Files selected: {files}\n",
            "=" * 60 + "\n",
        ]

        self._prepare_run(f"Applying: {action}")
        logger.info(
            "start_apply: action=%s files=%d edits=%d dry_run=%s",
            action,
            files,
            len(edits),
            is_dry_run,
        )
        threading.Thread(
            target=self._run_apply,
            args=(list(edits), is_dry_run, header),
            daemon=True,
        ).start()

    @handle_audio_errors(reraise=False, context="tag_editor_app_apply")
    def _run_apply(
        self,
        edits: list[FieldEdit],
        is_dry_run: bool,
        header: list[str],
    ) -> None:
        """Background thread: delegate to :func:`processor.run_apply`.

        Args:
            edits: The field edits to apply.
            is_dry_run: Whether the run may write.
            header: Report header lines for this run.
        """
        run_apply(
            edits,
            is_dry_run=is_dry_run,
            on_progress=self._on_progress,
            on_complete=lambda **kw: self._finish_apply(header=header, **kw),
            on_error=self._on_error,
            processor=self.processor,
        )

    def _finish_apply(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        results: list[EditResult],
        changed: int,
        written: int,
        **_extra: Any,
    ) -> None:
        """Record the run's summary rows, then finish as every peer does.

        Args:
            header: Report header lines for this run.
            total: Files in the batch.
            processed: Files handled.
            skipped: Files with nothing to change.
            errors: Files with at least one failed edit.
            duration_secs: Wall-clock run time.
            log_entries: The per-edit report lines.
            results: One edit outcome per requested edit.
            changed: Files whose values changed (or would, in a dry run).
            written: Individual tag writes performed.
            **_extra: Any other completion field the processor publishes.
        """
        self.TAGGED_LABEL = APPLY_LABEL
        self._summary_rows = (
            ("Tag edits", f"{len(results)} planned, {written} written"),
            *self._pending_extra_summary,
        )
        self.root.after(0, self._refresh_rows, results)
        self.root.after(0, self._disable_stop)
        super()._on_complete(
            header=header,
            total=total,
            processed=processed,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            log_entries=list(log_entries) + list(self._pending_extra_entries),
            **_extra,
        )
        warnings = self._pending_warnings
        if warnings:
            self.root.after(0, self._warn_rows, warnings)

    def _summary_extras(self) -> list[tuple[str, str]]:
        """Return this run's rows for the report and the Results panel."""
        return list(self._summary_rows)

    def _refresh_rows(self, results: list[EditResult]) -> None:
        """Update the grid from an apply run's results (main thread).

        Args:
            results: One outcome per edit; failed edits leave the row alone.
        """
        for result in results:
            if result.error is None:
                self._update_row(result)

    def _warn_rows(self, warnings: tuple[str, ...]) -> None:
        """Show the CSV rows this run could not plan (main thread)."""
        messagebox.showwarning("Tag Editor", "\n".join(dict.fromkeys(warnings)))

    # ── Shared run plumbing ───────────────────────────────────────────────────

    def _prepare_run(self, status_text: str) -> None:
        """Reset the run UI and move to the Processing tab.

        Args:
            status_text: The status line the run starts with.
        """
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state=tk.NORMAL)
        self.notebook.select(self._tab_processing)
        self.file_listbox.delete(0, tk.END)
        self._reset_progress_ui()
        self.overall_status.set(status_text)

    def _disable_stop(self) -> None:
        """Disable the Stop button (main thread; after a finished run)."""
        self.stop_btn.config(state=tk.DISABLED)

    def _show_error_dialog(self, message: str) -> None:
        """Report a fatal error and hand the controls back."""
        super()._show_error_dialog(message)
        self._disable_stop()

    # ── Grid interaction ──────────────────────────────────────────────────────

    def _on_tree_select(self, _event: object) -> None:
        """Populate the edit form from the single selected row."""
        selection = self.tree.selection()
        if len(selection) != 1 or selection[0] not in self._rows:
            return
        _path, values = self._rows[selection[0]]
        field = normalize_field(self.field_var.get())
        self.value_var.set(values.get(field) or "")
        self.clear_var.set(False)

    def _update_row(self, result: EditResult) -> None:
        """Refresh one grid row from an edit result.

        Args:
            result: Edit result whose field should be updated in place.
        """
        iid = str(result.path)
        if iid not in self._rows:
            return
        path, values = self._rows[iid]
        values[result.field] = result.new_value
        self.tree.set(iid, result.field, result.new_value or "")
        self._rows[iid] = (path, values)


def main(directory: str | None = None) -> None:
    """Launch the Tag Editor window.

    The driver's handshake is applied by the window itself (as every peer's
    does): ``TagEditorApp`` mirrors the Mode, Auto Start/Auto End and the
    display flags onto the Run Controls strip, locks the panel when the driver
    launched the process, and schedules the load walk only when the driver asked
    for it.  A path passed to this function directly — the module entry — keeps
    its documented immediate-start behaviour.

    Args:
        directory: Optional path to pre-populate the source field and scan
            immediately.  When ``None``, the Master-Driver argv is applied by
            the window instead.
    """
    root = tk.Tk()
    bootstrap_theme()
    apply_argv = directory is None and cli_args.looks_like_driver_argv()
    app = TagEditorApp(root, apply_argv=apply_argv)

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
