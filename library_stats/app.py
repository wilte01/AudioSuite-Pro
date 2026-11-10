"""
app.py — LibraryStatsApp GUI dashboard.

Opens a tkinter window with matplotlib charts showing library statistics
derived from existing audio tags.  All data is read-only — no analysis or
tag writing is performed.

The window is built by ``audio_suite_shared.suite_app.SuiteApp``: the Help bar,
the notebook and the Processing and Results tabs come from the shell.  This
module supplies the Setup tab (run-controls strip, scan and export actions), the
five dashboard tabs (Summary, Charts, Missing Data, Completeness and Artwork
Gaps) and the scan itself.

Mode replaces the old Cache checkbox and Refresh button, because they were two
controls for one decision: ``Incremental Scan`` reuses the cache (the default),
``Full Scan`` rebuilds it, and ``Direct Scan`` reads the library without the
cache at all.  The Master Driver's ``--incremental``/``--refresh`` flags seed
the mode.

Changed in 1.3.0: figure building moved to the Tk-free ``library_stats.ui.charts``
(so the charts are testable without a window), the Completeness tab embeds the
missing-tags-by-album heatmap, and the Charts tab gains a completeness trend fed
by the snapshots each scan records in the cache (PLAN D38/D40/D41).

Changed in 1.0.1: parses the driver's argv and pre-fills directory, incremental/refresh
and the CSV/JSON exports.
Changed in 2.2.0: the Export dialog offers M3U and HTML beside CSV/JSON and
writes the format the chosen extension names, and a "Camelot column" checkbox
adds the harmonic-mixing key column to the CSV/HTML exports (functional
backlog F-05/F-06).
Changed in 2.3.1: the widget's text colours follow the suite theme instead of
Tk's symbolic defaults (PLAN_restoration_2026-10-31.md T-02).

Changed in 2.6.0: the Artwork Gaps tab lists the albums whose files lack
embedded artwork and can write a cover beside each from the picture one of its
files already carries.  That pass is the one write the dashboard offers, it runs
off the Tk thread through the same queue, and it writes its own run report
(``library_stats_artwork_log.txt``), which the tab's View Log opens.

Changed in 2.4.3: adopts ``SuiteApp`` (PLAN_2026-11-03_2.4.3_structure.md WP-8
order #3).  The old one-pane window — a toolbar, a status bar and a four-tab
notebook it built itself — becomes the shell's Setup, Processing and Results
tabs plus the four dashboard tabs as extra tabs; Cache and Refresh fold into the
run-controls Mode; the worker hands its result to the Tk thread through a
``SimpleQueue`` instead of calling ``root.after`` from the scan thread; and every
scan writes ``<scanned folder>/library_stats_scan_log.txt``, the report View Log
opens, with the suite's header/SUMMARY shape.
"""

from __future__ import annotations

import logging
import os
import queue
import sqlite3
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Literal

from audio_suite_shared import styles, suite_config
from audio_suite_shared.cli_helpers import was_launched_from_driver
from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.platform_utils import open_path
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from audio_suite_shared.ui_helpers import show_error_from_exception
from library_stats.core.artwork_gaps import (
    AlbumArtworkGap,
    CoverRun,
    missing_artwork_albums,
    run_cover_extraction,
)
from library_stats.core.completeness import (
    CompletenessReport,
    TagCompleteness,
    analyse_completeness,
    export_completeness_csv,
    export_completeness_json,
)
from library_stats.library_cache import LibraryCache

from .library_stats import (
    StatsReport,
    export_csv,
    export_html,
    export_json,
    export_m3u,
    scan_directory,
)
from .utils import cli_args

try:
    import matplotlib

    matplotlib.use("TkAgg")
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

    # The builders are imported after the backend is selected: they own no
    # figure code any more, but importing them first would resolve a backend
    # before ``matplotlib.use("TkAgg")``.
    from library_stats.ui.charts import build_heatmap_figure, build_summary_figure

    HAVE_MPL = True
except ImportError:
    HAVE_MPL = False

logger = logging.getLogger(__name__)

#: The scan modes the run-controls strip offers, in strip order.
INCREMENTAL_SCAN = "Incremental Scan"
FULL_SCAN = "Full Scan"
DIRECT_SCAN = "Direct Scan"
SCAN_MODES = (INCREMENTAL_SCAN, FULL_SCAN, DIRECT_SCAN)

#: The run report's file name, written into the scanned folder.
REPORT_NAME = "library_stats_scan_log.txt"


class LibraryStatsApp(SuiteApp):
    """Library Statistics Dashboard GUI."""

    title = "Library Statistics Dashboard"
    window_key = "library_stats_window"
    program_name = "library_stats"
    guide_name = "Library_Stats_User_Guide.docx"
    completion_text = "Library Scan Complete!"
    tab_labels = (
        " 1. Setup ",
        " 2. Processing ",
        " 3. Results ",
        " 4. Summary ",
        " 5. Charts ",
        " 6. Missing Data ",
        " 7. Completeness ",
        " 8. Artwork Gaps ",
    )

    def __init__(
        self,
        root: tk.Tk,
        *,
        directory: str = "",
        incremental: bool = False,
        refresh: bool = False,
        export_csv: str = "",
        export_json: str = "",
    ) -> None:
        self.folder_path = tk.StringVar(value=suite_config.load_last_directory())
        self.run_mode = tk.StringVar(value=INCREMENTAL_SCAN)
        self._use_cache = tk.BooleanVar(value=True)
        self._refresh_cache = tk.BooleanVar(value=False)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self.run_mode.trace_add("write", self._on_mode_changed)

        self._report: StatsReport | None = None
        self._completeness_report: CompletenessReport | None = None
        self._artwork_gaps: tuple[AlbumArtworkGap, ...] = ()
        self._artwork_log_path = ""
        self._cover_running = False
        self._scanning = False
        self._cache: LibraryCache = LibraryCache()
        self._launched_from_driver = was_launched_from_driver()

        self._cli_refresh = False
        self._cli_export_csv = ""
        self._cli_export_json = ""

        self.controls_panel: DriverControlsPanel | None = None
        self._events: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._poll_id: str = ""
        self._closing = False
        self._run_started = 0.0
        self._run_source = ""
        self._log_entries: list[str] = []

        self._apply_cli_args(
            directory=directory,
            incremental=incremental,
            refresh=refresh,
            export_csv=export_csv,
            export_json=export_json,
        )

        # Build the shared shell (Help bar, notebook, Processing, Results).
        super().__init__(root)
        # Names the pre-migration tests and this class's own code already use.
        self._notebook: ttk.Notebook = self.notebook
        self._status_var: tk.StringVar = self.overall_status
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        if self.folder_path.get():
            if self._refresh_cache.get():
                self.root.after(500, self._start_refresh)
            else:
                self.root.after(500, self._start_scan)

    def _apply_cli_args(
        self,
        *,
        directory: str,
        incremental: bool,
        refresh: bool,
        export_csv: str,
        export_json: str,
    ) -> None:
        """Pre-fill application state from the Master Driver / CLI arguments.

        Must run before the shell builds the tabs so that the auto-scan at the
        end of ``__init__`` sees the correct folder path, scan mode and refresh
        flag.

        Args:
            directory: Music directory from argv[1].
            incremental: Use the cache (``--incremental``).
            refresh: Force a full re-scan (``--refresh``).
            export_csv: Path for CSV export.
            export_json: Path for JSON export.
        """
        if directory:
            self.folder_path.set(directory)
        if refresh:
            self.run_mode.set(FULL_SCAN)
        elif incremental:
            self.run_mode.set(INCREMENTAL_SCAN)
        self._cli_refresh = refresh
        self._cli_export_csv = export_csv
        self._cli_export_json = export_json

    # ── Shell wiring ──────────────────────────────────────────────────────────

    def _tab_specs(self) -> tuple[tuple[str, Any], ...]:
        """Build Setup, the shell's two tabs, then the dashboard's own five."""
        return (
            (self.tab_labels[0], self._build_setup_tab),
            (self.tab_labels[1], self._build_processing_tab),
            (self.tab_labels[2], self._build_results_tab),
            (self.tab_labels[3], self._build_summary_tab),
            (self.tab_labels[4], self._build_charts_tab),
            (self.tab_labels[5], self._build_missing_tab),
            (self.tab_labels[6], self._build_completeness_tab),
            (self.tab_labels[7], self._build_artwork_tab),
        )

    def _on_mode_changed(self, *_args: str) -> None:
        """Derive the cache flags from the strip's Mode (the only control)."""
        mode = self.run_mode.get()
        self._use_cache.set(mode != DIRECT_SCAN)
        self._refresh_cache.set(mode == FULL_SCAN)

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder picker, the actions and the export options."""
        frame = tk.Frame(parent, padx=30, pady=20, bg=styles.BG_WHITE)
        frame.pack(expand=True, fill="both")

        tk.Label(
            frame,
            text=self.title,
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=(0, 20))

        panel = DriverControlsPanel(
            frame,
            source_var=self.folder_path,
            mode_var=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse,
            modes=SCAN_MODES,
        )
        panel.pack(fill="x", pady=(0, 15))
        panel.set_driven(self._launched_from_driver)
        self.controls_panel = panel

        actions = tk.Frame(frame, bg=styles.BG_WHITE)
        actions.pack(fill="x", pady=(0, 10))

        self._scan_btn = tk.Button(
            actions,
            text="Scan Library",
            command=self._start_scan,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief="flat",
            padx=10,
        )
        self._scan_btn.pack(side=tk.LEFT, padx=(0, 5))

        # Kept as a one-click shortcut for the Full Scan mode; it is the same
        # decision, so it routes through the mode rather than a second flag.
        self._refresh_btn = tk.Button(
            actions,
            text="Refresh",
            command=self._start_refresh,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief="flat",
            padx=10,
        )
        self._refresh_btn.pack(side=tk.LEFT, padx=(0, 5))

        self._export_btn = tk.Button(
            actions,
            text="Export",
            command=self._export,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            disabledforeground=styles.FG_ON_ACCENT_LOCKED,
            relief="flat",
            padx=10,
            state="disabled",
        )
        self._export_btn.pack(side=tk.LEFT, padx=(5, 0))

        # Camelot column for the CSV/HTML exports (functional backlog F-06).
        # An export is a file the user keeps, so the choice is a widget rather
        # than a silent default: the column only appears when ticked.
        self._camelot_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            actions,
            text="Camelot column",
            variable=self._camelot_var,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            activebackground=styles.BG_WHITE,
            selectcolor=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=(10, 0))

        tk.Label(
            frame,
            text=(
                "Read-only: the scan reads existing tags and writes no audio or "
                "tag data. Each scan writes its report beside the scanned folder."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=760,
            justify=tk.LEFT,
        ).pack(anchor="w", pady=(10, 0))

    # ── Summary tab ──────────────────────────────────────────────────────────

    def _build_summary_tab(self, parent: tk.Frame) -> None:
        sf = self._summary_frame = parent
        sf.grid_columnconfigure(0, weight=1, uniform="col")
        sf.grid_columnconfigure(1, weight=1, uniform="col")
        sf.grid_columnconfigure(2, weight=3, uniform="col")

        self._summary_labels: dict[str, tk.Label] = {}

        row = 0
        fields = [
            ("Total Files", "total_files"),
            ("Total Albums", "total_albums"),
            ("Total Album Artists", "total_artists"),
            ("Total Artists", "total_track_artists"),
            ("Scan Duration", "duration_str"),
        ]
        for label, key in fields:
            self._make_stat_card(sf, row, 0, label, key)
            row += 1

        # Format breakdown
        fmt_frame = tk.LabelFrame(
            sf,
            text="Format Breakdown",
            font=styles.FONT_LABEL_B,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            padx=10,
            pady=5,
        )
        fmt_frame.grid(row=0, column=1, rowspan=2, sticky="nsew", padx=5, pady=2)
        self._fmt_text = tk.Text(
            fmt_frame,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            height=6,
            width=28,
            relief="flat",
        )
        self._fmt_text.pack(fill="both", expand=True)

        # Key mode breakdown
        km_frame = tk.LabelFrame(
            sf,
            text="Key Mode Split",
            font=styles.FONT_LABEL_B,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            padx=10,
            pady=5,
        )
        km_frame.grid(row=2, column=1, rowspan=2, sticky="nsew", padx=5, pady=2)
        self._km_text = tk.Text(
            km_frame,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            height=6,
            width=28,
            relief="flat",
        )
        self._km_text.pack(fill="both", expand=True)

        # Top Artists
        art_frame = tk.LabelFrame(
            sf,
            text="Top Artists",
            font=styles.FONT_LABEL_B,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            padx=10,
            pady=5,
        )
        art_frame.grid(row=0, column=2, rowspan=4, sticky="nsew", padx=5, pady=2)
        self._art_text = tk.Text(
            art_frame,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            height=16,
            width=50,
            relief="flat",
        )
        self._art_text.pack(fill="both", expand=True)
        art_scroll = tk.Scrollbar(art_frame, command=self._art_text.yview)
        art_scroll.pack(side="right", fill="y")
        self._art_text.configure(yscrollcommand=art_scroll.set)

    def _make_stat_card(
        self, parent: tk.Frame, row: int, col: int, label: str, key: str
    ) -> None:
        card = tk.Frame(
            parent, bg=styles.BG_LIGHT, padx=10, pady=8, relief="ridge", bd=1
        )
        card.grid(row=row, column=col, sticky="nsew", padx=5, pady=2)
        tk.Label(
            card,
            text=label,
            font=styles.FONT_CAPTION,
            bg=styles.BG_LIGHT,
            fg=styles.FG_SUB,
        ).pack(anchor="w")
        lbl = tk.Label(
            card,
            text="\u2014",
            font=("Segoe UI", 22, "bold"),
            bg=styles.BG_LIGHT,
            fg=styles.get_main(),
            anchor="w",
        )
        lbl.pack(fill="x")
        self._summary_labels[key] = lbl

    # ── Charts tab ───────────────────────────────────────────────────────────

    def _build_charts_tab(self, parent: tk.Frame) -> None:
        self._charts_frame = parent
        self._chart_canvas: FigureCanvasTkAgg | None = None
        if not HAVE_MPL:
            tk.Label(
                parent,
                text=(
                    "matplotlib not installed.\nInstall with: pip install matplotlib"
                ),
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_SUB,
            ).pack(expand=True)

    # ── Missing data tab ────────────────────────────────────────────────────

    def _build_missing_tab(self, parent: tk.Frame) -> None:
        mf = self._missing_frame = parent
        tk.Label(
            mf,
            text="Files Missing Tags",
            font=styles.FONT_TITLE,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
        ).pack(pady=10)

        self._missing_text = tk.Text(
            mf,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            height=20,
            relief="flat",
        )
        self._missing_text.pack(fill="both", expand=True, padx=20, pady=5)
        m_scroll = tk.Scrollbar(mf, command=self._missing_text.yview)
        m_scroll.pack(side="right", fill="y")
        self._missing_text.configure(yscrollcommand=m_scroll.set)

    # ── Completeness tab ────────────────────────────────────────────────────

    def _build_completeness_tab(self, parent: tk.Frame) -> None:
        cf = self._completeness_frame = parent

        header = tk.Frame(cf, bg=styles.BG_WHITE)
        header.pack(fill="x", padx=20, pady=(10, 0))
        tk.Label(
            header,
            text="Tag Completeness",
            font=styles.FONT_TITLE,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
        ).pack(side=tk.LEFT)
        self._comp_csv_btn = tk.Button(
            header,
            text="Save CSV",
            command=self._export_completeness_csv,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            disabledforeground=styles.FG_ON_ACCENT_LOCKED,
            relief="flat",
            padx=8,
            state="disabled",
        )
        self._comp_csv_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self._comp_json_btn = tk.Button(
            header,
            text="Save JSON",
            command=self._export_completeness_json,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            disabledforeground=styles.FG_ON_ACCENT_LOCKED,
            relief="flat",
            padx=8,
            state="disabled",
        )
        self._comp_json_btn.pack(side=tk.RIGHT)

        self._comp_overall_var = tk.StringVar(value="")
        tk.Label(
            header,
            textvariable=self._comp_overall_var,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
        ).pack(side=tk.RIGHT, padx=(0, 16))

        self._comp_canvas_frame = tk.Frame(cf, bg=styles.BG_WHITE)
        self._comp_canvas_frame.pack(fill="x", padx=20, pady=(12, 6))

        # Missing-tags-by-album heatmap (PLAN D38: inside this tab, not a new
        # one — the four-tab layout is a locked contract).
        self._comp_heatmap_frame = tk.Frame(cf, bg=styles.BG_WHITE)
        self._comp_heatmap_frame.pack(fill="x", padx=20, pady=(0, 6))
        self._comp_heatmap_canvas: FigureCanvasTkAgg | None = None

        self._comp_missing_text = tk.Text(
            cf,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            height=12,
            relief="flat",
        )
        self._comp_missing_text.pack(fill="both", expand=True, padx=20, pady=(0, 10))
        comp_scroll = tk.Scrollbar(cf, command=self._comp_missing_text.yview)
        comp_scroll.pack(side="right", fill="y")
        self._comp_missing_text.configure(yscrollcommand=comp_scroll.set)

    def _export_completeness_csv(self) -> None:
        report = self._completeness_report
        if report is None or report.total_files == 0:
            messagebox.showwarning("No Data", "Scan a library first before exporting.")
            return
        path = filedialog.asksaveasfilename(
            initialdir=suite_config.load_last_directory(),
            title="Export Completeness CSV",
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv")],
        )
        if not path:
            return
        try:
            export_completeness_csv(report, path)
            self._status_var.set(f"Exported to {os.path.basename(path)}")
        except (OSError, ValueError) as exc:
            show_error_from_exception(exc, title="Export Error")

    def _export_completeness_json(self) -> None:
        report = self._completeness_report
        if report is None or report.total_files == 0:
            messagebox.showwarning("No Data", "Scan a library first before exporting.")
            return
        path = filedialog.asksaveasfilename(
            initialdir=suite_config.load_last_directory(),
            title="Export Completeness JSON",
            defaultextension=".json",
            filetypes=[("JSON files", "*.json")],
        )
        if not path:
            return
        try:
            export_completeness_json(report, path)
            self._status_var.set(f"Exported to {os.path.basename(path)}")
        except (OSError, ValueError) as exc:
            show_error_from_exception(exc, title="Export Error")

    # ── Artwork gaps tab ────────────────────────────────────────────────────

    def _build_artwork_tab(self, parent: tk.Frame) -> None:
        """Build the album artwork list and its cover-extraction actions."""
        af = self._artwork_frame = parent
        header = tk.Frame(af, bg=styles.BG_WHITE)
        header.pack(fill="x", padx=20, pady=(10, 0))
        tk.Label(
            header,
            text="Albums Missing Artwork",
            font=styles.FONT_TITLE,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
        ).pack(side=tk.LEFT)

        # A distinct label: the shell's header View Log opens the scan report,
        # and this one opens the cover pass's own report (D-27).
        self._art_view_log_btn = tk.Button(
            header,
            text="View Artwork Log",
            command=self._open_artwork_log,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            disabledforeground=styles.FG_ON_ACCENT_LOCKED,
            relief="flat",
            padx=8,
            state="disabled",
        )
        self._art_view_log_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self._art_dry_btn = tk.Button(
            header,
            text="Dry Run",
            command=lambda: self._start_cover_extraction(dry_run=True),
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            disabledforeground=styles.FG_ON_ACCENT_LOCKED,
            relief="flat",
            padx=8,
            state="disabled",
        )
        self._art_dry_btn.pack(side=tk.RIGHT, padx=(5, 0))
        self._art_extract_btn = tk.Button(
            header,
            text="Extract Covers",
            command=lambda: self._start_cover_extraction(dry_run=False),
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            disabledforeground=styles.FG_ON_ACCENT_LOCKED,
            relief="flat",
            padx=8,
            state="disabled",
        )
        self._art_extract_btn.pack(side=tk.RIGHT)

        self._art_status_var = tk.StringVar(
            value="Scan a library to list the albums that need a cover."
        )
        tk.Label(
            af,
            textvariable=self._art_status_var,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            anchor="w",
        ).pack(fill="x", padx=20, pady=(6, 0))

        self._art_album_list = tk.Listbox(
            af,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            height=9,
            relief="flat",
            activestyle="none",
        )
        self._art_album_list.pack(fill="both", expand=True, padx=20, pady=(8, 4))
        list_scroll = tk.Scrollbar(af, command=self._art_album_list.yview)
        list_scroll.pack(side="right", fill="y")
        self._art_album_list.configure(yscrollcommand=list_scroll.set)

        self._art_result_text = tk.Text(
            af,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            height=9,
            relief="flat",
        )
        self._art_result_text.pack(fill="both", expand=True, padx=20, pady=(0, 10))

    def _update_artwork_gaps(self, completeness: CompletenessReport) -> None:
        """List the albums missing artwork and enable the cover actions."""
        self._art_album_list.delete(0, tk.END)
        self._art_result_text.delete("1.0", tk.END)
        self._artwork_log_path = ""
        self._art_view_log_btn.config(state="disabled")

        gaps = missing_artwork_albums(completeness)
        self._artwork_gaps = gaps
        for gap in gaps:
            self._art_album_list.insert(
                tk.END,
                f"  {gap.album:<40} {gap.missing_files:>4} of "
                f"{gap.total_files:>4} files without art",
            )

        state: Literal["normal", "disabled"] = (
            "normal" if gaps and not self._cover_running else "disabled"
        )
        self._art_extract_btn.config(state=state)
        self._art_dry_btn.config(state=state)
        if gaps:
            self._art_status_var.set(
                f"{len(gaps)} album(s) have files with no embedded artwork. "
                "A cover is taken from a file that does have one."
            )
        elif completeness.total_files:
            self._art_status_var.set("Every file carries embedded artwork.")
        else:
            self._art_status_var.set(
                "Scan a library to list the albums that need a cover."
            )

    def _start_cover_extraction(self, *, dry_run: bool) -> None:
        """Run the cover pass off the Tk thread, one sidecar per album folder."""
        if self._cover_running:
            return
        if not self._artwork_gaps:
            messagebox.showinfo(
                "No Missing Artwork", "No albums are missing embedded artwork."
            )
            return

        self._cover_running = True
        self._art_extract_btn.config(state="disabled")
        self._art_dry_btn.config(state="disabled")
        self._art_result_text.delete("1.0", tk.END)
        self._art_status_var.set(
            "Dry run: reporting the covers that would be written..."
            if dry_run
            else "Extracting covers from each album's own files..."
        )
        source = self.folder_path.get().strip()
        self._thread = threading.Thread(
            target=self._cover_thread,
            args=(self._artwork_gaps, source, dry_run),
            daemon=True,
        )
        self._thread.start()
        self._start_polling()

    def _cover_thread(
        self,
        gaps: tuple[AlbumArtworkGap, ...],
        source: str,
        dry_run: bool,
    ) -> None:
        """Write the covers off the Tk thread; never touch a widget here."""
        try:
            run = run_cover_extraction(gaps, source=source, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 - reported to the user, never lost
            self._events.put(("covers_error", exc))
        else:
            self._events.put(("covers", run))

    def _on_covers_complete(self, run: CoverRun) -> None:
        """Render a finished cover pass and expose its own run report."""
        self._cover_running = False
        state: Literal["normal", "disabled"] = (
            "normal" if self._artwork_gaps else "disabled"
        )
        self._art_extract_btn.config(state=state)
        self._art_dry_btn.config(state=state)
        self._art_result_text.delete("1.0", tk.END)
        for result in run.results:
            detail = f" -> {result.sidecar}" if result.sidecar else ""
            if result.detail:
                detail = (
                    f"{detail} | {result.detail}" if detail else f" | {result.detail}"
                )
            self._art_result_text.insert(
                "end",
                f"  {result.album:<30} {result.status.upper():<10} "
                f"{result.folder}{detail}\n",
            )
        self._artwork_log_path = run.report_path
        log_state: Literal["normal", "disabled"] = (
            "normal" if run.report_path else "disabled"
        )
        self._art_view_log_btn.config(state=log_state)
        self._art_status_var.set(
            f"{'Dry run' if run.dry_run else 'Covers'}: {run.extracted} written, "
            f"{run.kept} kept, {run.no_art} with no artwork, "
            f"{run.errors} error(s) in {run.elapsed:.1f}s."
        )
        self._status_var.set("Artwork pass complete.")

    def _on_covers_error(self, exc: Exception) -> None:
        """Report a failed cover pass without leaving the buttons locked."""
        self._cover_running = False
        state: Literal["normal", "disabled"] = (
            "normal" if self._artwork_gaps else "disabled"
        )
        self._art_extract_btn.config(state=state)
        self._art_dry_btn.config(state=state)
        self._art_status_var.set("The artwork pass failed. See the error dialog.")
        show_error_from_exception(exc, title="Artwork Error")

    def _open_artwork_log(self) -> None:
        """Open this view's own run report."""
        if not self._artwork_log_path:
            messagebox.showinfo("No Log", "Run the cover pass first.")
            return
        open_path(self._artwork_log_path)

    # ── Actions ──────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.folder_path.get() or "")
        if folder:
            self.folder_path.set(folder)
            suite_config.save_last_directory(folder)

    def _start_scan(self, refresh: bool = False) -> None:
        path = self.folder_path.get().strip()
        if not path or not os.path.isdir(path):
            messagebox.showwarning(
                "Invalid Folder", "Please select a valid music folder."
            )
            return

        if self._scanning:
            return
        if refresh and self.run_mode.get() != FULL_SCAN:
            self.run_mode.set(FULL_SCAN)
        self._scanning = True
        self._scan_btn.config(state="disabled", text="Scanning...")
        self._refresh_btn.config(state="disabled")
        self._export_btn.config(state="disabled")
        self._begin_run(path)
        self._status_var.set(f"Scanning... ({self.run_mode.get().lower()})")
        self.progress["mode"] = "indeterminate"
        self.progress.start(12)
        self._report = None

        self._thread = threading.Thread(
            target=self._scan_thread, args=(path, refresh), daemon=True
        )
        self._thread.start()
        self._start_polling()

    def _start_refresh(self) -> None:
        """Force a full re-scan that ignores the cache."""
        path = self.folder_path.get().strip()
        if not path or not os.path.isdir(path):
            messagebox.showwarning(
                "Invalid Folder", "Please select a valid music folder."
            )
            return
        self._start_scan(refresh=True)

    def _scan_thread(self, path: str, refresh: bool) -> None:
        """Run the scan off the Tk thread; never touch a widget here."""
        try:
            report = scan_directory(
                path,
                use_cache=self._use_cache.get(),
                refresh_cache=refresh,
                cache=self._cache,
            )
            completeness = analyse_completeness(path)
            # Record the trend point before the UI update, but never let a cache
            # problem fail a scan that already produced a valid report.
            try:
                self._cache.record_completeness_snapshot(completeness)
            except sqlite3.Error:
                logger.warning(
                    "Could not record the completeness snapshot", exc_info=True
                )
            self._events.put(("done", (report, completeness)))
        except Exception as exc:  # noqa: BLE001 - reported to the user, never lost
            self._events.put(("error", exc))

    def _start_polling(self) -> None:
        """Begin draining the worker's queue on the Tk thread."""
        self._poll_events()

    def _poll_events(self) -> None:
        """Apply every queued worker result, then re-arm while it still runs."""
        self._poll_id = ""
        if self._closing:
            return
        while True:
            try:
                kind, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "done":
                report, completeness = payload
                self._on_scan_complete(report, completeness)
            elif kind == "covers":
                self._on_covers_complete(payload)
            elif kind == "covers_error":
                self._on_covers_error(payload)
            else:
                self._on_scan_error(payload)
        if self._thread is not None and self._thread.is_alive():
            self._poll_id = self.root.after(100, self._poll_events)

    def _on_scan_complete(
        self, report: StatsReport, completeness: CompletenessReport
    ) -> None:
        self._report = report
        self._completeness_report = completeness
        self._scanning = False
        self.progress.stop()
        self.progress["mode"] = "determinate"
        self.progress["value"] = 1
        self.progress["maximum"] = 1
        self._scan_btn.config(state="normal", text="Scan Library")
        self._refresh_btn.config(state="normal")
        self._export_btn.config(state="normal")
        self._comp_csv_btn.config(state="normal")
        self._comp_json_btn.config(state="normal")
        cached_count = self._cache.row_count(self.folder_path.get().strip())
        cache_info = (
            f" | {cached_count} cached"
            if self._use_cache.get() and cached_count
            else ""
        )
        self._status_var.set(
            f"Scanned {report.total_files} files in "
            f"{report.duration_secs:.1f}s{cache_info}."
        )
        scanned_in = report.scan_path or self.folder_path.get()
        self.file_listbox.insert(
            tk.END, f"{report.total_files} files scanned in {scanned_in}"
        )
        self.file_listbox.see(tk.END)
        self.stats_label.config(
            text=(
                f"Files: {report.total_files} | Albums: {report.total_albums}"
                f" | Artists: {report.total_artists}"
            )
        )
        self._update_summary(report)
        self._update_missing(report)
        self._collect_log_entries(report)
        try:
            history = self._cache.completeness_history(
                self.folder_path.get().strip(), limit=12
            )
        except sqlite3.Error:
            history = []
        self._update_charts(report, history)
        self._update_completeness(completeness)
        self._update_artwork_gaps(completeness)
        self._apply_cli_exports(report)
        self._write_run_log()
        self.render_completion(
            duration_secs=report.duration_secs,
            output_dir=report.scan_path or self.folder_path.get().strip(),
        )
        self.summary_label.config(
            text=(
                f"Total: {report.total_files} files\n"
                f"Albums: {report.total_albums}\n"
                f"Artists: {report.total_artists}"
            )
        )
        if self.auto_end_var.get():
            self.root.after(1500, self.root.destroy)

    def _on_scan_error(self, exc: Exception) -> None:
        self._scanning = False
        self.progress.stop()
        self.progress["mode"] = "determinate"
        self._scan_btn.config(state="normal", text="Scan Library")
        self._refresh_btn.config(state="normal")
        self._status_var.set("Scan failed. See error dialog for details.")
        show_error_from_exception(exc, title="Scan Error")

    def _apply_cli_exports(self, report: StatsReport) -> None:
        """Auto-export to CSV/JSON if CLI flags requested it.

        Args:
            report: The completed statistics report.
        """
        if self._cli_export_csv:
            try:
                export_csv(report, self._cli_export_csv)
                self._status_var.set(
                    f"Exported CSV to {os.path.basename(self._cli_export_csv)}"
                )
            except (AudioSuiteError, OSError, ValueError) as exc:
                show_error_from_exception(exc, title="Export Error")
        if self._cli_export_json:
            try:
                export_json(report, self._cli_export_json)
                self._status_var.set(
                    f"Exported JSON to {os.path.basename(self._cli_export_json)}"
                )
            except (AudioSuiteError, OSError, ValueError) as exc:
                show_error_from_exception(exc, title="Export Error")

    def _export(self) -> None:
        report = self._report
        if report is None or report.total_files == 0:
            messagebox.showwarning("No Data", "Scan a library first before exporting.")
            return

        filetypes = [
            ("CSV files", "*.csv"),
            ("JSON files", "*.json"),
            ("M3U playlist", "*.m3u"),
            ("HTML report", "*.html"),
        ]
        path = filedialog.asksaveasfilename(
            initialdir=suite_config.load_last_directory(),
            title="Export Metadata",
            defaultextension=".csv",
            filetypes=filetypes,
        )
        if not path:
            return

        camelot = self._camelot_var.get()
        try:
            lower = path.lower()
            if lower.endswith(".json"):
                export_json(report, path)
            elif lower.endswith((".m3u", ".m3u8")):
                export_m3u(report.scan_path, path)
            elif lower.endswith((".html", ".htm")):
                export_html(report.scan_path, path, camelot=camelot)
            else:
                export_csv(report, path, camelot=camelot)
            self._status_var.set(f"Exported to {os.path.basename(path)}")
        except (AudioSuiteError, OSError, ValueError) as exc:
            show_error_from_exception(exc, title="Export Error")

    # ── Run report ───────────────────────────────────────────────────────────

    def _begin_run(self, source: str) -> None:
        """Name this run's report, in the folder it is about to scan."""
        self._log_entries = []
        self._run_source = source
        self._log_path = os.path.join(source, REPORT_NAME) if source else ""
        self._run_started = time.monotonic()

    def _collect_log_entries(self, report: StatsReport) -> None:
        """Record the scan's detail for the report's body."""
        entries = ["Formats:\n"]
        entries.extend(
            f"  {ext:>8}  {count}\n"
            for ext, count in sorted(report.format_breakdown.items())
        )
        entries.append("\nMissing tags:\n")
        total = report.total_files or 1
        for label, key in (
            ("BPM", "no_bpm"),
            ("Key", "no_key"),
            ("Genre", "no_genre"),
            ("Mood", "no_mood"),
            ("Tempo Marking", "no_tempo_marking"),
            # Changed in 2.6.0: artwork coverage rides the same report (F-E10).
            ("Artwork", "no_art"),
        ):
            count = report.missing_data.get(key, 0)
            entries.append(f"  {label:<15} {count:>6}  ({count / total * 100:5.1f}%)\n")
        self._log_entries = entries

    def _write_run_log(self) -> None:
        """Serialise this run's report; a failed write is logged, never raised."""
        if not self._log_path:
            return
        report = self._report
        elapsed = time.monotonic() - self._run_started
        mode = self.run_mode.get().upper()
        header = [
            "LIBRARY STATISTICS REPORT\n",
            f"Mode: {mode}\n",
            f"Source: {self._run_source}\n",
            f"Cache: {'enabled' if self._use_cache.get() else 'disabled'}\n",
            f"Refresh: {'yes' if self._refresh_cache.get() else 'no'}\n",
            "Scanner: read-only (no audio analysis, no tag writes)\n",
            "=" * 60 + "\n",
        ]
        summary = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {report.total_files if report else 0}\n",
            f"Albums: {report.total_albums if report else 0}\n",
            f"Album artists: {report.total_artists if report else 0}\n",
            f"Track artists: {report.total_track_artists if report else 0}\n",
            f"Scan time: {report.duration_secs if report else 0.0:.1f}s\n",
            f"Time: {int(elapsed // 60):02d}:{int(elapsed % 60):02d}\n",
        ]
        try:
            with open(self._log_path, "w", encoding="utf-8") as handle:
                handle.writelines(header + self._log_entries + summary)
        except OSError as exc:
            logger.error("Could not write the run report: %s", exc, exc_info=True)

    # ── UI updates ───────────────────────────────────────────────────────────

    def _update_summary(self, r: StatsReport) -> None:
        self._summary_labels["total_files"].config(text=str(r.total_files))
        self._summary_labels["total_albums"].config(text=str(r.total_albums))
        self._summary_labels["total_artists"].config(text=str(r.total_artists))
        self._summary_labels["total_track_artists"].config(
            text=str(r.total_track_artists)
        )
        self._summary_labels["duration_str"].config(text=f"{r.duration_secs:.1f}s")

        # Format breakdown
        self._fmt_text.delete("1.0", "end")
        for ext, count in r.format_breakdown.items():
            self._fmt_text.insert("end", f"{ext:>8}  {count}\n")

        # Key mode split
        self._km_text.delete("1.0", "end")
        major = r.key_mode_distribution.get("major", 0)
        minor = r.key_mode_distribution.get("minor", 0)
        total = major + minor
        if total:
            self._km_text.insert(
                "end", f"  Major  {major:>5}  ({major / total * 100:.0f}%)\n"
            )
            self._km_text.insert(
                "end", f"  Minor  {minor:>5}  ({minor / total * 100:.0f}%)\n"
            )

        # Top artists
        self._art_text.delete("1.0", "end")
        for artist, count in r.top_artists[:30]:
            a = artist[:40] + ".." if len(artist) > 40 else artist
            self._art_text.insert("end", f"  {a:<42} {count:>4}\n")

    def _update_missing(self, r: StatsReport) -> None:
        self._missing_text.delete("1.0", "end")
        total = r.total_files or 1
        labels = [
            ("Missing BPM", "no_bpm"),
            ("Missing Key", "no_key"),
            ("Missing Genre", "no_genre"),
            ("Missing Mood", "no_mood"),
            ("Missing Tempo Marking", "no_tempo_marking"),
            # Changed in 2.6.0: artwork coverage (F-E10).
            ("Missing Artwork", "no_art"),
        ]
        for label, key in labels:
            count = r.missing_data.get(key, 0)
            pct = count / total * 100
            bar = "\u2588" * int(pct / 2) if pct > 0 else ""
            self._missing_text.insert(
                "end", f"  {label:<25} {count:>6}  ({pct:5.1f}%)  {bar}\n"
            )

    def _update_charts(
        self,
        r: StatsReport,
        history: list[dict[str, Any]] | None = None,
    ) -> None:
        """Render the Charts tab (four distributions, artwork and the trend).

        Args:
            r: The completed statistics report.
            history: Completeness snapshots, oldest first, for the trend
                panel.  Empty/None draws the "no history yet" panel.
        """
        if not HAVE_MPL:
            return

        # Clear previous chart
        for w in self._charts_frame.winfo_children():
            w.destroy()

        fig = build_summary_figure(r, history)

        canvas = FigureCanvasTkAgg(fig, master=self._charts_frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._chart_canvas = canvas

    # ── Completeness rendering ───────────────────────────────────────────────

    @staticmethod
    def _colour_for_pct(pct: float) -> str:
        """Return the bar colour for a completeness percentage.

        Green above 80 %, amber 50–80 %, red below 50 %.
        """
        if pct > 80.0:
            return "#22c55e"
        if pct >= 50.0:
            return "#f59e0b"
        return "#ef4444"

    def _update_completeness(self, r: CompletenessReport) -> None:
        for w in self._comp_canvas_frame.winfo_children():
            w.destroy()
        self._comp_missing_text.delete("1.0", "end")

        if r.total_files == 0:
            self._comp_missing_text.insert(
                "end", "  No audio files found in " + r.directory + "\n"
            )
            self._comp_overall_var.set("")
            return

        self._comp_overall_var.set(f"Overall: {r.overall_pct:.0f}% complete")

        order = sorted(
            r.tag_results.values(), key=lambda tc: (tc.pct_complete, tc.field)
        )

        self._comp_canvas_frame.grid_columnconfigure(0, minsize=130)
        self._comp_canvas_frame.grid_columnconfigure(1, weight=1, minsize=300)
        self._comp_canvas_frame.grid_columnconfigure(2, minsize=70)

        tk.Label(
            self._comp_canvas_frame,
            text="Tag",
            font=styles.FONT_LABEL_B,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(0, 8))
        tk.Label(
            self._comp_canvas_frame,
            text="Complete (% of files)",
            font=styles.FONT_LABEL_B,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            anchor="w",
        ).grid(row=0, column=1, sticky="w")
        tk.Label(
            self._comp_canvas_frame,
            text="%",
            font=styles.FONT_LABEL_B,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            anchor="e",
        ).grid(row=0, column=2, sticky="e")

        for i, tc in enumerate(order):
            row = i + 1
            tk.Label(
                self._comp_canvas_frame,
                text=tc.label,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                anchor="w",
                width=16,
            ).grid(row=row, column=0, sticky="w", padx=(0, 8), pady=2)

            canvas = tk.Canvas(
                self._comp_canvas_frame,
                height=20,
                bg="#fee2e2",
                highlightthickness=1,
                highlightbackground="#e5e7eb",
            )
            canvas.grid(row=row, column=1, sticky="ew", pady=2)

            def _on_resize(
                _event: object, c: tk.Canvas = canvas, t: TagCompleteness = tc
            ) -> None:
                self._draw_bar(c, t)

            canvas.bind("<Configure>", _on_resize)

            tk.Label(
                self._comp_canvas_frame,
                text=f"{tc.pct_complete:.0f}%",
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                anchor="e",
            ).grid(row=row, column=2, sticky="e", pady=2)

            if tc.missing:
                self._comp_missing_text.insert(
                    "end", f"  {tc.label:<15} missing {tc.missing:>6} files\n"
                )
                for path in tc.missing_files:
                    self._comp_missing_text.insert("end", f"      {path}\n")
            else:
                self._comp_missing_text.insert(
                    "end", f"  {tc.label:<15} no missing files\n"
                )

        self._render_heatmap(r)

    def _render_heatmap(self, r: CompletenessReport) -> None:
        """Embed the missing-tags-by-album heatmap under the tag bars."""
        frame = self._comp_heatmap_frame
        for w in frame.winfo_children():
            w.destroy()
        self._comp_heatmap_canvas = None
        if not HAVE_MPL:
            return
        fig = build_heatmap_figure(r)
        canvas = FigureCanvasTkAgg(fig, master=frame)
        canvas.draw()
        canvas.get_tk_widget().pack(fill="both", expand=True)
        self._comp_heatmap_canvas = canvas

    def _draw_bar(self, canvas: tk.Canvas, tc: TagCompleteness) -> None:
        width = canvas.winfo_width()
        if width <= 1:  # not yet mapped — defer until a real size is known
            return
        canvas.delete("all")
        fill = max(5.0, width * tc.pct_complete / 100.0)
        canvas.create_rectangle(
            0,
            2,
            fill,
            canvas.winfo_height() - 2,
            fill=self._colour_for_pct(tc.pct_complete),
            outline="",
        )

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        """Stop the poller and the worker, then close the window."""
        self._closing = True
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = ""
        self.root.destroy()


def main() -> None:
    """Main entry point for the Library Statistics Dashboard.

    Parses the Master-Driver / CLI argv when no explicit directory is
    supplied, pre-fills the GUI, and enters the mainloop.
    """
    from audio_suite_shared.styles import bootstrap_theme

    args = parse_cli_args(cli_args.parse)
    root = tk.Tk()
    bootstrap_theme()
    LibraryStatsApp(
        root,
        directory=args.folder_path,
        incremental=args.incremental,
        refresh=args.refresh,
        export_csv=args.export_csv,
        export_json=args.export_json,
    )
    root.mainloop()
