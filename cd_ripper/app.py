"""
cd_ripper/app.py — Main application window for CD Ripper.
Palette-aware, matches Music Format Converter style.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any

from audio_suite_shared import styles
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.ui_helpers import UIHelperMixin
from cd_ripper.ui.results_tab import ResultsTab
from cd_ripper.ui.rip_tab import RipTab
from cd_ripper.ui.setup_tab import SetupTab


class CDRipperApp(UIHelperMixin):
    """CD Ripper application GUI."""

    HELP_GUIDE = "CD_Ripper_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
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

    def _open_help(self) -> None:
        """Open help file with enhanced error handling."""
        self._open_help_standard(self.HELP_GUIDE)
