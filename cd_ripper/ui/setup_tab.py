"""
cd_ripper/ui/setup_tab.py — Setup tab container (decomposed).
"""

import os
import sys
import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, ttk
from typing import Any

from audio_suite_shared import styles, ui_common
from cd_ripper.core.cd_ripper_config import set_output_dir
from cd_ripper.core.disc import DiscInfo

from .drive_config_panel import DriveConfigPanel
from .format_config_panel import FormatConfigPanel
from .metadata_config_panel import MetadataConfigPanel


class SetupTab:
    """Setup tab UI container for CD Ripper."""

    def __init__(
        self,
        notebook: Any,
        state: dict[str, Any],
        ready_cb: Callable[[], None],
    ) -> None:
        self.state = state
        self.ready_cb = ready_cb
        self.frame = tk.Frame(notebook, bg=styles.BG_WHITE)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        self._proceed_btn = tk.Button(
            self.frame,
            text="PROCEED TO RIP  ▶",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            height=2,
            command=self._proceed,
            state="disabled",
        )
        self._proceed_btn.pack(side="bottom", fill="x", padx=30, pady=(4, 15))

        canvas = tk.Canvas(self.frame, bg=styles.BG_WHITE, highlightthickness=0)
        vsb = ttk.Scrollbar(self.frame, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        outer = tk.Frame(canvas, padx=30, pady=15, bg=styles.BG_WHITE)
        win = canvas.create_window((0, 0), window=outer, anchor="nw")

        outer.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))
        canvas.bind_all(
            "<MouseWheel>",
            lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
        )

        tk.Label(
            outer,
            text="CD Ripper",
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=(0, 10))

        self._drive_panel = DriveConfigPanel(
            outer,
            self.state,
            on_disc_read_cb=self._on_disc_read,
            on_release_applied_cb=self._on_release_applied,
            set_proceed_enabled=lambda enabled: self._proceed_btn.configure(
                state="normal" if enabled else "disabled"
            ),
        )
        self._drive_panel.frame.pack(fill="x")

        self._meta_panel = MetadataConfigPanel(outer)
        self._meta_panel.frame.pack(fill="x")

        self._fmt_panel = FormatConfigPanel(outer)
        self._fmt_panel.frame.pack(fill="x")

        info_frame = tk.Frame(outer, bg="#e8f4f8", relief=tk.RIDGE, bd=1)
        info_frame.pack(fill="x", pady=8)
        tk.Label(
            info_frame,
            text=(
                "ℹ Insert a CD and click Read Disc to read the TOC and look up "
                "metadata.\n"
                "• Double-click any track title or artist name to edit it inline.\n"
                "• Use Apply to all tracks to push album/artist/year/genre to every "
                "track.\n"
                "• Administrator rights are required for raw CD audio extraction."
            ),
            font=styles.FONT_CAPTION,
            bg="#e8f4f8",
            justify=tk.LEFT,
            wraplength=700,
        ).pack(padx=10, pady=6)

        self._drive_panel.refresh_drives()

    # ── Callbacks from sub-panels ─────────────────────────────────────────────

    def _on_disc_read(self, info: DiscInfo) -> None:
        if info.release_info:
            self._meta_panel.populate_album_fields(info.tracks)
        self._meta_panel.populate_tracks(info.tracks)

    def _on_release_applied(self) -> None:
        if self._drive_panel._disc_info:
            self._meta_panel.populate_album_fields(self._drive_panel._disc_info.tracks)
            self._meta_panel.populate_tracks(self._drive_panel._disc_info.tracks)

    # ── Proceed ───────────────────────────────────────────────────────────────

    def apply_cli_settings(
        self,
        *,
        output_dir: str = "",
        format_label: str = "",
        cue: bool = False,
    ) -> None:
        """Pre-fill the format panel from the Master Driver / CLI arguments.

        The update path for each widget mirrors what the user's interaction
        triggers, satisfying the project AGENTS pre-fill rule.

        Args:
            output_dir: Output directory from ``--output-dir``.
            format_label: GUI display name (e.g. ``"FLAC"``) from ``--format``.
            cue: Whether to write a CUE sheet (``--cue``).
        """
        if output_dir:
            self._fmt_panel.out_var.set(output_dir)
            self._fmt_panel.on_out_dir_changed()
        if format_label:
            self._fmt_panel.fmt_var.set(format_label)
            self._fmt_panel.on_fmt_changed()
        if cue:
            self._fmt_panel.cue_var.set(True)

    def _proceed(self) -> None:
        tracks = self.state.get("tracks", [])
        cli_filter = self.state.get("cli_track_filter")
        if cli_filter:
            tracks = [t for t in tracks if t["number"] in cli_filter]
            self.state["tracks"] = tracks
        if not tracks:
            ui_common.show_message(
                self.frame,
                "No Tracks",
                "Please read a disc first.",
                icon="⚠",
                icon_color="#d97706",
            )
            return

        out_dir = self._fmt_panel.out_var.get().strip()
        if not out_dir:
            ui_common.show_message(
                self.frame,
                "Output Folder Required",
                "Please choose an output folder before proceeding.",
            )
            folder = filedialog.askdirectory(title="Select Output Folder")
            if not folder:
                return
            self._fmt_panel.out_var.set(folder)
            out_dir = folder

        set_output_dir(out_dir)

        from cd_ripper.core.ripper import FORMAT_OPTIONS, get_quality_options

        fmt = self._fmt_panel.fmt_var.get()
        quality_label = self._fmt_panel.quality_var.get()
        opts = get_quality_options(fmt)
        quality_args = (
            opts.get(quality_label) if opts else FORMAT_OPTIONS[fmt]["codec_args"]
        )

        _core = os.path.normpath(
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "core")
        )
        _local_name = "ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"
        ffmpeg = os.path.join(_core, _local_name)
        ffmpeg = ffmpeg if os.path.exists(ffmpeg) else "ffmpeg"

        self.state.update(
            {
                "out_dir": out_dir,
                "fmt": fmt,
                "quality_args": quality_args,
                "ffmpeg_path": ffmpeg,
                "write_cue": bool(self._fmt_panel.cue_var.get()),
                "verify_mode": self._fmt_panel.verify_var.get(),
            }
        )
        self.ready_cb()
