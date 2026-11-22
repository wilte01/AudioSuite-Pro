"""Tkinter UI for the Tag Editor.

The Tag Editor is the suite's interactive grid: the load walk fills a table of
files and their editable tag values, and the user applies validated single-field
edits, bulk transformations or a CSV import to the rows they select.

Changed in 2.2.1: the window is built on the suite's shared pieces (maintenance
item U5) — the palette Help bar, a three-tab notebook, the shared Processing tab
(progress bar, per-file list, status line) and Results tab (View Log / Open
Folder) — and the Setup tab is a ``BaseSetupFrame``, so the shared Run Controls
strip supplies the source row, the browse dialog, the Mode combobox and the
driver's orchestration display.  At the time the app was an
``AnalysisTagToolApp``: the load walk and every apply run went through the
processor's ``run_*`` entry points, so the run drove the shared
progress/completion handlers, the browse dialog was the shared one (initial
directory, last-directory memory), the argv handshake was the positional one
every folder tool reads, and each run wrote its report into the scanned folder
(``tag_editor_scan_log.txt`` for the load walk,
``tag_editor_dry_run_log.txt`` / ``tag_editor_sync_log.txt`` for an apply), which
is the file View Log opens.

Changed in 2.6.0: the Setup tab's **Copy Fields…** and **Templates…** actions
(plan F-E7). A copied field set and a saved template both become ``FieldEdit``
lists for the selected rows, so the dry-run diff, the run report and the undo
batch are the window's existing apply path rather than a second writer.

Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, D8's wave 3), so the
shell owns the Help bar and the Processing and Results tabs and this tool keeps
its Setup panel and its grid.  Both run reports are written here now that the
window no longer inherits ``AnalysisTagToolApp``: each is serialised on the run's
thread with the ``SUMMARY:`` footer every peer writes, and the run's mode and
folder are snapshotted on the Tk thread in ``start_processing``/``_start_apply``
so the completion never reads a Tk variable off it.  Every callback the two run
kinds publish — the progress tick, the run error, the completion, the grid fill,
the row refresh and the CSV warnings — is a message on one ``SimpleQueue`` that
a poller the Tk thread starts drains, because the runs are raw
``threading.Thread`` workers and may not call ``root.after`` or a widget at all.
View Log and Open Folder are the shell's.

Changed in 2.9.0: that poller is the shared ``event_pump.pump_events``, so the
drain loop and its finished-run drain are the suite's one implementation (B2).

Changed in 2.9.0: the window keeps no tick id.  It has no close handler, so
nothing could ever cancel the pending tick, and a destroyed root drops its
``after`` callbacks itself (D30).

Changed in 2.9.0: the shell owns the hand-off - ``_start_worker`` builds the
queue and starts the thread, and ``_poll_ui_updates`` is inherited - so this
window supplies only ``_dispatch_ui_message`` (D31).
"""

from __future__ import annotations

import logging
import os
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Any

from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import (
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
)
from audio_suite_shared.styles import bootstrap_theme
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.tag_templates import (
    TagTemplate,
    load_templates,
    parse_fields,
    save_template,
    template_from_file,
)

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
from . import setup_tab

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


class TagEditorApp(SuiteApp):
    """Interactive grid for editing common tag fields across audio files."""

    title = "Tag Editor"
    window_key = "tag_editor_window"
    program_name = DRIVER_TOOL_ID
    #: Shipped guide the Help button opens.  Registered in
    #: ``audio_suite_shared.platform_utils.guide_to_program``; an empty value
    #: would make the shell's Help button a silent no-op.
    HELP_GUIDE = "Tag_Editor_User_Guide.docx"
    guide_name = HELP_GUIDE
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" 1. Setup ", " 2. Processing ", " 3. Results ")

    TAGGED_LABEL: str = SCAN_LABEL
    DRY_COMPLETE_LABEL: str = "Apply Complete!"
    LIVE_COMPLETE_LABEL: str = "Tags Written!"
    #: The heading the Results tab shows before a run; a finished run replaces
    #: it with the wording for its mode.
    completion_text: str = "Run Complete!"

    #: The manifest id the window has always declared (tests and the driver
    #: read it); ``program_name`` above is the shell's copy of the same value.
    TOOL_ID: str = DRIVER_TOOL_ID

    #: Set from argv in ``__init__``.  The default keeps an ``object.__new__``
    #: test shell on the interactive (modal-warning) path.
    _launched_from_driver: bool = False
    #: Read by the completion, which closes the window when it is set.
    auto_end: bool = False
    #: Built by the shell from the Setup panel.
    _setup_frame: Any = None
    #: The run's mode and folder, snapshotted on the Tk thread by
    #: ``start_processing``/``_start_apply`` so the completion reads no Tk
    #: variable.
    _run_mode: str = ""
    _run_folder: str = ""

    def __init__(self, root: tk.Tk, *, apply_argv: bool = True) -> None:
        """Initialise the Tag Editor window.

        Args:
            root: Tk root window.
            apply_argv: Whether to apply the Master-Driver handshake from
                ``sys.argv``.  The ``--directory`` module entry pre-populates
                the source itself and starts the walk, so it opts out.
        """
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

        #: Per-apply-run context the completion adds to the report and the
        #: summary (CSV bookkeeping), captured before the thread starts so the
        #: completion signature stays the processor's payload plus the report
        #: header.
        self._pending_extra_entries: tuple[str, ...] = ()
        self._pending_extra_summary: tuple[tuple[str, str], ...] = ()
        self._pending_warnings: tuple[str, ...] = ()

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
        """Emit the grid, the edit form and the run controls into the tab."""
        widgets: dict[str, Any] = setup_tab.build(
            parent,
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
            on_copy_fields=self.copy_fields,
            on_templates=self.templates,
            on_tree_select=self._on_tree_select,
            driver_locked=self._launched_from_driver,
            modes=RUN_MODES,
        )
        self._setup_frame = widgets["setup_frame"]
        self.start_btn = widgets["start_btn"]
        self.stop_btn = widgets["stop_btn"]
        self.tree: ttk.Treeview = widgets["tree"]
        self.value_entry: tk.Entry = widgets["value_entry"]
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

    def _apply_cli_args(self, parsed: cli_args.TagEditorArgs) -> None:
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

        self._pending_extra_entries = ()
        self._pending_extra_summary = ()
        self._pending_warnings = ()
        # Snapshot what the completion renders from, on the Tk thread: the
        # worker and its handler must not call .get().
        self._run_mode = self.run_mode.get()
        self._run_folder = folder
        self._log_path = os.path.join(folder, RUN_REPORT_SCAN)
        header: list[str] = [
            "TAG EDITOR REPORT\n",
            "Action: load library\n",
            f"Directory: {folder}\n",
            "=" * 60 + "\n",
        ]

        self._prepare_run("Scanning library...")
        logger.info("start_processing: folder=%s", folder)
        self._start_worker(self._run_scan, (folder, header))

    @handle_audio_errors(reraise=False, context="tag_editor_app_scan")
    def _run_scan(self, folder: str, header: list[str]) -> None:
        """Background thread: delegate to :func:`processor.run_scan`.

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
        """Write the walk's report, then queue the grid fill and the Results.

        Bound by the wiring lambda rather than overriding a shell handler: the
        payload carries ``rows``, which the shell never learns, and a required
        field an override adds to the supertype's signature is a type error.

        Runs on the worker thread: the report is written here, and every widget
        write is queued for the Tk poller.

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
        tagged = processed - skipped - errors
        summary_rows: tuple[tuple[str, str], ...] = (
            (("Audio files", f"{len(rows)} of {total} files"),) if total else ()
        )
        self._write_run_report(
            header=header,
            log_entries=log_entries,
            rows=summary_rows,
            total=total,
            tagged=tagged,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
        )
        self._ui_updates.put(("grid", rows))
        self._ui_updates.put(
            ("complete", total, tagged, skipped, errors, duration_secs, summary_rows)
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

    # ── Copy from a reference file and saved templates ────────────────────────

    def _selected_paths(self) -> list[Path]:
        """Return the file paths behind the current grid selection."""
        return [
            self._rows[iid][0] for iid in self.tree.selection() if iid in self._rows
        ]

    def copy_fields(self) -> None:
        """Copy chosen fields from a reference file onto the selected rows."""
        if not self._selected_paths():
            messagebox.showwarning("Tag Editor", "Select at least one file row.")
            return
        reference = filedialog.askopenfilename(
            title="Copy Fields From",
            filetypes=[
                (
                    "Audio files",
                    "*.mp3 *.flac *.m4a *.ogg *.opus *.wav *.aiff *.aif",
                ),
                ("All files", "*.*"),
            ],
        )
        if not reference:
            return
        requested = simpledialog.askstring(
            "Copy Fields",
            "Fields to copy (comma-separated):",
            initialvalue="title,artist,album,album_artist",
        )
        if not requested:
            return
        try:
            names = parse_fields(requested)
            template = template_from_file(reference, names)
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return
        absent = [name for name in names if name not in template.fields]
        edits = [
            FieldEdit(path=path, field=name, value=value)
            for path in self._selected_paths()
            for name, value in template.fields.items()
        ]
        if absent:
            self.overall_status.set(
                "Reference has none of: "
                f"{', '.join(absent)} - those fields are left alone."
            )
        self._start_apply(edits, action=f"Copy fields from {Path(reference).name}")

    def templates(self) -> None:
        """Save the selected row's values as a template, or apply a saved one."""
        saved = load_templates()
        listed = ", ".join(sorted(saved)) or "(none saved)"
        choice = simpledialog.askstring(
            "Templates",
            f"Saved: {listed}\n\nType a name to apply it, or save:<name> "
            "to save the selected row's values.",
        )
        if not choice:
            return
        name = choice.strip()
        if name.lower().startswith("save:"):
            self.save_selection_as_template(name.split(":", 1)[1].strip())
        else:
            self.apply_template_to_selection(name)

    def save_selection_as_template(self, name: str) -> bool:
        """Store the first selected row's editable values under *name*.

        Args:
            name: Template name.

        Returns:
            True when the template was saved.
        """
        cleaned = name.strip()
        if not cleaned:
            messagebox.showerror("Tag Editor", "A template needs a name.")
            return False
        paths = self._selected_paths()
        if not paths:
            messagebox.showwarning(
                "Tag Editor", "Select a file row to copy its values."
            )
            return False
        selection = self.tree.selection()
        values = dict(self._rows[selection[0]][1])
        fields = {
            field: value
            for field, value in values.items()
            if field in FIELD_LABELS and isinstance(value, str) and value
        }
        if not fields:
            messagebox.showwarning(
                "Tag Editor", "The selected row has no tag values to save."
            )
            return False
        try:
            save_template(
                TagTemplate(name=cleaned, fields=fields, source=str(paths[0]))
            )
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return False
        self.overall_status.set(f"Saved template '{cleaned}' ({len(fields)} field(s))")
        return True

    def apply_template_to_selection(self, name: str) -> bool:
        """Queue a saved template's editable fields for the selected rows.

        Args:
            name: Saved template name.

        Returns:
            True when an apply run was started.
        """
        template = load_templates().get(name)
        if template is None:
            messagebox.showerror("Tag Editor", f"No saved template named {name!r}.")
            return False
        paths = self._selected_paths()
        if not paths:
            messagebox.showwarning("Tag Editor", "Select at least one file row.")
            return False
        edits = [
            FieldEdit(path=path, field=field, value=value)
            for path in paths
            for field, value in template.fields.items()
            if field in FIELD_LABELS
        ]
        if not edits:
            messagebox.showerror(
                "Tag Editor", f"Template {name!r} has no editable grid fields."
            )
            return False
        self._start_apply(edits, action=f"Template: {name}")
        return True

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
        # Snapshot what the completion renders from, on the Tk thread.
        self._run_mode = DRY_RUN if is_dry_run else LIVE_UPDATE
        self._run_folder = folder
        self._log_path = os.path.join(
            folder, RUN_REPORT_DRY_RUN if is_dry_run else RUN_REPORT_LIVE
        )
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
        self._start_worker(self._run_apply, (list(edits), is_dry_run, header))

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
        """Write the apply run's report, then queue the grid and the Results.

        Runs on the worker thread: the report is written here, and every widget
        write is queued for the Tk poller.

        Args:
            header: Report header lines for this run.
            total: Files in the batch.
            processed: Files handled.
            skipped: Files with nothing to change.
            errors: Files with at least one failed edit.
            duration_secs: Wall-clock run time.
            log_entries: The per-edit report lines.
            results: One edit outcome per requested edit.
            changed: Files whose values changed (or would, in a dry run).  The
                report counts the same files through its per-file results.
            written: Individual tag writes performed.
            **_extra: Any other completion field the processor publishes.
        """
        self.TAGGED_LABEL = APPLY_LABEL
        tagged = processed - skipped - errors
        summary_rows: tuple[tuple[str, str], ...] = (
            ("Tag edits", f"{len(results)} planned, {written} written"),
            *self._pending_extra_summary,
        )
        self._write_run_report(
            header=header,
            log_entries=list(log_entries) + list(self._pending_extra_entries),
            rows=summary_rows,
            total=total,
            tagged=tagged,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
        )
        self._ui_updates.put(("results", results))
        self._ui_updates.put(
            ("complete", total, tagged, skipped, errors, duration_secs, summary_rows)
        )
        if self._pending_warnings:
            self._ui_updates.put(("warnings", self._pending_warnings))

    def _write_run_report(
        self,
        *,
        header: list[str],
        log_entries: list[str],
        rows: tuple[tuple[str, str], ...],
        total: int,
        tagged: int,
        skipped: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Serialise one run's report into ``_log_path``.

        The footer is the one every peer writes, so the run-report lock can read
        this tool's report the way it reads an adopter's.

        Args:
            header: Report header lines for this run.
            log_entries: The per-file report lines.
            rows: This run's extra summary rows.
            total: Files the run visited.
            tagged: Files handled without being skipped or erroring.
            skipped: Files left alone.
            errors: Files that failed.
            duration_secs: Wall-clock run time.
        """
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
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
            total: Files the run visited.
            tagged: Files handled without being skipped or erroring.
            skipped: Files left alone.
            errors: Files that failed.
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

    # ── Callbacks (queued from a run's thread — no widget writes) ─────────

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

        Called from the run's own thread, so it only queues; the tick is
        written by ``_dispatch_ui_message`` (AGENTS.md).

        Args:
            processed: Files finished so far.
            total: Files the run will attempt.
            skipped: Files left alone so far.
            errors: Files that failed so far.
            display_text: The per-file line the processor published.
            **_extra: The other progress fields the processor publishes.
        """
        self._ui_updates.put(
            ("progress", processed, total, skipped, errors, display_text)
        )

    def _on_error(self, message: str) -> None:
        """Queue a fatal run error for the Tk thread's poller.

        The processor publishes this from the run's thread and the shell's
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
        elif kind == "grid":
            _, rows = message
            self._fill_grid(rows)
        elif kind == "results":
            _, results = message
            self._refresh_rows(results)
        elif kind == "warnings":
            _, warnings = message
            self._warn_rows(warnings)
        elif kind == "complete":
            _, total, tagged, skipped, errors, duration_secs, rows = message
            self._render_finish(total, tagged, skipped, errors, duration_secs, rows)

    # ── Shared run plumbing ───────────────────────────────────────────────────

    def _prepare_run(self, status_text: str) -> None:
        """Reset the run UI and move to the Processing tab.

        Args:
            status_text: The status line the run starts with.
        """
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state=tk.NORMAL)
        self.notebook.select(self.processing_frame)
        self.file_listbox.delete(0, tk.END)
        self._reset_progress_ui()
        self.overall_status.set(status_text)

    def _reset_progress_ui(self) -> None:
        """Reset the bar and the counters (must be called on the Tk thread)."""
        self.progress["value"] = 0
        self.stats_label.config(text=self.processing_stats_text)

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
