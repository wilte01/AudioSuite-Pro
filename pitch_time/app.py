"""app.py — the Pitch / Time window.

The shell (Help bar, notebook, Processing and Results tabs) comes from
``audio_suite_shared.suite_app.SuiteApp``; this module supplies the Setup tab,
the mode and its value, the run and the three callback seams.  The run happens
on a worker thread and hands every result to the Tk thread through a
``SimpleQueue``: a worker thread that called ``root.after`` (or any widget
method) would raise on 3.14 and leave the window waiting for a result that
never arrives.

Changed in 2.7.0: new module (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
Changed in 2.7.0: the Tempo / Pitch row is labelled "Change:" rather than
"Mode:", which the run-mode row above it already used; two rows sharing one
word read as one control.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

from audio_suite_shared import styles, suite_config
from audio_suite_shared.cli_helpers import was_launched_from_driver
from audio_suite_shared.exceptions import AudioConfigValueError
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from pitch_time.core.engine import REPORT_NAMES, discover, run_pitch_time
from pitch_time.core.models import (
    MODE_LABELS,
    MODE_PITCH,
    MODE_TEMPO,
    MODES,
    PitchTimeSettings,
)

from .utils import cli_args

logger = logging.getLogger(__name__)

LIVE_MODE = "Live Update"
DRY_MODE = "Dry Run"
RUN_MODES = (LIVE_MODE, DRY_MODE)


class PitchTimeApp(SuiteApp):
    """Change a folder's tempo or pitch, writing each result beside its source."""

    title = "Pitch / Time"
    window_key = "pitch_time_window"
    program_name = "pitch_time"
    guide_name = "Pitch_Time_User_Guide.docx"
    completion_text = "Pitch / Time Complete!"

    def __init__(
        self,
        root: tk.Tk,
        *,
        directory: str = "",
        rate: str = "",
        semitones: str = "",
        dry_run: bool = False,
    ) -> None:
        self.folder_path = tk.StringVar(value=suite_config.load_last_directory())
        self.transform_mode = tk.StringVar(value=MODE_TEMPO)
        self.rate_var = tk.StringVar(value="1.0")
        self.semitones_var = tk.StringVar(value="0.0")
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
        self._settings_label: tk.Label | None = None

        self._apply_cli_args(
            directory=directory,
            rate=rate,
            semitones=semitones,
            dry_run=dry_run,
        )
        super().__init__(root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._update_settings_label()
        if self.folder_path.get() and self._launched_from_driver:
            self.root.after(500, self._start_run)

    def _apply_cli_args(
        self,
        *,
        directory: str,
        rate: str,
        semitones: str,
        dry_run: bool,
    ) -> None:
        """Pre-fill the window from the Master Driver / launcher arguments.

        Runs before the shell builds the tabs, so every widget is constructed
        from the value it will show rather than corrected afterwards.  A launch
        that names semitones switches the mode with it: the flag *is* the mode.
        """
        if directory:
            self.folder_path.set(directory)
        if rate:
            self.rate_var.set(rate)
            self.transform_mode.set(MODE_TEMPO)
        if semitones:
            self.semitones_var.set(semitones)
            self.transform_mode.set(MODE_PITCH)
        if dry_run:
            self.run_mode.set(DRY_MODE)

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder, the mode, its value and Start."""
        frame = tk.Frame(parent, padx=30, pady=16, bg=styles.BG_WHITE)
        frame.pack(expand=True, fill="both")

        tk.Label(
            frame,
            text=self.title,
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=(0, 12))

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
        panel.pack(fill="x", pady=(0, 10))
        panel.set_driven(self._launched_from_driver)
        self.controls_panel = panel

        self._build_mode_rows(frame)
        self._build_value_rows(frame)

        self._settings_label = tk.Label(
            frame,
            text="",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            anchor="w",
        )
        self._settings_label.pack(fill="x", pady=(4, 6))

        self.start_btn = tk.Button(
            frame,
            text="Process Files",
            command=self._start_run,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief="flat",
            padx=12,
        )
        self.start_btn.pack(anchor="w", pady=(4, 8))

        tk.Label(
            frame,
            text=(
                "Tempo keeps the pitch and changes the length; Pitch keeps the "
                "length and changes the pitch. Each result is written beside its "
                "source under a name that carries the setting, so the original "
                "file is never replaced. The source's sample rate, channels, "
                "bit depth and tags are kept."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=760,
            justify=tk.LEFT,
        ).pack(anchor="w")

    def _build_mode_rows(self, parent: tk.Frame) -> None:
        """Emit the Tempo / Pitch choice."""
        row = tk.Frame(parent, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=2)
        tk.Label(
            row,
            text="Change:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=22,
            anchor="w",
        ).pack(side=tk.LEFT)
        for mode in MODES:
            tk.Radiobutton(
                row,
                text=MODE_LABELS[mode],
                variable=self.transform_mode,
                value=mode,
                command=self._update_settings_label,
                font=styles.FONT_CAPTION,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                activebackground=styles.BG_WHITE,
                activeforeground=styles.FG_MAIN,
            ).pack(side=tk.LEFT, padx=(0, 12))

    def _build_value_rows(self, parent: tk.Frame) -> None:
        """Emit the rate and semitone fields."""
        for label, var in (
            ("Tempo rate (factor):", self.rate_var),
            ("Pitch shift (semitones):", self.semitones_var),
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
                width=10,
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

    def _settings(self) -> PitchTimeSettings:
        """Build the run's settings from the widgets.

        Raises:
            ValueError: A numeric field is not a number.
            AudioConfigValueError: The mode or a value is not one the engine
                can honour.
        """
        try:
            rate = float(self.rate_var.get().strip() or "1.0")
            semitones = float(self.semitones_var.get().strip() or "0.0")
        except ValueError as exc:
            raise ValueError("The rate and semitones fields must be numbers.") from exc
        return PitchTimeSettings(
            mode=self.transform_mode.get(), rate=rate, semitones=semitones
        )

    def _update_settings_label(self) -> None:
        """Show the setting the run would use, and say when it changes nothing."""
        if self._settings_label is None:
            return
        try:
            settings = self._settings()
        except (ValueError, AudioConfigValueError) as exc:
            text = getattr(exc, "message", None) or str(exc)
            self._settings_label.config(text=text)
            return
        suffix = " (no change requested)" if settings.is_neutral else ""
        self._settings_label.config(text=f"Setting: {settings.description}{suffix}")

    def _start_run(self) -> None:
        """Validate the window, name the report, then run on a worker thread."""
        folder = self.folder_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning(
                "Invalid Folder", "Please select a valid source folder."
            )
            return
        try:
            settings = self._settings()
        except ValueError:
            messagebox.showwarning(
                "Invalid Setting", "The rate and semitones fields must be numbers."
            )
            return
        except AudioConfigValueError as exc:
            messagebox.showwarning("Invalid Setting", exc.message)
            return

        if self._thread is not None and self._thread.is_alive():
            return
        dry_run = self.run_mode.get() == DRY_MODE
        self._log_path = str(Path(folder) / REPORT_NAMES[dry_run])
        self.start_btn.config(state="disabled", text="Processing...")
        self.progress["mode"] = "determinate"
        self.progress["value"] = 0
        self.progress["maximum"] = max(len(discover(Path(folder))), 1)
        self.stats_label.config(text="Processing...")
        self._thread = threading.Thread(
            target=self._worker,
            args=(folder, settings, dry_run),
            daemon=True,
        )
        self._thread.start()
        self._poll_events()

    def _worker(self, folder: str, settings: PitchTimeSettings, dry_run: bool) -> None:
        """Run the batch off the Tk thread; never touch a widget here."""
        try:
            run_pitch_time(
                folder,
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
        them; the tool's own fields (``written``, ``mode``, ``rate``,
        ``semitones``) ride the catch-all so a payload that grows cannot raise
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
                self.stats_label.config(
                    text=(
                        f"Files: {payload.get('processed', 0)}"
                        f"/{payload.get('total', 0)}"
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
        self.start_btn.config(state="normal", text="Process Files")
        self.progress["value"] = self.progress["maximum"]
        self.summary_label.config(
            text=(
                f"Files: {payload.get('total', 0)}\n"
                f"Written: {payload.get('written', 0)}\n"
                f"Skipped: {payload.get('skipped', 0)}\n"
                f"Errors: {payload.get('errors', 0)}"
            )
        )
        self.render_completion(
            duration_secs=float(payload.get("duration_secs", 0.0)),
            output_dir=self.folder_path.get().strip(),
        )
        if self.auto_end_var.get():
            self.root.after(1500, self.root.destroy)

    def _failed(self, message: str) -> None:
        """Show a run failure and re-enable the start button."""
        self.start_btn.config(state="normal", text="Process Files")
        self.stats_label.config(text="Processing failed.")
        messagebox.showerror("Pitch / Time Error", message)

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
    PitchTimeApp(
        root,
        directory=args.folder_path,
        rate=args.rate,
        semitones=args.semitones,
        dry_run=getattr(args, "live_mode", True) is False,
    )
    root.mainloop()
