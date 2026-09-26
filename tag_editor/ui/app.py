"""app.py — Tkinter interface for the freeform Tag Editor."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from audio_suite_shared.app_bootstrap import BaseSuiteApp
from audio_suite_shared.exceptions import AudioDirectoryError, AudioSuiteError
from tag_editor.core.csv_io import build_import_plan, export_csv
from tag_editor.core.processor import (
    BULK_OPERATION_LABELS,
    CASE_MODE_LABELS,
    FIELD_LABELS,
    EditResult,
    FieldEdit,
    TagEditorProcessor,
    TagRow,
    normalize_field,
    summarize_results,
)


class TagEditorApp(BaseSuiteApp):
    """Interactive grid for editing common tag fields across audio files."""

    HELP_GUIDE = "Tag_Editor_User_Guide.docx"

    def __init__(
        self,
        root: tk.Tk,
        directory: str = "",
        live_mode: bool = False,
    ) -> None:
        """Initialise the Tag Editor window.

        Args:
            root: Tk root window.
            directory: Optional music directory to load immediately.
            live_mode: When True, Apply writes tags; when False, it previews.
        """
        super().__init__(
            root,
            "Tag Editor",
            "tag_editor_window",
            "tag_editor",
            help_guide=self.HELP_GUIDE,
        )
        self.processor = TagEditorProcessor()
        self.directory = tk.StringVar(value=directory)
        self.field_var = tk.StringVar(value="title")
        self.value_var = tk.StringVar()
        self.clear_var = tk.BooleanVar(value=False)
        self.bulk_operation_var = tk.StringVar(value=BULK_OPERATION_LABELS["set_blank"])
        self.bulk_field_var = tk.StringVar(value="genre")
        self.second_field_var = tk.StringVar(value="album_artist")
        self.case_mode_var = tk.StringVar(value=CASE_MODE_LABELS["title"])
        self.dry_run = tk.BooleanVar(value=not live_mode)
        self.status_var = tk.StringVar(
            value="Ready. Select a folder and load the grid."
        )
        self._rows: dict[str, tuple[Path, dict[str, str | None]]] = {}
        self._setup_ui()
        if directory:
            self.load_library()

    def _setup_ui(self) -> None:
        main = ttk.Frame(self.root, padding=10)
        main.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.root.rowconfigure(0, weight=1)
        self.root.columnconfigure(0, weight=1)
        main.rowconfigure(3, weight=1)
        main.columnconfigure(0, weight=1)

        folder_frame = ttk.LabelFrame(main, text="Music Library", padding=8)
        folder_frame.grid(row=0, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        folder_frame.columnconfigure(0, weight=1)
        ttk.Entry(folder_frame, textvariable=self.directory).grid(
            row=0, column=0, sticky=(tk.W, tk.E), padx=(0, 5)
        )
        ttk.Button(folder_frame, text="Browse...", command=self._browse_directory).grid(
            row=0, column=1, padx=(0, 5)
        )
        ttk.Button(folder_frame, text="Load Grid", command=self.load_library).grid(
            row=0, column=2, padx=(0, 5)
        )
        ttk.Button(folder_frame, text="Import CSV...", command=self.import_csv).grid(
            row=0, column=3, padx=(0, 5)
        )
        ttk.Button(folder_frame, text="Export CSV...", command=self.export_csv).grid(
            row=0, column=4
        )

        edit_frame = ttk.LabelFrame(main, text="Single Field Edit", padding=8)
        edit_frame.grid(row=1, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        ttk.Label(edit_frame, text="Field:").grid(row=0, column=0, padx=(0, 5))
        field_names = list(FIELD_LABELS)
        ttk.Combobox(
            edit_frame,
            textvariable=self.field_var,
            values=field_names,
            state="readonly",
            width=16,
        ).grid(row=0, column=1, padx=(0, 10))
        ttk.Label(edit_frame, text="Value:").grid(row=0, column=2, padx=(0, 5))
        self.value_entry = ttk.Entry(edit_frame, textvariable=self.value_var, width=45)
        self.value_entry.grid(row=0, column=3, sticky=(tk.W, tk.E), padx=(0, 10))
        ttk.Checkbutton(edit_frame, text="Clear field", variable=self.clear_var).grid(
            row=0, column=4, padx=(0, 10)
        )
        ttk.Checkbutton(edit_frame, text="Dry Run", variable=self.dry_run).grid(
            row=0, column=5, padx=(0, 10)
        )
        ttk.Button(
            edit_frame, text="Apply to Selection", command=self.apply_selection
        ).grid(row=0, column=6)

        bulk_frame = ttk.LabelFrame(main, text="Bulk Operations", padding=8)
        bulk_frame.grid(row=2, column=0, sticky=(tk.W, tk.E), pady=(0, 8))
        ttk.Label(bulk_frame, text="Operation:").grid(row=0, column=0, padx=(0, 5))
        ttk.Combobox(
            bulk_frame,
            textvariable=self.bulk_operation_var,
            values=list(BULK_OPERATION_LABELS.values()),
            state="readonly",
            width=30,
        ).grid(row=0, column=1, padx=(0, 10))
        ttk.Label(bulk_frame, text="Field:").grid(row=0, column=2, padx=(0, 5))
        ttk.Combobox(
            bulk_frame,
            textvariable=self.bulk_field_var,
            values=list(FIELD_LABELS),
            state="readonly",
            width=16,
        ).grid(row=0, column=3, padx=(0, 10))
        ttk.Label(bulk_frame, text="Swap With:").grid(row=0, column=4, padx=(0, 5))
        ttk.Combobox(
            bulk_frame,
            textvariable=self.second_field_var,
            values=list(FIELD_LABELS),
            state="readonly",
            width=16,
        ).grid(row=0, column=5, padx=(0, 10))
        ttk.Label(bulk_frame, text="Case:").grid(row=0, column=6, padx=(0, 5))
        ttk.Combobox(
            bulk_frame,
            textvariable=self.case_mode_var,
            values=list(CASE_MODE_LABELS.values()),
            state="readonly",
            width=12,
        ).grid(row=0, column=7, padx=(0, 10))
        ttk.Button(
            bulk_frame, text="Apply Bulk", command=self.apply_bulk_selection
        ).grid(row=0, column=8)

        grid_frame = ttk.Frame(main)
        grid_frame.grid(row=3, column=0, sticky=(tk.W, tk.E, tk.N, tk.S), pady=(0, 8))
        grid_frame.rowconfigure(0, weight=1)
        grid_frame.columnconfigure(0, weight=1)
        columns = ("file", *tuple(FIELD_LABELS))
        self.tree = ttk.Treeview(
            grid_frame, columns=columns, show="headings", selectmode="extended"
        )
        self.tree.heading("file", text="File")
        self.tree.column("file", width=260, stretch=True)
        for field, label in FIELD_LABELS.items():
            self.tree.heading(field, text=label)
            self.tree.column(field, width=120, stretch=True)
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        scrollbar = ttk.Scrollbar(
            grid_frame, orient=tk.VERTICAL, command=self.tree.yview
        )
        self.tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.grid(row=0, column=1, sticky=(tk.N, tk.S))
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        status = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN)
        status.grid(row=1, column=0, sticky=(tk.W, tk.E), padx=10, pady=(0, 5))

    def _browse_directory(self) -> None:
        """Open a directory chooser and update the library path."""
        directory = filedialog.askdirectory(title="Select Music Library Directory")
        if directory:
            self.directory.set(directory)

    def load_library(self) -> bool:
        """Scan the selected directory and populate the editable grid.

        Returns:
            True when the grid was loaded; False when validation failed.
        """
        directory = self.directory.get().strip()
        if not directory:
            messagebox.showerror(
                "Tag Editor", "Select a music library directory first."
            )
            return False
        try:
            rows = self.processor.scan_directory(directory)
        except AudioDirectoryError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return False
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return False

        self.tree.delete(*self.tree.get_children())
        self._rows.clear()
        for row in rows:
            iid = str(row.path)
            values = tuple(row.values.get(field) or "" for field in FIELD_LABELS)
            self.tree.insert("", "end", iid=iid, values=(row.path.name, *values))
            self._rows[iid] = (row.path, row.values)
        self.status_var.set(f"Loaded {len(rows)} audio file(s) from {directory}")
        return True

    def _on_tree_select(self, _event: object) -> None:
        """Populate the edit form from the single selected row."""
        selection = self.tree.selection()
        if len(selection) != 1 or selection[0] not in self._rows:
            return
        _path, values = self._rows[selection[0]]
        field = normalize_field(self.field_var.get())
        current_value = values.get(field)
        self.value_var.set(current_value or "")
        self.clear_var.set(False)

    def apply_selection(self) -> None:
        """Apply the selected field edit to every highlighted row."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Tag Editor", "Select at least one file row.")
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
        ]
        try:
            results = self.processor.apply_edits(edits, dry_run=self.dry_run.get())
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return
        self._report_results(results)

    def apply_bulk_selection(self) -> None:
        """Apply the selected bulk operation to every highlighted row."""
        selection = self.tree.selection()
        if not selection:
            messagebox.showwarning("Tag Editor", "Select at least one file row.")
            return
        rows = [
            TagRow(path=self._rows[iid][0], values=dict(self._rows[iid][1]))
            for iid in selection
        ]
        try:
            results = self.processor.apply_bulk(
                rows,
                self.bulk_operation_var.get(),
                self.bulk_field_var.get(),
                second_field=self.second_field_var.get(),
                case_mode=self.case_mode_var.get(),
                dry_run=self.dry_run.get(),
            )
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return
        self._report_results(results)

    def _report_results(self, results: list[EditResult]) -> None:
        """Refresh successful rows and surface an aggregate apply summary."""
        stats = summarize_results(results)
        for result in results:
            if result.error is None:
                self._update_row(result)
        mode = "previewed" if self.dry_run.get() else "written"
        self.status_var.set(
            f"{stats.changed} change(s) {mode}, {stats.unchanged} unchanged, "
            f"{stats.errors} error(s)"
        )
        if stats.errors:
            messages = self._error_messages(results)
            messagebox.showwarning(
                "Tag Editor",
                "\n".join(dict.fromkeys(messages)),
            )

    @staticmethod
    def _error_messages(results: list[EditResult]) -> list[str]:
        """Collect the failure messages from edit results.

        Only results that actually failed are reported: a successful result
        carries ``error=None`` and must never surface as "Unknown error".

        Args:
            results: Edit results from a grid apply or CSV import.

        Returns:
            The deduplicated-by-caller list of failure messages, in result
            order.
        """
        return [result.error for result in results if result.error is not None]

    def import_csv(self) -> None:
        """Apply a CSV of per-file field edits to the loaded library."""
        directory = self.directory.get().strip()
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
            results = self.processor.apply_edits(plan.edits, dry_run=self.dry_run.get())
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return

        stats = summarize_results(results)
        for result in results:
            if result.error is None:
                self._update_row(result)
        mode = "previewed" if self.dry_run.get() else "written"
        errors = stats.errors + len(plan.row_errors)
        self.status_var.set(
            f"Imported {plan.row_count} CSV row(s): {stats.changed} change(s) "
            f"{mode}, {stats.unchanged} unchanged, {errors} error(s)"
        )
        if plan.ignored_columns:
            self.status_var.set(
                f"{self.status_var.get()} | Ignored columns: "
                f"{', '.join(plan.ignored_columns)}"
            )
        messages = self._error_messages(results)
        messages.extend(plan.row_errors)
        if messages:
            messagebox.showwarning(
                "Tag Editor",
                "\n".join(dict.fromkeys(messages)),
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
        directory = self.directory.get().strip()
        try:
            written = export_csv(
                rows,
                Path(selected),
                Path(directory) if directory else None,
            )
        except AudioSuiteError as exc:
            messagebox.showerror("Tag Editor", str(exc))
            return
        self.status_var.set(f"Exported {written} file row(s) to {selected}")

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


def main(directory: str | None = None, live_mode: bool = False) -> None:
    """Launch the Tag Editor window.

    Args:
        directory: Optional directory to load immediately.
        live_mode: When True, Apply starts in live-write mode.
    """
    root = tk.Tk()
    TagEditorApp(root, directory=directory or "", live_mode=live_mode)
    root.mainloop()
