"""
cd_ripper/ui/format_config_panel.py — Output format/quality configuration.
"""

import os
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any

from audio_suite_shared import styles
from cd_ripper.core.cd_ripper_config import get_output_dir, set_output_dir


class FormatConfigPanel:
    """Output format and directory configuration sub-panel."""

    def __init__(self, parent: tk.Widget) -> None:
        self.frame = tk.Frame(parent, bg=styles.BG_WHITE)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Output folder
        tk.Label(
            self.frame,
            text="Output Directory:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(8, 0))
        out_row = tk.Frame(self.frame, bg=styles.BG_WHITE)
        out_row.pack(fill="x", pady=3)
        self.out_var = tk.StringVar(value=get_output_dir())
        out_entry = tk.Entry(
            out_row,
            textvariable=self.out_var,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        )
        out_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        out_entry.bind("<FocusOut>", self.on_out_dir_changed)
        out_entry.bind("<Return>", self.on_out_dir_changed)
        tk.Button(
            out_row,
            text="Browse",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self.browse_out,
        ).pack(side="right")

        # Format + quality
        fmt_row = tk.Frame(self.frame, bg=styles.BG_WHITE)
        fmt_row.pack(fill="x", pady=(8, 0))
        tk.Label(
            fmt_row,
            text="Output Format:",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side="left")
        self.fmt_var = tk.StringVar(value="FLAC")
        fmt_combo = ttk.Combobox(
            fmt_row,
            textvariable=self.fmt_var,
            values=["FLAC", "MP3", "OGG", "M4A", "WAV", "Opus"],
            font=styles.FONT_BODY,
            state="readonly",
            width=10,
        )
        fmt_combo.pack(side="left", padx=(5, 20))
        fmt_combo.bind("<<ComboboxSelected>>", self.on_fmt_changed)

        tk.Label(
            fmt_row,
            text="Quality:",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side="left")
        self.quality_var = tk.StringVar()
        self.quality_combo = ttk.Combobox(
            fmt_row,
            textvariable=self.quality_var,
            font=styles.FONT_BODY,
            state="readonly",
            width=28,
        )
        self.quality_combo.pack(side="left", padx=(5, 0))
        self.update_quality_combo()

        # Verification mode
        verify_row = tk.Frame(self.frame, bg=styles.BG_WHITE)
        verify_row.pack(fill="x", pady=(8, 0))
        tk.Label(
            verify_row,
            text="Verify Rips:",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side="left")
        self.verify_var = tk.StringVar(value="twice")
        ttk.Combobox(
            verify_row,
            textvariable=self.verify_var,
            values=["twice", "off", "accuraterip"],
            font=styles.FONT_BODY,
            state="readonly",
            width=14,
        ).pack(side="left", padx=(5, 0))
        tk.Label(
            verify_row,
            text=(
                "Twice (re-read, no internet) · AccurateRip (DB cross-check) · "
                "Off (no check)"
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(side="left", padx=(8, 0))

        # CUE sheet option
        self.cue_var = tk.BooleanVar(value=False)
        tk.Checkbutton(
            self.frame,
            text="Write CUE sheet alongside ripped tracks",
            variable=self.cue_var,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            activebackground=styles.BG_WHITE,
            anchor="w",
        ).pack(anchor="w", pady=(8, 0))

    # ── Output / Format ───────────────────────────────────────────────────────

    def on_out_dir_changed(self, _event: Any = None) -> None:
        path = self.out_var.get().strip()
        if path and os.path.isdir(path):
            set_output_dir(path)

    def browse_out(self) -> None:
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            self.out_var.set(folder)
            set_output_dir(folder)

    def on_fmt_changed(self, _event: Any = None) -> None:
        self.update_quality_combo()

    def update_quality_combo(self) -> None:
        from cd_ripper.core.ripper import get_quality_options

        opts = get_quality_options(self.fmt_var.get())
        if opts:
            self.quality_combo["values"] = list(opts.keys())
            self.quality_combo.current(0)
        else:
            self.quality_combo["values"] = ["Default"]
            self.quality_combo.current(0)
