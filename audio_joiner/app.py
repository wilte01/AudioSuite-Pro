"""app.py — the Audio Joiner window.

The shell (Help bar, notebook, Processing and Results tabs) comes from
``audio_suite_shared.suite_app.SuiteApp``; this module supplies the Setup tab,
the segment order, the run and the three callback seams.  The run happens on a
worker thread and hands every result to the Tk thread through a
``SimpleQueue``: a worker thread that called ``root.after`` (or any widget
method) would raise on 3.14 and leave the window waiting for a result that
never arrives.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
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

from audio_joiner.core.join import (
    INPUT_EXTENSIONS,
    REPORT_NAMES,
    measure_durations,
    preferred_order,
    run_join,
)
from audio_joiner.core.models import JoinSettings
from audio_suite_shared import styles, suite_config
from audio_suite_shared.cli_helpers import was_launched_from_driver
from audio_suite_shared.exceptions import AudioConfigValueError
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.ui_driver_controls import DriverControlsPanel

from .utils import cli_args

logger = logging.getLogger(__name__)

LIVE_MODE = "Live Update"
DRY_MODE = "Dry Run"
RUN_MODES = (LIVE_MODE, DRY_MODE)


def _clock(ms: int) -> str:
    """Render milliseconds as ``MM:SS.mmm``."""
    minutes, rest = divmod(max(ms, 0), 60_000)
    seconds, millis = divmod(rest, 1000)
    return f"{minutes:02d}:{seconds:02d}.{millis:03d}"


class AudioJoinerApp(SuiteApp):
    """Join a folder's segments into one file, in a chosen order."""

    title = "Audio Joiner"
    window_key = "audio_joiner_window"
    program_name = "audio_joiner"
    guide_name = "Audio_Joiner_User_Guide.docx"
    completion_text = "Join Complete!"

    def __init__(
        self,
        root: tk.Tk,
        *,
        directory: str = "",
        order: str = "",
        output: str = "",
        gap_ms: str = "",
        crossfade_ms: str = "",
        copy_when_compatible: bool = True,
        dry_run: bool = False,
    ) -> None:
        self.folder_path = tk.StringVar(value=suite_config.load_last_directory())
        self.output_path = tk.StringVar(value="")
        self.gap_ms = tk.StringVar(value="0")
        self.crossfade_ms = tk.StringVar(value="0")
        self.copy_compatible = tk.BooleanVar(value=True)
        self.run_mode = tk.StringVar(value=LIVE_MODE)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        self.controls_panel: DriverControlsPanel | None = None
        self._launched_from_driver = was_launched_from_driver()
        self._segments: list[Path] = []
        self._durations: dict[Path, int] = {}
        # The launched order is resolved once the folder is known, because a
        # file name may itself contain the separator this string uses.
        self._pending_order = order
        self._preferred_order: list[str] = []
        self._events: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._poll_id: str = ""
        self._closing = False
        self._planned_label: tk.Label | None = None
        self._segment_list: tk.Listbox | None = None

        self._apply_cli_args(
            directory=directory,
            output=output,
            gap_ms=gap_ms,
            crossfade_ms=crossfade_ms,
            copy_when_compatible=copy_when_compatible,
            dry_run=dry_run,
        )
        super().__init__(root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_segments()
        if self.folder_path.get() and self._launched_from_driver:
            self.root.after(500, self._start_join)

    def _apply_cli_args(
        self,
        *,
        directory: str,
        output: str,
        gap_ms: str,
        crossfade_ms: str,
        copy_when_compatible: bool,
        dry_run: bool,
    ) -> None:
        """Pre-fill the window from the Master Driver / launcher arguments.

        Runs before the shell builds the tabs, so every widget is constructed
        from the value it will show rather than corrected afterwards.
        """
        if directory:
            self.folder_path.set(directory)
        if output:
            self.output_path.set(output)
        if gap_ms:
            self.gap_ms.set(gap_ms)
        if crossfade_ms:
            self.crossfade_ms.set(crossfade_ms)
        self.copy_compatible.set(copy_when_compatible)
        if dry_run:
            self.run_mode.set(DRY_MODE)

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder, the segment order, the boundary settings and Start."""
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

        self._build_segment_rows(frame)
        self._build_boundary_rows(frame)

        self._planned_label = tk.Label(
            frame,
            text="Segments: 0",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            anchor="w",
        )
        self._planned_label.pack(fill="x", pady=(4, 6))

        self.start_btn = tk.Button(
            frame,
            text="Join Segments",
            command=self._start_join,
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
                "A straight join is a stream copy when every segment shares the "
                "first file's codec and parameters; otherwise every segment is "
                "re-encoded to the first file's rate and channel count, and the "
                "report says so. A gap inserts silence at each boundary; a "
                "crossfade overlaps them with an equal-power fade."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=760,
            justify=tk.LEFT,
        ).pack(anchor="w")

    def _build_segment_rows(self, parent: tk.Frame) -> None:
        """Emit the segment list and the buttons that reorder it."""
        row = tk.Frame(parent, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=2)

        holder = tk.Frame(row, bg=styles.BG_WHITE)
        holder.pack(side=tk.LEFT)
        self._segment_list = tk.Listbox(
            holder,
            height=7,
            width=58,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectbackground=styles.get_main(),
        )
        self._segment_list.pack(side=tk.LEFT, fill="y")

        buttons = tk.Frame(row, bg=styles.BG_WHITE)
        buttons.pack(side=tk.LEFT, padx=8, anchor="n")
        for label, command in (
            ("Move up", lambda: self._move(-1)),
            ("Move down", lambda: self._move(1)),
            ("Reload", self._reload_segments),
        ):
            tk.Button(
                buttons,
                text=label,
                command=command,
                font=styles.FONT_CAPTION,
                bg=styles.BG_LIGHT,
                fg=styles.FG_MAIN,
                relief="flat",
                padx=6,
            ).pack(fill="x", pady=1)

        row = tk.Frame(parent, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=2)
        tk.Label(
            row,
            text="Join into:",
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

    def _build_boundary_rows(self, parent: tk.Frame) -> None:
        """Emit the gap, crossfade and stream-copy controls."""
        for label, var in (
            ("Gap (ms):", self.gap_ms),
            ("Crossfade (ms):", self.crossfade_ms),
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

        tk.Checkbutton(
            parent,
            text="Stream-copy when every segment already matches the first file",
            variable=self.copy_compatible,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
        ).pack(anchor="w", pady=(0, 4))

    # ── Segment order ─────────────────────────────────────────────────────────

    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.folder_path.get() or "")
        if folder:
            self.folder_path.set(folder)
            suite_config.save_last_directory(folder)
            self._refresh_segments()

    def _browse_output(self) -> None:
        chosen = filedialog.asksaveasfilename(
            initialdir=self.output_path.get() or self.folder_path.get() or ""
        )
        if chosen:
            self.output_path.set(chosen)

    def _reload_segments(self) -> None:
        """Re-read the folder, keeping any order the user already chose."""
        kept = [path.name for path in self._segments]
        self._preferred_order = kept
        self._refresh_segments()

    def _refresh_segments(self) -> None:
        """Fill the list from the folder, honouring the preferred order first."""
        folder = self.folder_path.get().strip()
        self._segments = []
        self._durations = {}
        if folder and os.path.isdir(folder):
            found = sorted(
                path
                for path in Path(folder).iterdir()
                if path.is_file() and path.suffix.lower() in INPUT_EXTENSIONS
            )
            by_name = {path.name: path for path in found}
            if self._pending_order:
                self._preferred_order = [
                    path.name
                    for path in preferred_order(Path(folder), self._pending_order)
                ]
                self._pending_order = ""
            ordered = [
                by_name.pop(name) for name in self._preferred_order if name in by_name
            ]
            ordered.extend(by_name[name] for name in sorted(by_name))
            self._segments = ordered
            try:
                durations = measure_durations(ordered)
            except (AudioConfigValueError, OSError, ValueError):
                durations = ()
            self._durations = dict(zip(ordered, durations)) if durations else {}
        self._render_segments()

    def _render_segments(self) -> None:
        """Redraw the list and the planned-length line."""
        if self._segment_list is not None:
            self._segment_list.delete(0, tk.END)
            for path in self._segments:
                duration = self._durations.get(path)
                label = f"{path.name}  {_clock(duration)}" if duration else path.name
                self._segment_list.insert(tk.END, label)
        if self._planned_label is not None:
            self._planned_label.config(text=self._planned_text())

    def _planned_text(self) -> str:
        """Return the plan line for the current segments and settings."""
        if not self._segments:
            return "Segments: 0"
        try:
            settings = self._settings()
            total = plan_total(self._durations, self._segments, settings)
        except (ValueError, AudioConfigValueError) as exc:
            return f"Segments: {len(self._segments)} - {getattr(exc, 'message', exc)}"
        return f"Segments: {len(self._segments)} | Planned length: {_clock(total)}"

    def _move(self, delta: int) -> None:
        """Move the selected segment one slot up or down."""
        if self._segment_list is None:
            return
        selection = self._segment_list.curselection()
        if not selection:
            return
        index = int(selection[0])
        target = index + delta
        if not 0 <= target < len(self._segments):
            return
        self._segments[index], self._segments[target] = (
            self._segments[target],
            self._segments[index],
        )
        self._render_segments()
        self._segment_list.selection_set(target)
        self._segment_list.see(target)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _settings(self) -> JoinSettings:
        """Build the run's settings from the widgets.

        Raises:
            ValueError: A numeric field is not a number.
            AudioConfigValueError: The settings describe no valid boundary.
        """
        return JoinSettings(
            gap_ms=int(self.gap_ms.get().strip() or "0"),
            crossfade_ms=int(self.crossfade_ms.get().strip() or "0"),
            copy_when_compatible=self.copy_compatible.get(),
        )

    def _start_join(self) -> None:
        """Validate the window, name the report, then run on a worker thread."""
        folder = self.folder_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning(
                "Invalid Folder", "Please select a valid source folder."
            )
            return
        if len(self._segments) < 2:
            messagebox.showwarning(
                "Not Enough Segments",
                "A join needs at least two audio files in the source folder.",
            )
            return
        try:
            settings = self._settings()
        except ValueError:
            messagebox.showwarning(
                "Invalid Setting", "The gap and crossfade fields must be numbers."
            )
            return
        except AudioConfigValueError as exc:
            messagebox.showwarning("Invalid Setting", exc.message)
            return

        if self._thread is not None and self._thread.is_alive():
            return
        dry_run = self.run_mode.get() == DRY_MODE
        self._log_path = str(Path(folder) / REPORT_NAMES[dry_run])
        self.start_btn.config(state="disabled", text="Joining...")
        self.progress["mode"] = "determinate"
        self.progress["value"] = 0
        self.progress["maximum"] = len(self._segments)
        self.stats_label.config(text="Joining...")
        self._thread = threading.Thread(
            target=self._worker,
            args=(
                folder,
                ",".join(path.name for path in self._segments),
                self.output_path.get().strip(),
                settings,
                dry_run,
            ),
            daemon=True,
        )
        self._thread.start()
        self._poll_events()

    def _worker(
        self,
        folder: str,
        order: str,
        output: str,
        settings: JoinSettings,
        dry_run: bool,
    ) -> None:
        """Run the join off the Tk thread; never touch a widget here."""
        try:
            run_join(
                folder,
                order=order,
                output=output,
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
        them; the tool's own fields (``output``, ``duration_ms``, ``segments``)
        ride the catch-all so a payload that grows cannot raise inside the
        callback.
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
                        f"Segments: {payload.get('processed', 0)}"
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
        self.start_btn.config(state="normal", text="Join Segments")
        self.progress["value"] = self.progress["maximum"]
        writer = "stream copy" if payload.get("reencoded") is False else "re-encode"
        self.summary_label.config(
            text=(
                f"Segments: {payload.get('segments', 0)}\n"
                f"Length: {_clock(int(payload.get('duration_ms', 0)))}\n"
                f"Writer: {writer}\n"
                f"Errors: {payload.get('errors', 0)}"
            )
        )
        output = str(payload.get("output", ""))
        self.render_completion(
            duration_secs=float(payload.get("duration_secs", 0.0)),
            output_dir=str(Path(output).parent) if output else "",
        )
        if self.auto_end_var.get():
            self.root.after(1500, self.root.destroy)

    def _failed(self, message: str) -> None:
        """Show a run failure and re-enable the start button."""
        self.start_btn.config(state="normal", text="Join Segments")
        self.stats_label.config(text="Join failed.")
        messagebox.showerror("Join Error", message)

    def _on_close(self) -> None:
        """Stop the poller, then close the window."""
        self._closing = True
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = ""
        self.root.destroy()


def plan_total(
    durations: dict[Path, int], segments: list[Path], settings: JoinSettings
) -> int:
    """Return the planned length for the window's current segment list.

    Args:
        durations: Known lengths, keyed by segment.
        segments: The segments in join order.
        settings: The boundary settings.

    Returns:
        The planned length in milliseconds.

    Raises:
        AudioConfigValueError: A segment's length is unknown, or the settings
            produce no valid plan.
    """
    from audio_joiner.core.models import plan_duration_ms

    lengths = [durations[path] for path in segments if path in durations]
    if len(lengths) != len(segments):
        raise AudioConfigValueError(
            "Some segments' lengths could not be measured yet, so the planned "
            "length is not known. Reload the folder to measure them."
        )
    return plan_duration_ms(lengths, settings)


def main() -> None:
    """Parse the launcher argv, pre-fill the window and enter the mainloop."""
    from audio_suite_shared.styles import bootstrap_theme

    args = parse_cli_args(cli_args.parse)
    root = tk.Tk()
    bootstrap_theme()
    AudioJoinerApp(
        root,
        directory=args.folder_path,
        order=args.order,
        output=args.output,
        gap_ms=args.gap_ms,
        crossfade_ms=args.crossfade_ms,
        copy_when_compatible=args.copy,
        dry_run=getattr(args, "live_mode", True) is False,
    )
    root.mainloop()
