"""
cd_ripper/app.py — Main application window for CD Ripper.
Palette-aware, matches Music Format Converter style.

Changed in 1.0.1: parses the driver's argv and pre-fills the rip output, format, tracks
and cue settings.

Changed in 1.2.0: wires the Results tab's manual "Re-rip flagged tracks" action
to a re-rip of exactly those tracks (PLAN_feature_expansion.md D30).
Changed in 1.2.0: records what the disc's rip still owes the user (tracks that
did not rip, including the ones verification rejected) as the run's note, so a
Master Driver batch reports it on the CD Ripper step.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any

from audio_suite_shared import styles
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.run_outcome import record_caveats, shortfall
from audio_suite_shared.ui_helpers import UIHelperMixin
from cd_ripper.ui.results_tab import ResultsTab
from cd_ripper.ui.rip_tab import RipTab
from cd_ripper.ui.setup_tab import SetupTab
from cd_ripper.utils import cli_args

#: Manifest id the Master Driver keys this tool's batch step by.  It is not
#: derivable from the window title, and a note recorded under any other key is
#: never read; ``tests/test_run_outcome_contract.py`` locks it to the manifest.
DRIVER_TOOL_ID = "cd_ripper"


class CDRipperApp(UIHelperMixin):
    """CD Ripper application GUI."""

    HELP_GUIDE = "CD_Ripper_User_Guide.docx"

    def __init__(
        self,
        root: tk.Tk,
        *,
        output_dir: str = "",
        format: str = "",
        tracks: str = "",
        cue: bool = False,
    ) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "CD Ripper",
            "cd_ripper_window",
            "cd_ripper",
            width=860,
            height=950,
            apply_ttk_styles=False,
        )
        self.root.minsize(860, 950)
        self._apply_styles()
        self._build_ui()
        self._apply_cli_args(
            output_dir=output_dir,
            format=format,
            tracks=tracks,
            cue=cue,
        )

    def _apply_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(
            "Suite.Horizontal.TProgressbar",
            troughcolor="#e0e0e0",
            background=styles.get_main(),
        )
        style.configure("TNotebook", background=styles.BG_LIGHT)
        style.configure(
            "TNotebook.Tab",
            background=styles.get_main(),
            foreground="white",
            padding=[15, 5],
        )
        style.map("TNotebook.Tab", background=[("selected", styles.get_dark())])
        style.configure("Treeview", font=styles.FONT_BODY)
        style.configure("Treeview.Heading", font=styles.FONT_BODY_B)

    def _build_ui(self) -> None:

        # Help button
        help_frame = tk.Frame(self.root, bg=styles.BG_LIGHT)
        help_frame.pack(fill="x", padx=12, pady=(12, 0))
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

        # Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=12, pady=12)

        self.state: dict[str, Any] = {
            "tracks": [],
            "disc_id": None,
            "release_info": None,
            "rip_results": [],
        }

        self.setup_tab = SetupTab(self.notebook, self.state, self._on_ready_to_rip)
        self.rip_tab = RipTab(self.notebook, self.state, self._on_rip_complete)
        self.results_tab = ResultsTab(self.notebook, self.state)
        # The Results tab owns the flagged-row list; the app owns the tab
        # switch, so the callback is handed over rather than the widget.
        self.state["on_rerip"] = self._on_rerip

        self.notebook.add(self.setup_tab.frame, text="  Setup & Lookup  ")
        self.notebook.add(self.rip_tab.frame, text="  Rip  ")
        self.notebook.add(self.results_tab.frame, text="  Results  ")

        self.notebook.tab(1, state="disabled")
        self.notebook.tab(2, state="disabled")

    def _on_ready_to_rip(self) -> None:
        self.notebook.tab(1, state="normal")
        self.notebook.select(1)
        self.rip_tab.prepare()

    def _on_rip_complete(self) -> None:
        self.notebook.tab(2, state="normal")
        self.notebook.select(2)
        self.results_tab.refresh()
        self._record_run_note()

    def _record_run_note(self) -> None:
        """Record what the disc's rip still owes the user, for the batch report.

        A track that failed verification deliberately writes no file, so the
        Results tab shows it per track and the flagged-track re-rip exists for
        it.  This is the one-line version, and it is recorded after *every*
        session -- including a partial re-rip -- so it always describes the
        disc's current results: fixing the last flagged track clears the note.
        """
        results = self.state.get("rip_results", [])
        failed = [entry for entry in results if not entry.get("success")]
        if not failed:
            record_caveats(DRIVER_TOOL_ID)
            return
        record_caveats(
            DRIVER_TOOL_ID,
            shortfall(len(failed), len(results), "track", "did not rip"),
        )

    def _apply_cli_args(
        self,
        *,
        output_dir: str,
        format: str,
        tracks: str,
        cue: bool,
    ) -> None:
        """Pre-fill widgets from the Master Driver / CLI arguments.

        Args:
            output_dir: Output directory from ``--output-dir``.
            format: Lowercase format name from ``--format``.
            tracks: Comma-separated track selection from ``--tracks``.
            cue: Whether to write a CUE sheet (``--cue``).
        """
        self.setup_tab.apply_cli_settings(
            output_dir=output_dir,
            format_label=cli_args.FORMAT_DISPLAY.get(format.strip().lower(), ""),
            cue=cue,
        )
        selection = cli_args.parse_track_selection(tracks)
        if selection:
            self.state["cli_track_filter"] = selection

    def _on_rerip(self, numbers: list[int]) -> None:
        """Re-rip the flagged tracks and show their progress.

        Args:
            numbers: Ascending track numbers that failed and were selected
                for a manual re-rip.
        """
        self.notebook.tab(1, state="normal")
        self.notebook.select(1)
        self.rip_tab.re_rip(numbers)

    def _open_help(self) -> None:
        """Open help file with enhanced error handling."""
        self._open_help_standard(self.HELP_GUIDE)


def main() -> None:
    """Main entry point for the CD Ripper.

    Parses the Master-Driver / CLI argv, pre-fills the GUI, and enters
    the mainloop.
    """
    from audio_suite_shared.styles import bootstrap_theme

    args = parse_cli_args(cli_args.parse)
    root = tk.Tk()
    bootstrap_theme()
    CDRipperApp(
        root,
        output_dir=args.output_dir,
        format=args.format,
        tracks=args.tracks,
        cue=args.cue,
    )
    root.mainloop()
