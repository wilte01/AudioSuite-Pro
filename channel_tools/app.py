"""app.py — the Channel Tools window.

The shell (Help bar, notebook, Processing and Results tabs) comes from
``audio_suite_shared.suite_app.SuiteApp``; this module supplies the Setup tab,
the run and the three callback seams.  The run happens on a worker thread and
hands every result to the Tk thread through a ``SimpleQueue``: a worker thread
that called ``root.after`` (or any widget method) would raise on 3.14 and leave
the window waiting for a result that never arrives.

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from audio_suite_shared import channel_ops, styles, suite_config
from audio_suite_shared.cli_helpers import was_launched_from_driver
from audio_suite_shared.exceptions import AudioConfigValueError
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.ui_driver_controls import DriverControlsPanel

from .core.models import ChannelSettings
from .core.processor import REPORT_NAMES, run_channels
from .utils import cli_args

logger = logging.getLogger(__name__)

LIVE_MODE = "Live Update"
DRY_MODE = "Dry Run"
RUN_MODES = (LIVE_MODE, DRY_MODE)

#: Combobox label → operation id.  The labels say what the user gets; the
#: values are the operation's own name, so the two cannot drift apart.
OPERATION_LABELS: dict[str, str] = {
    spec.label: spec.id for spec in channel_ops.OPERATIONS.values()
}
_BY_OPERATION = {operation: label for label, operation in OPERATION_LABELS.items()}

CHANNEL_LABELS: dict[str, str] = {"Left": "left", "Right": "right"}
INVERT_LABELS: dict[str, str] = {
    "Both sides": "both",
    "Left only": "left",
    "Right only": "right",
}

#: Where the window remembers the last operation it ran.
OPERATION_KEY = "channel_tools_operation"


def saved_operation() -> str:
    """Return the operation the last run used, or the default.

    Returns:
        An id from ``channel_ops.OPERATIONS``.  A stored value this build no
        longer knows is ignored rather than shown as a combobox value with no
        member.
    """
    stored = suite_config.load_value(OPERATION_KEY, channel_ops.DEFAULT_OPERATION)
    return stored if stored in channel_ops.OPERATIONS else channel_ops.DEFAULT_OPERATION


class ChannelToolsApp(SuiteApp):
    """Apply one channel operation to every file in a folder, in place."""

    title = "Channel Tools"
    window_key = "channel_tools_window"
    program_name = "channel_tools"
    guide_name = "Channel_Tools_User_Guide.docx"
    completion_text = "Channel Edit Complete!"

    def __init__(
        self,
        root: tk.Tk,
        *,
        directory: str = "",
        operation: str = "",
        width: str = "",
        source_channel: str = "",
        invert_target: str = "",
        dry_run: bool = False,
        auto_start: bool = False,
    ) -> None:
        self.folder_path = tk.StringVar(value=suite_config.load_last_directory())
        self.run_mode = tk.StringVar(value=LIVE_MODE)
        # The driver's Auto Start decides whether this launch runs by itself;
        # the panel shows the inherited state rather than its own default.
        self.auto_start_var = tk.BooleanVar(value=auto_start)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self.operation_label = tk.StringVar(
            value=_BY_OPERATION[operation or saved_operation()]
        )
        self.width_percent = tk.StringVar(value="100")
        self.channel_label = tk.StringVar(value="Left")
        self.invert_label = tk.StringVar(value="Both sides")
        self.rule_label: tk.Label | None = None

        self.controls_panel: DriverControlsPanel | None = None
        self._launched_from_driver = was_launched_from_driver()
        self._auto_start = auto_start
        self._events: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._poll_id: str = ""
        self._closing = False

        self._apply_cli_args(
            directory=directory,
            operation=operation,
            width=width,
            source_channel=source_channel,
            invert_target=invert_target,
            dry_run=dry_run,
        )
        super().__init__(root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_rule()
        if self._should_auto_run():
            self.root.after(500, self._start_channels)

    def _should_auto_run(self) -> bool:
        """Whether this launch starts the batch by itself.

        A Master Driver launch supplies the folder and the run mode, so it is
        not a reason to run: only a launch whose Auto Start was ticked (the
        ``--start`` handshake flag) runs on its own. Without this, a driver
        launch with Auto Start off applied the channels immediately instead of
        loading and waiting on Setup.

        Returns:
            True only when a folder is set, the process came from the driver
            and the handshake asked for Auto Start.
        """
        return bool(
            self.folder_path.get().strip()
            and self._launched_from_driver
            and self._auto_start
        )

    def _apply_cli_args(
        self,
        *,
        directory: str,
        operation: str,
        width: str,
        source_channel: str,
        invert_target: str,
        dry_run: bool,
    ) -> None:
        """Pre-fill the window from the Master Driver / launcher arguments.

        Runs before the shell builds the tabs, so every widget is constructed
        from the value it will show rather than corrected afterwards.
        """
        if directory:
            self.folder_path.set(directory)
        if operation in OPERATIONS_IDS:
            self.operation_label.set(_BY_OPERATION[operation])
        if width:
            self.width_percent.set(width)
        for label_map, value, var in (
            (CHANNEL_LABELS, source_channel, self.channel_label),
            (INVERT_LABELS, invert_target, self.invert_label),
        ):
            for label, stored in label_map.items():
                if value == stored:
                    var.set(label)
        if dry_run:
            self.run_mode.set(DRY_MODE)

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder controls, the operation and Start."""
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

        self._build_operation_row(frame)
        self._build_parameter_rows(frame)

        self.rule_label = tk.Label(
            frame,
            text="",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            anchor="w",
            justify=tk.LEFT,
            wraplength=760,
        )
        self.rule_label.pack(fill="x", pady=(6, 8))

        self.start_btn = tk.Button(
            frame,
            text="Apply Channels",
            command=self._start_channels,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief="flat",
            padx=12,
        )
        self.start_btn.pack(anchor="w", pady=(2, 10))

        tk.Label(
            frame,
            text=(
                "Files are rewritten in place through the shared workflow: tags "
                "survive, a lossless source keeps its bit depth, a live write can "
                "be undone, and an operation that changes nothing writes nothing. "
                "Mid/side and width need stereo input; more than two channels is "
                "refused rather than guessed at."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=760,
            justify=tk.LEFT,
        ).pack(anchor="w")

    def _build_operation_row(self, parent: tk.Frame) -> None:
        """Emit the operation dropdown and its live rule line."""
        row = tk.Frame(parent, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=2)
        tk.Label(
            row,
            text="Operation:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=22,
            anchor="w",
        ).pack(side=tk.LEFT)
        box = ttk.Combobox(
            row,
            textvariable=self.operation_label,
            state="readonly",
            width=52,
            font=styles.FONT_BODY,
            values=tuple(OPERATION_LABELS),
        )
        box.pack(side=tk.LEFT, padx=6)
        box.bind("<<ComboboxSelected>>", lambda _event: self._refresh_rule())

    def _build_parameter_rows(self, parent: tk.Frame) -> None:
        """Emit the width, source-channel and invert controls."""
        for label, var, values in (
            ("Width (percent):", self.width_percent, None),
            ("Dual-mono source:", self.channel_label, tuple(CHANNEL_LABELS)),
            ("Invert target:", self.invert_label, tuple(INVERT_LABELS)),
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
            if values is None:
                tk.Entry(
                    row,
                    textvariable=var,
                    width=10,
                    font=styles.FONT_BODY,
                    bg=styles.BG_WHITE,
                    fg=styles.FG_MAIN,
                    insertbackground=styles.FG_MAIN,
                ).pack(side=tk.LEFT, padx=6)
            else:
                ttk.Combobox(
                    row,
                    textvariable=var,
                    state="readonly",
                    width=16,
                    font=styles.FONT_BODY,
                    values=values,
                ).pack(side=tk.LEFT, padx=6)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _browse(self) -> None:
        folder = filedialog.askdirectory(initialdir=self.folder_path.get() or "")
        if folder:
            self.folder_path.set(folder)
            suite_config.save_last_directory(folder)

    def _settings(self) -> ChannelSettings:
        """Build the run's settings from the widgets.

        Raises:
            ValueError: The width is not a number.
            AudioConfigValueError: The request names no meaningful rule.
        """
        return ChannelSettings(
            operation=OPERATION_LABELS.get(
                self.operation_label.get(), channel_ops.DEFAULT_OPERATION
            ),
            width_percent=float(self.width_percent.get().strip() or "100"),
            source_channel=CHANNEL_LABELS.get(self.channel_label.get(), "left"),
            invert_target=INVERT_LABELS.get(self.invert_label.get(), "both"),
        )

    def _refresh_rule(self) -> None:
        """Show the rule the current widgets describe, or why they describe none."""
        if self.rule_label is None:
            return
        try:
            text = self._settings().rule
        except ValueError:
            text = "The width must be a number."
        except AudioConfigValueError as exc:
            text = exc.message
        self.rule_label.config(text=text)

    def _start_channels(self) -> None:
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
                "Invalid Setting", "The width field must be a number."
            )
            return
        except AudioConfigValueError as exc:
            messagebox.showwarning("Invalid Setting", exc.message)
            return

        if self._thread is not None and self._thread.is_alive():
            return
        dry_run = self.run_mode.get() == DRY_MODE
        self._refresh_rule()
        self._log_path = str(Path(folder) / REPORT_NAMES[dry_run])
        suite_config.save_value(OPERATION_KEY, settings.operation)
        self.start_btn.config(state="disabled", text="Processing...")
        self.progress["mode"] = "determinate"
        self.progress["value"] = 0
        self.stats_label.config(text="Processing channels...")
        self._thread = threading.Thread(
            target=self._worker,
            args=(folder, settings, dry_run),
            daemon=True,
        )
        self._thread.start()
        self._poll_events()

    def _worker(self, folder: str, settings: ChannelSettings, dry_run: bool) -> None:
        """Run the batch off the Tk thread; never touch a widget here."""
        try:
            run_channels(
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
        them; the tool's own fields (``succeeded``, ``report``, ``rule``) ride
        the catch-all so a payload that grows cannot raise inside the callback.
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
        self.start_btn.config(state="normal", text="Apply Channels")
        self.progress["value"] = self.progress["maximum"]
        self.summary_label.config(
            text=(
                f"Files: {payload.get('total', 0)}\n"
                f"Changed: {payload.get('succeeded', 0)}\n"
                f"Unchanged: {payload.get('skipped', 0)}\n"
                f"Errors: {payload.get('errors', 0)}\n"
                f"Rule: {payload.get('rule', '')}"
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
        self.start_btn.config(state="normal", text="Apply Channels")
        self.stats_label.config(text="Channel edit failed.")
        messagebox.showerror("Channel Error", message)

    def _on_close(self) -> None:
        """Stop the poller, then close the window."""
        self._closing = True
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = ""
        self.root.destroy()


#: The operation ids, in the order the combobox lists them.
OPERATIONS_IDS: tuple[str, ...] = channel_ops.OPERATION_IDS


def main() -> None:
    """Parse the launcher argv, pre-fill the window and enter the mainloop."""
    from audio_suite_shared.styles import bootstrap_theme

    args = parse_cli_args(cli_args.parse)
    root = tk.Tk()
    bootstrap_theme()
    ChannelToolsApp(
        root,
        directory=args.folder_path,
        operation=args.operation,
        width=args.width,
        source_channel=args.source_channel,
        invert_target=args.invert_target,
        dry_run=getattr(args, "live_mode", True) is False,
        # Changed in 2.7.0: the launch runs only when --start says so,
        # instead of any driver launch applying the folder (F-E6 follow-up).
        auto_start=getattr(args, "auto_start", False),
    )
    root.mainloop()
