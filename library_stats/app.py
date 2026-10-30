"""
app.py — LibraryStatsApp GUI dashboard.

Opens a tkinter window with matplotlib charts showing library statistics
derived from existing audio tags.  All data is read-only — no analysis or
tag writing is performed.

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
"""

from __future__ import annotations

import os
import sqlite3
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from audio_suite_shared import styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.exceptions import AudioSuiteError, handle_audio_errors
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.ui_helpers import UIHelperMixin, show_error_from_exception
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


class LibraryStatsApp(UIHelperMixin):
    """Library Statistics Dashboard GUI."""

    HELP_GUIDE = "Library_Stats_User_Guide.docx"

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
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Library Statistics Dashboard",
            "library_stats_window",
            "library_stats",
            width=1100,
            height=780,
        )

        self.folder_path = tk.StringVar(value=suite_config.load_last_directory())
        self._report: StatsReport | None = None
        self._completeness_report: CompletenessReport | None = None
        self._scanning = False
        self._use_cache = tk.BooleanVar(value=True)
        self._cache: LibraryCache = LibraryCache()

        self._cli_refresh = False
        self._cli_export_csv = ""
        self._cli_export_json = ""

        self._apply_cli_args(
            directory=directory,
            incremental=incremental,
            refresh=refresh,
            export_csv=export_csv,
            export_json=export_json,
        )
        self._build_ui()

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

        Must run before ``_build_ui`` so that the auto-scan at the end of
        ``_build_ui`` sees the correct folder path, cache mode, and refresh
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
        if incremental:
            self._use_cache.set(True)
        self._cli_refresh = refresh
        self._cli_export_csv = export_csv
        self._cli_export_json = export_json

    def _build_ui(self) -> None:
        self.root.title("Library Statistics Dashboard")

        top = tk.Frame(self.root, bg=styles.BG_APP, padx=20, pady=10)
        top.pack(fill="x")

        tk.Label(
            top,
            text="Music Folder:",
            font=styles.FONT_LABEL,
            bg=styles.BG_APP,
            fg=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=(0, 10))

        tk.Entry(
            top,
            textvariable=self.folder_path,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 10))

        tk.Button(
            top,
            text="Browse",
            command=self._browse,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief="flat",
            padx=10,
        ).pack(side=tk.LEFT, padx=(0, 5))

        self._scan_btn = tk.Button(
            top,
            text="Scan Library",
            command=self._start_scan,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief="flat",
            padx=10,
        )
        self._scan_btn.pack(side=tk.LEFT)

        self._cache_cb = tk.Checkbutton(
            top,
            text="Cache",
            variable=self._use_cache,
            font=styles.FONT_CAPTION,
            bg=styles.BG_APP,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
        )
        self._cache_cb.pack(side=tk.LEFT, padx=(5, 0))

        self._refresh_btn = tk.Button(
            top,
            text="Refresh",
            command=self._start_refresh,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief="flat",
            padx=10,
        )
        self._refresh_btn.pack(side=tk.LEFT, padx=(5, 0))

        self._export_btn = tk.Button(
            top,
            text="Export",
            command=self._export,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
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
            top,
            text="Camelot column",
            variable=self._camelot_var,
            font=styles.FONT_CAPTION,
            bg=styles.BG_APP,
            fg=styles.FG_MAIN,
            activebackground=styles.BG_APP,
            selectcolor=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(10, 0))

        # ── Status bar ───────────────────────────────────────────────────────
        self._status_var = tk.StringVar(
            value="Ready. Select a folder and click Scan Library."
        )
        status = tk.Label(
            self.root,
            textvariable=self._status_var,
            font=styles.FONT_CAPTION,
            bg=styles.BG_LIGHT,
            fg=styles.FG_SUB,
            anchor="w",
            padx=20,
            pady=4,
        )
        status.pack(fill="x")

        # ── Notebook for results ─────────────────────────────────────────────
        self._notebook = ttk.Notebook(self.root)
        self._notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        self._summary_frame = tk.Frame(self._notebook, bg=styles.BG_WHITE)
        self._charts_frame = tk.Frame(self._notebook, bg=styles.BG_WHITE)
        self._missing_frame = tk.Frame(self._notebook, bg=styles.BG_WHITE)
        self._completeness_frame = tk.Frame(self._notebook, bg=styles.BG_WHITE)

        self._notebook.add(self._summary_frame, text="Summary")
        self._notebook.add(self._charts_frame, text="Charts")
        self._notebook.add(self._missing_frame, text="Missing Data")
        self._notebook.add(self._completeness_frame, text="Completeness")

        self._build_summary_tab()
        self._build_missing_tab()
        self._build_completeness_tab()

        self._chart_canvas: FigureCanvasTkAgg | None = None

        # Auto-scan if directory already set
        if self.folder_path.get():
            if self._cli_refresh:
                self.root.after(500, self._start_refresh)
            else:
                self.root.after(500, self._start_scan)

    # ── Summary tab ──────────────────────────────────────────────────────────

    def _build_summary_tab(self) -> None:
        sf = self._summary_frame
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

    # ── Missing data tab ────────────────────────────────────────────────────

    def _build_missing_tab(self) -> None:
        mf = self._missing_frame
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

    def _build_completeness_tab(self) -> None:
        cf = self._completeness_frame

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
        self._scanning = True
        self._scan_btn.config(state="disabled", text="Scanning...")
        self._refresh_btn.config(state="disabled")
        self._status_var.set("Scanning..." + (" (full refresh)" if refresh else ""))
        self._report = None

        threading.Thread(
            target=self._do_scan, args=(path, refresh), daemon=True
        ).start()

    def _start_refresh(self) -> None:
        """Force a full re-scan that ignores the cache."""
        path = self.folder_path.get().strip()
        if not path or not os.path.isdir(path):
            messagebox.showwarning(
                "Invalid Folder", "Please select a valid music folder."
            )
            return
        self._start_scan(refresh=True)

    def _do_scan(self, path: str, refresh: bool = False) -> None:
        try:
            self._scan_worker(path, refresh)
        except AudioSuiteError as exc:
            self.root.after(0, self._on_scan_error, exc)

    @handle_audio_errors(reraise=True, context="library_stats_scan")
    def _scan_worker(self, path: str, refresh: bool) -> None:
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
            pass
        self.root.after(0, self._on_scan_complete, report, completeness)

    def _on_scan_complete(
        self, report: StatsReport, completeness: CompletenessReport
    ) -> None:
        self._report = report
        self._completeness_report = completeness
        self._scanning = False
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
        self._update_summary(report)
        self._update_missing(report)
        try:
            history = self._cache.completeness_history(
                self.folder_path.get().strip(), limit=12
            )
        except sqlite3.Error:
            history = []
        self._update_charts(report, history)
        self._update_completeness(completeness)
        self._apply_cli_exports(report)

    def _on_scan_error(self, exc: Exception) -> None:
        self._scanning = False
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
        """Render the Charts tab (four distributions plus the trend).

        Args:
            r: The completed statistics report.
            history: Completeness snapshots, oldest first, for the trend
                panel.  Empty/None draws the "no history yet" panel.
        """
        if not HAVE_MPL:
            lbl = tk.Label(
                self._charts_frame,
                text="matplotlib not installed.\nInstall with: pip install matplotlib",
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_SUB,
            )
            lbl.pack(expand=True)
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
