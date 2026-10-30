"""setup_tab.py — Setup tab for the Tag Editor.

Changed in 2.2.1: extracted from ``ui/app.py`` into the module layout every
peer uses (maintenance item U5).  The tab is a ``BaseSetupFrame``, so the
shared Run Controls strip supplies the source row, the Browse dialog, the
Mode combobox and the driver's orchestration display, and the start button is
the suite's full-width one.  The grid — this tool's editing surface — is
tool-specific and lives in ``_build_options``.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame

from ..core.processor import BULK_OPERATION_LABELS, CASE_MODE_LABELS, FIELD_LABELS


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    field_var: tk.StringVar,
    value_var: tk.StringVar,
    clear_var: tk.BooleanVar,
    bulk_operation_var: tk.StringVar,
    bulk_field_var: tk.StringVar,
    second_field_var: tk.StringVar,
    case_mode_var: tk.StringVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    on_stop: Callable[[], None],
    on_apply_selection: Callable[[], None],
    on_apply_bulk: Callable[[], None],
    on_import_csv: Callable[[], None],
    on_export_csv: Callable[[], None],
    on_tree_select: Callable[[object], None],
    driver_locked: bool = False,
    modes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """
    Populate the Setup tab.

    Args:
        parent:              The tab Frame to populate.
        folder_path:         StringVar bound to the source directory entry.
        run_mode:            StringVar for the Dry Run / Live Update combobox.
        auto_start_var:      BooleanVar bound to the Auto Start checkbox.
        auto_end_var:        BooleanVar bound to the Auto End checkbox.
        clear_logs_var:      Tk variable mirroring the driver's Clear Logs state.
        parallel_var:        Tk variable mirroring the driver's Parallel state.
        field_var:           StringVar holding the selected editable field.
        value_var:           StringVar holding the value to write.
        clear_var:           BooleanVar for the "Clear field" checkbox.
        bulk_operation_var:  StringVar holding the selected bulk operation label.
        bulk_field_var:      StringVar holding the bulk target field.
        second_field_var:    StringVar holding the swap partner field.
        case_mode_var:       StringVar holding the case-conversion mode label.
        on_browse:           Callback for the Browse button.
        on_start:            Callback for the start button.
        on_stop:             Callback for the Stop button.
        on_apply_selection:  Callback for "Apply to Selection".
        on_apply_bulk:       Callback for "Apply Bulk".
        on_import_csv:       Callback for "Import CSV...".
        on_export_csv:       Callback for "Export CSV...".
        on_tree_select:      Callback for a grid selection change.
        driver_locked:       True when launched via the Master Driver; locks
                             the Run Controls panel to inherited values.
        modes:               Mode labels for the strip; the driver's own strings.

    Returns:
        Dict with keys: setup_frame, start_btn, controls_panel, stop_btn,
        tree, value_entry.
    """
    frame = _SetupFrame(
        parent,
        title="Tag Editor",
        start_text="LOAD & SCAN LIBRARY",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        browse_text="Browse & Scan",
        driver_locked=driver_locked,
        modes=modes,
        field_var=field_var,
        value_var=value_var,
        clear_var=clear_var,
        bulk_operation_var=bulk_operation_var,
        bulk_field_var=bulk_field_var,
        second_field_var=second_field_var,
        case_mode_var=case_mode_var,
        on_stop=on_stop,
        on_apply_selection=on_apply_selection,
        on_apply_bulk=on_apply_bulk,
        on_import_csv=on_import_csv,
        on_export_csv=on_export_csv,
        on_tree_select=on_tree_select,
    )
    widgets = frame.get_widgets()
    widgets["setup_frame"] = frame
    return widgets


class _SetupFrame(BaseSetupFrame):
    """Tag Editor Setup tab skeleton on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        *,
        field_var: tk.StringVar,
        value_var: tk.StringVar,
        clear_var: tk.BooleanVar,
        bulk_operation_var: tk.StringVar,
        bulk_field_var: tk.StringVar,
        second_field_var: tk.StringVar,
        case_mode_var: tk.StringVar,
        on_stop: Callable[[], None],
        on_apply_selection: Callable[[], None],
        on_apply_bulk: Callable[[], None],
        on_import_csv: Callable[[], None],
        on_export_csv: Callable[[], None],
        on_tree_select: Callable[[object], None],
        **kwargs: Any,
    ) -> None:
        # Option state must be bound before super().__init__, which calls
        # _layout() -> _build_options() during construction.
        self._field_var = field_var
        self._value_var = value_var
        self._clear_var = clear_var
        self._bulk_operation_var = bulk_operation_var
        self._bulk_field_var = bulk_field_var
        self._second_field_var = second_field_var
        self._case_mode_var = case_mode_var
        self._on_stop = on_stop
        self._on_apply_selection = on_apply_selection
        self._on_apply_bulk = on_apply_bulk
        self._on_import_csv = on_import_csv
        self._on_export_csv = on_export_csv
        self._on_tree_select = on_tree_select
        #: Filled by ``_build_options`` and handed back by ``get_widgets``.
        self.tree: ttk.Treeview | None = None
        self.value_entry: tk.Entry | None = None
        self.stop_btn: tk.Button | None = None
        super().__init__(parent, **kwargs)

    def get_widgets(self) -> dict[str, Any]:
        """Return the widgets the window drives after construction."""
        widgets = super().get_widgets()
        widgets.update(
            {
                "stop_btn": self.stop_btn,
                "tree": self.tree,
                "value_entry": self.value_entry,
            }
        )
        return widgets

    def _build_options(self) -> None:
        """Emit the edit controls, the CSV buttons, the grid and Stop."""
        self._build_edit_frame()
        self._build_bulk_frame()
        self._build_csv_row()
        self._build_grid()

        # Stop sits above the shared full-width start button: a library scan is
        # cooperative, so stopping must not require switching tabs.
        stop_row = tk.Frame(self, bg=styles.BG_WHITE)
        stop_row.pack(fill="x", pady=(4, 0))
        self.stop_btn = tk.Button(
            stop_row,
            text="Stop",
            bg=styles.BG_LIGHT,
            fg=styles.FG_MAIN,
            font=styles.FONT_BUTTON,
            padx=15,
            pady=6,
            state=tk.DISABLED,
            command=self._on_stop,
        )
        self.stop_btn.pack(side=tk.RIGHT)

    def _build_edit_frame(self) -> None:
        """Build the single-field edit row."""
        frame = tk.LabelFrame(
            self,
            text="Single Field Edit",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            padx=10,
            pady=8,
        )
        frame.pack(fill="x", pady=(0, 8))

        tk.Label(
            frame,
            text="Field:",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT)
        ttk.Combobox(
            frame,
            textvariable=self._field_var,
            values=list(FIELD_LABELS),
            state="readonly",
            width=14,
        ).pack(side=tk.LEFT, padx=(5, 10))

        tk.Label(
            frame,
            text="Value:",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT)
        # The value entry grows with the window: a comment is written in place,
        # not one character at a time through a fixed-width box.
        self.value_entry = tk.Entry(
            frame,
            textvariable=self._value_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
            font=styles.FONT_BODY,
            relief=tk.SOLID,
            borderwidth=1,
        )
        self.value_entry.pack(side=tk.LEFT, fill="x", expand=True, padx=(5, 10))

        tk.Checkbutton(
            frame,
            text="Clear field",
            variable=self._clear_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            activebackground=styles.BG_WHITE,
            selectcolor=styles.BG_WHITE,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(
            frame, text="Apply to Selection", command=self._on_apply_selection
        ).pack(side=tk.LEFT)

    def _build_bulk_frame(self) -> None:
        """Build the bulk-operation row."""
        frame = tk.LabelFrame(
            self,
            text="Bulk Operations",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            padx=10,
            pady=8,
        )
        frame.pack(fill="x", pady=(0, 8))

        rows: tuple[tuple[str, tk.StringVar, list[str], int], ...] = (
            (
                "Operation:",
                self._bulk_operation_var,
                list(BULK_OPERATION_LABELS.values()),
                26,
            ),
            ("Field:", self._bulk_field_var, list(FIELD_LABELS), 14),
            ("Swap With:", self._second_field_var, list(FIELD_LABELS), 14),
            ("Case:", self._case_mode_var, list(CASE_MODE_LABELS.values()), 12),
        )
        for label, var, values, width in rows:
            tk.Label(
                frame,
                text=label,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                font=styles.FONT_BODY,
            ).pack(side=tk.LEFT, padx=(0, 5))
            ttk.Combobox(
                frame,
                textvariable=var,
                values=values,
                state="readonly",
                width=width,
            ).pack(side=tk.LEFT, padx=(0, 10))

        ttk.Button(frame, text="Apply Bulk", command=self._on_apply_bulk).pack(
            side=tk.LEFT
        )

    def _build_csv_row(self) -> None:
        """Build the CSV import/export row."""
        row = tk.Frame(self, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=(0, 8))
        tk.Label(
            row,
            text="Spreadsheet:",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(row, text="Import CSV...", command=self._on_import_csv).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(row, text="Export CSV...", command=self._on_export_csv).pack(
            side=tk.LEFT
        )

    def _build_grid(self) -> None:
        """Build the editable grid: the file rows and their tag values."""
        frame = tk.LabelFrame(
            self,
            text="Library Grid",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            padx=6,
            pady=6,
        )
        frame.pack(fill="both", expand=True)

        columns = ("file", *tuple(FIELD_LABELS))
        self.tree = ttk.Treeview(
            frame, columns=columns, show="headings", selectmode="extended"
        )
        self.tree.heading("file", text="File")
        self.tree.column("file", width=240, stretch=True)
        for field, label in FIELD_LABELS.items():
            self.tree.heading(field, text=label)
            self.tree.column(field, width=110, stretch=True)
        self.tree.grid(row=0, column=0, sticky=(tk.W, tk.E, tk.N, tk.S))
        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        yscroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky=(tk.N, tk.S))
        xscroll = ttk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.tree.xview)
        xscroll.grid(row=1, column=0, sticky=(tk.W, tk.E))
        self.tree.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)

        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
