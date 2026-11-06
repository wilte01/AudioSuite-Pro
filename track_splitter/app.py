"""app.py — the Track Splitter window.

The shell (Help bar, notebook, Processing and Results tabs) comes from
``audio_suite_shared.suite_app.SuiteApp``; this module supplies the Setup tab,
the run, and the three callback seams.  The run happens on a worker thread and
hands every result to the Tk thread through a ``SimpleQueue``: a worker thread
that called ``root.after`` (or any widget method) would raise on 3.14 and leave
the window waiting for a result that never arrives.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E4).
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any

from audio_suite_shared import styles, suite_config
from audio_suite_shared.cli_helpers import was_launched_from_driver
from audio_suite_shared.exceptions import AudioConfigValueError
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from track_splitter.core.models import BOUNDARY_RULES, SplitSettings
from track_splitter.core.splitter import run_split

from .utils import cli_args

logger = logging.getLogger(__name__)

LIVE_MODE = "Live Update"
DRY_MODE = "Dry Run"
RUN_MODES = (LIVE_MODE, DRY_MODE)

#: Combobox label → boundary rule.  The labels say what the user sees; the
#: values are the settings' own words, so the two cannot drift apart.
BOUNDARY_LABELS: dict[str, str] = {
    "Midpoint (half either side)": "midpoint",
    "Cut at silence start": "start",
    "Cut at silence end": "end",
}
_BY_RULE = {rule: label for label, rule in BOUNDARY_LABELS.items()}


class TrackSplitterApp(SuiteApp):
    """Split recordings into tracks at their silent gaps."""

    title = "Track Splitter"
    window_key = "track_splitter_window"
    program_name = "track_splitter"
    guide_name = "Track_Splitter_User_Guide.docx"
    completion_text = "Split Complete!"

    def __init__(
        self,
        root: tk.Tk,
        *,
        directory: str = "",
        output_dir: str = "",
        min_silence: str = "",
        silence_db: str = "",
        min_track: str = "",
        boundary: str = "",
        naming: str = "",
        cue: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.folder_path = tk.StringVar(value=suite_config.load_last_directory())
        self.output_path = tk.StringVar(value="")
        self.min_silence = tk.StringVar(value="700")
        self.silence_db = tk.StringVar(value="-45")
        self.min_track = tk.StringVar(value="5000")
        self.boundary_label = tk.StringVar(value=list(BOUNDARY_LABELS)[0])
        self.naming = tk.StringVar(value="{track:02d} - {title}")
        self.write_cue = tk.BooleanVar(value=True)
        self.run_mode = tk.StringVar(value=LIVE_MODE)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        self.controls_panel: DriverControlsPanel | None = None
        self._launched_from_driver = was_launched_from_driver()
        self._events: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._poll_id: str = ""
        self._closing = False

        self._apply_cli_args(
            directory=directory,
            output_dir=output_dir,
            min_silence=min_silence,
            silence_db=silence_db,
            min_track=min_track,
            boundary=boundary,
            naming=naming,
            cue=cue,
            dry_run=dry_run,
        )
        super().__init__(root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        if self.folder_path.get() and self._launched_from_driver:
            self.root.after(500, self._start_split)

    def _apply_cli_args(
        self,
        *,
        directory: str,
        output_dir: str,
        min_silence: str,
        silence_db: str,
        min_track: str,
        boundary: str,
        naming: str,
        cue: bool,
        dry_run: bool,
    ) -> None:
        """Pre-fill the window from the Master Driver / launcher arguments.

        Runs before the shell builds the tabs, so every widget is constructed
        from the value it will show rather than corrected afterwards.
        """
        if directory:
            self.folder_path.set(directory)
        if output_dir:
            self.output_path.set(output_dir)
        for var, value in (
            (self.min_silence, min_silence),
            (self.silence_db, silence_db),
            (self.min_track, min_track),
        ):
            if value:
                var.set(value)
        if boundary in _BY_RULE:
            self.boundary_label.set(_BY_RULE[boundary])
        if naming:
            self.naming.set(naming)
        self.write_cue.set(cue)
        if dry_run:
            self.run_mode.set(DRY_MODE)

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder pickers, the gap settings and the start button."""
        frame = tk.Frame(parent, padx=30, pady=20, bg=styles.BG_WHITE)
        frame.pack(expand=True, fill="both")

        tk.Label(
            frame,
            text=self.title,
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=(0, 16))

        panel = DriverControlsPanel(
            frame,
            source_var=self.folder_path,
            mode_var=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse,
            modes=RUN_MODES,
        )
        panel.pack(fill="x", pady=(0, 12))
        panel.set_driven(self._launched_from_driver)
        self.controls_panel = panel

        self._build_output_row(frame)
        self._build_settings_row(frame)

        tk.Checkbutton(
            frame,
            text="Write a CUE sheet describing the source's track starts",
            variable=self.write_cue,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
        ).pack(anchor="w", pady=(0, 6))

        self.start_btn = tk.Button(
            frame,
            text="Split Tracks",
            command=self._start_split,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief="flat",
            padx=12,
        )
        self.start_btn.pack(anchor="w", pady=(6, 10))

        tk.Label(
            frame,
            text=(
                "Silence is measured by FFmpeg at the threshold given, relative "
                "to full scale. A gap's silence stays with the track before it "
                "(cut at silence end), after it (cut at silence start), or is "
                "halved. Each track is cut sample-accurately by re-encoding."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=760,
            justify=tk.LEFT,
        ).pack(anchor="w")

    def _build_output_row(self, parent: tk.Frame) -> None:
        """Emit the output-folder row."""
        row = tk.Frame(parent, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=2)
        tk.Label(
            row,
            text="Tracks go to:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=22,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            row,
            textvariable=self.output_path,
            width=42,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)
        tk.Button(
            row,
            text="Browse",
            command=self._browse_output,
            font=styles.FONT_CAPTION,
            bg=styles.BG_LIGHT,
            fg=styles.FG_MAIN,
            relief="flat",
            padx=6,
        ).pack(side=tk.LEFT)

    def _build_settings_row(self, parent: tk.Frame) -> None:
        """Emit the threshold, length, boundary and naming controls."""
        for label, var, width in (
            ("Minimum silence (ms):", self.min_silence, 10),
            ("Silence threshold (dBFS):", self.silence_db, 10),
            ("Minimum track (ms):", self.min_track, 10),
        ):
            row = tk.Frame(parent, bg=styles.BG_WHITE)
            row.pack(fill="x", pady=2)
            tk.Label(
                row,
                text=label,
                font=styles.FONT_CAPTION,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                width=22,
                anchor="w",
            ).pack(side=tk.LEFT)
            tk.Entry(
                row,
                textvariable=var,
                width=width,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                insertbackground=styles.FG_MAIN,
            ).pack(side=tk.LEFT, padx=6)

        row = tk.Frame(parent, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=2)
        tk.Label(
            row,
            text="Boundary:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=22,
            anchor="w",
        ).pack(side=tk.LEFT)
        box = ttk.Combobox(
            row,
            textvariable=self.boundary_label,
            state="readonly",
            width=30,
            font=styles.FONT_BODY,
            values=tuple(BOUNDARY_LABELS),
        )
        box.pack(side=tk.LEFT, padx=6)

        row = tk.Frame(parent, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=(2, 8))
        tk.Label(
            row,
            text="Naming pattern:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=22,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            row,
            textvariable=self.naming,
            width=30,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.folder_path.get() or "")
        if folder:
            self.folder_path.set(folder)
            suite_config.save_last_directory(folder)

    def _browse_output(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.output_path.get() or "")
        if folder:
            self.output_path.set(folder)

    def _settings(self) -> SplitSettings:
        """Build the run's settings from the widgets.

        Raises:
            ValueError: A numeric field is not a number.
        """
        return SplitSettings(
            min_silence_ms=int(self.min_silence.get().strip()),
            silence_db=float(self.silence_db.get().strip()),
            min_track_ms=int(self.min_track.get().strip()),
            boundary=BOUNDARY_LABELS.get(
                self.boundary_label.get(), list(BOUNDARY_RULES)[0]
            ),
            naming_pattern=self.naming.get().strip(),
            write_cue=self.write_cue.get(),
        )

    def _start_split(self) -> None:
        """Validate the widgets, then hand the run to a worker thread."""
        path = self.folder_path.get().strip()
        if not path or not os.path.isdir(path):
            messagebox.showwarning(
                "Invalid Folder", "Please select a valid source folder."
            )
            return
        try:
            settings = self._settings()
        except ValueError:
            messagebox.showwarning(
                "Invalid Setting", "The length and level fields must be numbers."
            )
            return
        except AudioConfigValueError as exc:
            messagebox.showwarning("Invalid Setting", exc.message)
            return

        if self._thread is not None and self._thread.is_alive():
            return
        self.start_btn.config(state="disabled", text="Splitting...")
        self.progress["mode"] = "determinate"
        self.progress["value"] = 0
        self.progress["maximum"] = 1
        self.stats_label.config(text="Splitting...")
        dry_run = self.run_mode.get() == DRY_MODE
        self._thread = threading.Thread(
            target=self._worker,
            args=(path, self.output_path.get().strip() or None, settings, dry_run),
            daemon=True,
        )
        self._thread.start()
        self._poll_events()

    def _worker(
        self,
        path: str,
        output_dir: str | None,
        settings: SplitSettings,
        dry_run: bool,
    ) -> None:
        """Run the split off the Tk thread; never touch a widget here."""
        try:
            run_split(
                path,
                output_dir=output_dir,
                settings=settings,
                dry_run=dry_run,
                on_progress=self._on_progress,
                on_complete=self._on_complete,
                on_error=self._on_error,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced in the window, never lost
            self._events.put(("fatal", exc))

    # ── Callback seams ────────────────────────────────────────────────────────

    def _on_progress(self, **payload: Any) -> None:
        """Queue one progress payload for the Tk thread."""
        self._events.put(("progress", payload))

    def _on_complete(
        self,
        *,
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        **_extra: Any,
    ) -> None:
        """Queue the completion payload for the Tk thread.

        The five counters are declared because the poller displays every one of
        them; the tool's own fields (``tracks``, ``files_written``,
        ``output_dir``) ride the catch-all so a payload that grows cannot raise
        inside the callback.
        """
        self._events.put(
            (
                "complete",
                {
                    "total": total,
                    "processed": processed,
                    "skipped": skipped,
                    "errors": errors,
                    "duration_secs": duration_secs,
                    **_extra,
                },
            )
        )

    def _on_error(self, message: str) -> None:
        """Queue a run-failure message for the Tk thread."""
        self._events.put(("error", message))

    # ── Tk-thread poller ──────────────────────────────────────────────────────

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
            if kind == "progress":
                self.render_progress(
                    processed=int(payload.get("processed", 0)),
                    total=int(payload.get("total", 0)),
                    display_text=str(payload.get("display_text", "")),
                )
                processed = payload.get("processed", 0)
                total = payload.get("total", 0)
                self.stats_label.config(
                    text=(
                        f"Files: {processed}/{total}"
                        f" | Errors: {payload.get('errors', 0)}"
                    )
                )
            elif kind == "complete":
                self._finish(payload)
            else:
                self._failed(payload if isinstance(payload, str) else str(payload))
        if self._thread is not None and self._thread.is_alive():
            self._poll_id = self.root.after(100, self._poll_events)

    def _finish(self, payload: dict[str, Any]) -> None:
        """Render a finished run on the Results tab."""
        self.start_btn.config(state="normal", text="Split Tracks")
        tracks = payload.get("tracks", 0)
        written = payload.get("files_written", 0)
        self.progress["value"] = self.progress["maximum"]
        self.summary_label.config(
            text=(
                f"Files: {payload.get('total', 0)}\n"
                f"Tracks: {tracks}\n"
                f"Written: {written}\n"
                f"Errors: {payload.get('errors', 0)}"
            )
        )
        self.render_completion(
            duration_secs=float(payload.get("duration_secs", 0.0)),
            output_dir=str(payload.get("output_dir", "")),
        )
        if self.auto_end_var.get():
            self.root.after(1500, self.root.destroy)

    def _failed(self, message: str) -> None:
        """Show a run failure and re-enable the start button."""
        self.start_btn.config(state="normal", text="Split Tracks")
        self.stats_label.config(text="Split failed.")
        messagebox.showerror("Split Error", message)

    def _on_close(self) -> None:
        """Stop the poller, then close the window."""
        self._closing = True
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = ""
        self.root.destroy()


def main() -> None:
    """Parse the launcher argv, pre-fill the window and enter the mainloop."""
    from audio_suite_shared.styles import bootstrap_theme

    args = parse_cli_args(cli_args.parse)
    root = tk.Tk()
    bootstrap_theme()
    TrackSplitterApp(
        root,
        directory=args.folder_path,
        output_dir=args.output_dir,
        min_silence=args.min_silence,
        silence_db=args.silence_db,
        min_track=args.min_track,
        boundary=args.boundary,
        naming=args.naming,
        cue=args.cue,
        dry_run=getattr(args, "live_mode", True) is False,
    )
    root.mainloop()
