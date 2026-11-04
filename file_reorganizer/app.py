"""
app.py
Tkinter GUI for Tag-Based File Reorganizer.

Scans a source tree, evaluates the two path templates against each file's
tags, and previews (dry run) or performs the copy/move into the resolved
destination hierarchy.

The window is built by ``audio_suite_shared.suite_app.SuiteApp``: the Help bar,
the Setup / Processing / Results notebook and the Processing and Results tabs
come from the shell.  This module supplies the Setup tab (run-controls strip,
presets, destination picker, action choice, pattern editors and the
Preview/Execute/Stop buttons), the run itself, and the four counters the
Processing tab reports.

Dry Run is the run-controls strip's **Mode** (``Dry Run`` / ``Live Update``),
and it defaults to ``Dry Run``: Execute therefore stays safe until the mode is
switched, exactly as the former Dry Run checkbox did.  The ``dry_run``
BooleanVar is derived from the mode in one direction only, so a preset or the
driver's ``--live``/``--dry`` flag moves the mode and the derived flag follows.

Worker threads never touch a widget.  The engine's progress callback runs on
the scan thread, so every message is posted to a ``SimpleQueue`` and a poller
the Tk thread owns drains it (``root.after`` from a raw ``threading.Thread``
raises ``RuntimeError: main thread is not in main loop`` — AGENTS.md, D136).

Changed in 1.0.1: accepts the driver's argv as kwargs and pre-fills the source,
destination, action and pattern widgets.
Changed in 1.0.1: fixed type annotation from tk.Event[ttk.Combobox] to
tk.Event for Python 3.11 compatibility (Event is not subscriptable in 3.11).

Changed in 2.4.3: writes a per-run report, ``reorganizer_dry_run_log.txt`` or
``reorganizer_sync_log.txt``, into the scanned Source Music Directory and
points ``_log_path`` at it — the shape BPM Analyzer and the shared analysis
bases use (header, one line per file, ``SUMMARY:`` block).  Until this change
the tool wrote no run record at all: per-file detail only reached
``logs/file_reorganizer.log``, so the Results tab's View Log had nothing to
open after a live copy.  The program log stays diagnostic.

Changed in 2.4.3: adopts ``SuiteApp`` (PLAN_2026-11-03_2.4.3_structure.md
WP-8).  The single-pane layout becomes the shell's Setup / Processing /
Results tabs, the Dry Run checkbox becomes the run-controls Mode, the preview
list becomes the shared Processing list and the completion modal becomes the
shared Results tab.  The driver handshake's ``--live``/``--start``/``--end``
flags, parsed but previously dropped, now reach the panel they belong to.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import filedialog, ttk
from typing import Any

from audio_suite_shared import styles, suite_config, ui_common
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.exceptions import (
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.ui_driver_controls import DriverControlsPanel

from .core.defaults import DEFAULT_SPECIFIC, DEFAULT_VARIOUS
from .core.engine import FileReorganizer, ReorganizerStats
from .utils import cli_args
from .utils.config import load_settings, save_settings

TOOL_ID = "file_reorganizer"

logger = logging.getLogger(__name__)

#: Run-report file prefix: ``<prefix>_dry_run_log.txt`` / ``<prefix>_sync_log.txt``.
_REPORT_PREFIX = "reorganizer"

#: The run-controls strip's two modes; ``Dry Run`` is the safe default.
DRY_RUN_MODE = "Dry Run"
LIVE_UPDATE_MODE = "Live Update"

#: How often the Tk-thread poller drains the worker queue, in milliseconds.
_POLL_MS = 50


@dataclass(frozen=True)
class _RunEvent:
    """One message a scan thread hands to the Tk thread.

    The worker only ever constructs these and puts them on the queue; the
    poller turns them into widget writes and dialogs on the Tk thread.

    Attributes:
        kind: ``"progress"``, ``"preview_done"``, ``"execute_done"`` or
            ``"error"``.
        path_info: The line the engine published for one file.
        stats: The engine's counters at that point.
        message: The user-facing text of a run failure.
    """

    kind: str
    path_info: str = ""
    stats: ReorganizerStats | None = None
    message: str = ""


class FileReorganizerApp(SuiteApp):
    """Tkinter GUI application for Tag-Based File Reorganizer."""

    _TOOL_ID = TOOL_ID

    #: Identity the shared shell reads (Help bar, window, log file).
    title = "Tag-Based File Reorganizer"
    window_key = "file_reorganizer_window"
    program_name = TOOL_ID
    guide_name = "File_Reorganizer_User_Guide.docx"
    completion_text = "Reorganization Complete!"

    def __init__(
        self,
        root: tk.Tk,
        *,
        directory: str = "",
        output_dir: str = "",
        action: str = "",
        specific_pattern: str = "",
        various_pattern: str = "",
        live_mode: bool = False,
        auto_start: bool = False,
        auto_end: bool = False,
        clear_logs: bool = False,
        parallel_run: bool = False,
    ) -> None:
        self.root = root

        # ── Tk variables (created before the shell builds the tabs) ───────────
        self.source_dir = tk.StringVar()
        self.dest_dir = tk.StringVar()
        self.action = tk.StringVar(value="copy")
        self.run_mode = tk.StringVar(
            value=LIVE_UPDATE_MODE if live_mode else DRY_RUN_MODE
        )
        # Derived, never written directly: the strip's Mode is the control.
        self.dry_run = tk.BooleanVar(value=not live_mode)
        self.run_mode.trace_add("write", self._on_mode_changed)

        # Driver-mirrored run controls (Clear Logs / Parallel stay display-only)
        self.auto_start_var = tk.BooleanVar(value=auto_start)
        self.auto_end_var = tk.BooleanVar(value=auto_end)
        self.clear_logs_var = tk.BooleanVar(value=clear_logs)
        self.parallel_var = tk.BooleanVar(value=parallel_run)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        self.running = tk.BooleanVar(value=False)
        self.stats = ReorganizerStats()
        self.controls_panel: DriverControlsPanel | None = None
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Callable[[list[str]], None] | None = None
        self._reorganizer: FileReorganizer | None = None
        self._thread: threading.Thread | None = None
        self._events: queue.SimpleQueue[_RunEvent] = queue.SimpleQueue()
        self._poll_id: str = ""
        self._closing = False
        self._run_started = 0.0
        self._log_entries: list[str] = []

        # ── Build the shared shell (Help bar, notebook, Processing, Results) ──
        super().__init__(root)

        self._load_settings()
        self._seed_source_from_last_directory()
        self._apply_cli_args(
            directory=directory,
            output_dir=output_dir,
            action=action,
            specific_pattern=specific_pattern,
            various_pattern=various_pattern,
        )
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit this tool's Setup tab; the shared shell owns the notebook.

        Args:
            parent: The Setup tab frame the shell created.
        """
        frame = tk.Frame(parent, padx=30, pady=20, bg=styles.BG_WHITE)
        frame.pack(expand=True, fill="both")

        tk.Label(
            frame,
            text=self.title,
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=(0, 20))

        # ── Run controls (source directory + Mode / Auto Start / Auto End) ────
        panel = DriverControlsPanel(
            frame,
            source_var=self.source_dir,
            mode_var=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse_source,
            modes=(DRY_RUN_MODE, LIVE_UPDATE_MODE),
        )
        panel.pack(fill="x", pady=(0, 15))
        panel.set_driven(self._launched_from_driver)
        self.controls_panel = panel

        # ── Presets ───────────────────────────────────────────────────────────
        preset_row = tk.Frame(frame, bg=styles.BG_WHITE)
        preset_row.pack(fill="x", pady=(0, 15), anchor="w")
        tk.Label(
            preset_row,
            text="Presets:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(0, 5))

        combo = ttk.Combobox(
            preset_row,
            state="readonly",
            font=styles.FONT_BODY,
            width=28,
        )
        combo["values"] = suite_config.list_presets(self._TOOL_ID) or []
        combo.pack(side=tk.LEFT, padx=(0, 5))
        combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        self._preset_combo = combo

        def _refresh_preset_list(names: list[str]) -> None:
            combo["values"] = names

        self._refresh_preset_list = _refresh_preset_list

        tk.Button(
            preset_row,
            text="Save",
            command=self._save_preset_dialog,
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BODY,
            padx=8,
        ).pack(side=tk.LEFT, padx=(0, 3))
        tk.Button(
            preset_row,
            text="Delete",
            command=self._delete_preset_action,
            bg="#cc5555",
            fg="white",
            font=styles.FONT_BODY,
            padx=8,
        ).pack(side=tk.LEFT)

        # ── Destination ───────────────────────────────────────────────────────
        dest_frame = tk.Frame(frame, bg=styles.BG_WHITE)
        dest_frame.pack(fill="x", pady=5)
        ui_common.path_row(
            dest_frame, "Destination Directory:", self.dest_dir, self._browse_dest
        )

        # ── Action ────────────────────────────────────────────────────────────
        action_frame = tk.LabelFrame(
            frame,
            text=" Action ",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            padx=15,
            pady=10,
        )
        action_frame.pack(fill="x", pady=(15, 5))

        for text, value in (("Copy", "copy"), ("Move", "move")):
            tk.Radiobutton(
                action_frame,
                text=text,
                variable=self.action,
                value=value,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                activebackground=styles.BG_WHITE,
                activeforeground=styles.FG_MAIN,
                font=styles.FONT_BODY,
            ).pack(side=tk.LEFT, padx=(0, 15))

        tk.Label(
            action_frame,
            text="(Dry Run previews; switch Mode to Live Update to write)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT)

        # ── Pattern templates ─────────────────────────────────────────────────
        pattern_frame = tk.LabelFrame(
            frame,
            text=" Pattern Templates ",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            padx=15,
            pady=10,
        )
        pattern_frame.pack(fill="both", expand=True, pady=(10, 5))

        pattern_notebook = ttk.Notebook(pattern_frame)
        pattern_notebook.pack(fill="both", expand=True)

        specific_frame = tk.Frame(pattern_notebook, bg=styles.BG_WHITE)
        various_frame = tk.Frame(pattern_notebook, bg=styles.BG_WHITE)
        pattern_notebook.add(specific_frame, text="  Specific Artists  ")
        pattern_notebook.add(various_frame, text="  Various Artists  ")

        self.specific_text = self._build_pattern_editor(
            specific_frame, DEFAULT_SPECIFIC
        )
        self.various_text = self._build_pattern_editor(various_frame, DEFAULT_VARIOUS)

        # ── Buttons ───────────────────────────────────────────────────────────
        btn_row = tk.Frame(frame, bg=styles.BG_WHITE)
        btn_row.pack(fill="x", pady=(0, 5))

        self.preview_btn = tk.Button(
            btn_row,
            text="Preview",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self._preview,
        )
        self.preview_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.execute_btn = tk.Button(
            btn_row,
            text="Execute",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self._execute,
            state=tk.DISABLED,
        )
        self.execute_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_btn = tk.Button(
            btn_row,
            text="Stop",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self._stop,
            state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT)

    @staticmethod
    def _build_pattern_editor(parent: tk.Frame, template: str) -> tk.Text:
        """Create one pattern template editor.

        Args:
            parent: The pattern sub-tab frame.
            template: Initial template text.

        Returns:
            The text widget, packed and pre-filled.
        """
        editor = tk.Text(
            parent,
            height=10,
            width=90,
            wrap=tk.NONE,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
            highlightthickness=1,
            highlightcolor=styles.FG_SUB,
            relief=tk.SOLID,
            borderwidth=1,
        )
        editor.pack(fill="both", expand=True, padx=5, pady=5)
        editor.insert("1.0", template)
        return editor

    # ── Mode ──────────────────────────────────────────────────────────────────

    def _on_mode_changed(self, *_args: str) -> None:
        """Mirror the strip's Mode onto the derived ``dry_run`` flag."""
        self.dry_run.set(self.run_mode.get() == DRY_RUN_MODE)

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        """Collect the persisted settings for a preset or config save."""
        specific, various = self._sync_patterns()
        return {
            "source_dir": self.source_dir.get(),
            "dest_dir": self.dest_dir.get(),
            "action": self.action.get(),
            "dry_run": self.dry_run.get(),
            "run_mode": self.run_mode.get(),
            "specific_pattern": specific,
            "various_pattern": various,
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        """Apply a stored preset to the widgets."""
        if "source_dir" in settings:
            self.source_dir.set(settings["source_dir"])
        if "dest_dir" in settings:
            self.dest_dir.set(settings["dest_dir"])
        if "action" in settings:
            self.action.set(settings["action"])
        # Older presets stored only ``dry_run``; newer ones store the mode.
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])
        elif "dry_run" in settings:
            self.run_mode.set(DRY_RUN_MODE if settings["dry_run"] else LIVE_UPDATE_MODE)
        if "specific_pattern" in settings:
            self.specific_text.delete("1.0", tk.END)
            self.specific_text.insert("1.0", settings["specific_pattern"])
        if "various_pattern" in settings:
            self.various_text.delete("1.0", tk.END)
            self.various_text.insert("1.0", settings["various_pattern"])

    def _on_preset_selected(self, _event: tk.Event | None = None) -> None:
        """Load and apply the preset picked in the combobox."""
        combo = self._preset_combo
        if combo is None:
            return
        name = combo.get()
        if not name:
            return
        settings = suite_config.load_preset(self._TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        """Persist the current settings under *name* and refresh the list."""
        suite_config.save_preset(self._TOOL_ID, name, self._collect_settings())
        self._refresh_presets()

    def _delete_preset(self, name: str) -> None:
        """Delete the named preset and refresh the list."""
        suite_config.delete_preset(self._TOOL_ID, name)
        self._refresh_presets()

    def _refresh_presets(self) -> None:
        """Reload the preset names from the shared config."""
        if self._refresh_preset_list is not None:
            self._refresh_preset_list(suite_config.list_presets(self._TOOL_ID))

    def _save_preset_dialog(self) -> None:
        """Open the shared Save Preset dialog."""
        combo = self._preset_combo
        if combo is None:
            return
        ui_common.save_preset_dialog(combo, self._save_current_as_preset)

    def _delete_preset_action(self) -> None:
        """Confirm then delete the selected preset."""
        combo = self._preset_combo
        if combo is None:
            return
        ui_common.delete_preset_action(combo, self._delete_preset)

    # ── Source/destination seeding ────────────────────────────────────────────

    def _seed_source_from_last_directory(self) -> None:
        """Set the source directory from the suite-wide last-used folder.

        The source field always follows ``suite_config.load_last_directory``
        at launch: the Master Driver saves its selected folder there before
        launching standalone tools, and this tool updates it whenever a new
        source is picked.  It therefore wins over any locally persisted
        settings, matching sibling-tool behaviour.
        """
        last = suite_config.load_last_directory()
        if last:
            self.source_dir.set(last)

    def _apply_cli_args(
        self,
        *,
        directory: str,
        output_dir: str,
        action: str,
        specific_pattern: str,
        various_pattern: str,
    ) -> None:
        """Pre-fill widgets from the Master Driver / CLI arguments.

        The driver's source directory wins over the suite-wide last-used
        directory seeded just before this call, matching sibling-tool
        behaviour.

        Args:
            directory: Source music directory from argv[1].
            output_dir: Destination directory from ``--output-dir``.
            action: ``copy`` or ``move`` from ``--action``.
            specific_pattern: Pattern template from ``--specific-pattern``.
            various_pattern: Pattern template from ``--various-pattern``.
        """
        if directory:
            self.source_dir.set(directory)
        if output_dir:
            self.dest_dir.set(output_dir)
        if action in ("copy", "move"):
            self.action.set(action)
        if specific_pattern:
            self.specific_text.delete("1.0", tk.END)
            self.specific_text.insert("1.0", specific_pattern)
        if various_pattern:
            self.various_text.delete("1.0", tk.END)
            self.various_text.insert("1.0", various_pattern)

    def _browse_source(self) -> None:
        """Pick the source directory and record it as the suite last-used one."""
        d = filedialog.askdirectory(title="Select Source Directory")
        if d:
            self.source_dir.set(d)
            suite_config.save_last_directory(d)

    def _browse_dest(self) -> None:
        """Pick the destination directory."""
        d = filedialog.askdirectory(title="Select Destination Directory")
        if d:
            self.dest_dir.set(d)

    def _sync_patterns(self) -> tuple[str, str]:
        """Return both pattern editors' current text."""
        return self.specific_text.get("1.0", "end-1c"), self.various_text.get(
            "1.0", "end-1c"
        )

    @handle_audio_errors(reraise=False, context="file_reorganizer_save_settings")
    def _save_settings(self) -> None:
        """Persist destination, action and patterns to the shared config."""
        save_settings(
            dest_dir=self.dest_dir.get(),
            action=self.action.get(),
            specific_pattern=self.specific_text.get("1.0", "end-1c"),
            various_pattern=self.various_text.get("1.0", "end-1c"),
        )

    @handle_audio_errors(reraise=False, context="file_reorganizer_load_settings")
    def _load_settings(self) -> None:
        """Restore destination, action and patterns from the shared config."""
        settings = load_settings()
        self.dest_dir.set(settings["dest_dir"])
        self.action.set(settings["action"])
        specific = settings["specific_pattern"]
        various = settings["various_pattern"]
        self.specific_text.delete("1.0", tk.END)
        self.specific_text.insert("1.0", specific)
        self.various_text.delete("1.0", tk.END)
        self.various_text.insert("1.0", various)

    # ── Preview ───────────────────────────────────────────────────────────────

    def _preview(self) -> None:
        """Validate the inputs and start a dry-run scan on a worker thread."""
        src = self.source_dir.get().strip()
        dst = self.dest_dir.get().strip()
        if not src or not os.path.isdir(src):
            ui_common.show_message(
                self.root, "No Source", "Please select a valid source directory."
            )
            return
        if not dst:
            ui_common.show_message(
                self.root, "No Destination", "Please select a destination directory."
            )
            return

        specific_pat, various_pat = self._sync_patterns()
        self._begin_run("Previewing...", dry_run=True)
        self.preview_btn.config(state=tk.DISABLED)
        self._save_settings()

        self._thread = threading.Thread(
            target=self._preview_thread,
            args=(src, dst, specific_pat, various_pat),
            daemon=True,
        )
        self._thread.start()
        self._start_polling()

    def _preview_thread(
        self, src: str, dst: str, specific_pat: str, various_pat: str
    ) -> None:
        """Run the dry-run scan off the Tk thread and post its events."""
        try:
            self._preview_run(src, dst, specific_pat, various_pat)
        except AudioSuiteError as exc:
            self._events.put(
                _RunEvent(kind="error", message=_failure_message("Preview", exc))
            )
        finally:
            self._events.put(_RunEvent(kind="preview_done"))

    @handle_audio_errors(reraise=True, context="file_reorganizer_preview")
    def _preview_run(
        self, src: str, dst: str, specific_pat: str, various_pat: str
    ) -> None:
        """Scan and resolve destinations without writing anything."""
        reorganizer = FileReorganizer(
            specific_pat, various_pat, dst, action="copy", dry_run=True
        )
        self._reorganizer = reorganizer
        reorganizer.run(src, progress_callback=self._on_progress_preview)

    def _on_progress_preview(self, path_info: str, stats: ReorganizerStats) -> None:
        """Post one preview tick; called on the scan thread."""
        self._events.put(_RunEvent(kind="progress", path_info=path_info, stats=stats))

    # ── Execute ───────────────────────────────────────────────────────────────

    def _execute(self) -> None:
        """Validate the inputs and start the copy/move run on a worker thread."""
        src = self.source_dir.get().strip()
        dst = self.dest_dir.get().strip()
        if not src or not os.path.isdir(src):
            ui_common.show_message(
                self.root, "No Source", "Please select a valid source directory."
            )
            return
        if not dst:
            ui_common.show_message(
                self.root, "No Destination", "Please select a destination directory."
            )
            return

        specific_pat, various_pat = self._sync_patterns()
        self.running.set(True)
        self._begin_run("Executing...", dry_run=bool(self.dry_run.get()))
        self.preview_btn.config(state=tk.DISABLED)
        self.execute_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self._save_settings()

        self._thread = threading.Thread(
            target=self._execute_thread,
            args=(src, dst, specific_pat, various_pat),
            daemon=True,
        )
        self._thread.start()
        self._start_polling()

    def _execute_thread(
        self, src: str, dst: str, specific_pat: str, various_pat: str
    ) -> None:
        """Run the copy/move off the Tk thread and post its events."""
        try:
            self._execute_run(src, dst, specific_pat, various_pat)
        except AudioSuiteError as exc:
            self._events.put(
                _RunEvent(kind="error", message=_failure_message("Execute", exc))
            )
        finally:
            self._events.put(_RunEvent(kind="execute_done"))

    @handle_audio_errors(reraise=True, context="file_reorganizer_execute")
    def _execute_run(
        self, src: str, dst: str, specific_pat: str, various_pat: str
    ) -> None:
        """Copy or move every matched file inside the undo batch."""
        dry = self.dry_run.get()
        reorganizer = FileReorganizer(
            specific_pat, various_pat, dst, action=self.action.get(), dry_run=dry
        )
        self._reorganizer = reorganizer
        with active_batch("file_reorganizer", "file_reorg"):
            reorganizer.run(src, progress_callback=self._on_progress_execute)

    def _on_progress_execute(self, path_info: str, stats: ReorganizerStats) -> None:
        """Post one execute tick; called on the scan thread."""
        self._events.put(_RunEvent(kind="progress", path_info=path_info, stats=stats))

    # ── Worker → Tk handoff ───────────────────────────────────────────────────

    def _start_polling(self) -> None:
        """Begin draining the worker queue on the Tk thread."""
        if self._poll_id or self._closing:
            return
        self._poll_id = self.root.after(_POLL_MS, self._poll_events)

    def _poll_events(self) -> None:
        """Apply every queued worker event, then re-arm while the run lives."""
        self._poll_id = ""
        while True:
            try:
                event = self._events.get_nowait()
            except queue.Empty:
                break
            self._handle_event(event)
        if self._thread is not None and self._thread.is_alive():
            self._poll_id = self.root.after(_POLL_MS, self._poll_events)

    def _handle_event(self, event: _RunEvent) -> None:
        """Turn one queued event into widget writes (Tk thread only)."""
        if event.kind == "progress":
            if event.stats is not None:
                self._update_ui(event.path_info, event.stats)
        elif event.kind == "preview_done":
            self._preview_finished()
        elif event.kind == "execute_done":
            self._finish()
        else:
            self.preview_btn.config(state=tk.NORMAL)
            self.execute_btn.config(state=tk.NORMAL)
            self._on_error(event.message)

    def _begin_run(self, status: str, *, dry_run: bool) -> None:
        """Clear the Processing tab and point ``_log_path`` at this run's report.

        A dry run and a live run write different reports, next to the files
        that were scanned: ``reorganizer_dry_run_log.txt`` and
        ``reorganizer_sync_log.txt``.  That is the suite's convention (BPM
        Analyzer, ``AnalysisAppBase``/``ToolAppBase``), and it is why ``_log_path``
        is empty until a run starts rather than aimed at the diagnostic log.

        Args:
            status: The Processing tab's opening status line.
            dry_run: Whether this run only plans paths.
        """
        self._log_entries = []
        self._log_path = os.path.join(
            self.source_dir.get().strip(),
            f"{_REPORT_PREFIX}_{'dry_run' if dry_run else 'sync'}_log.txt",
        )
        self._run_started = time.monotonic()
        self._reset_processing_tab(status)

    def _write_run_log(self, *, dry_run: bool) -> None:
        """Write this run's report: settings, one line per file, then the summary.

        Mirrors the suite's report shape — ``<TOOL> REPORT``, ``Mode:``, the
        run's settings, a rule, the per-file entries and a ``SUMMARY:`` block —
        so a reorganiser report reads like every other tool's.  A failed write
        is logged rather than raised: the run has already happened.

        Args:
            dry_run: Whether the run planned paths only.
        """
        if not self._log_path:
            return
        specific, various = self._sync_patterns()
        elapsed = max(0.0, time.monotonic() - self._run_started)
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        lines = [
            "FILE REORGANIZER REPORT\n",
            f"Mode: {'DRY RUN' if dry_run else 'LIVE UPDATE'}\n",
            f"Source: {self.source_dir.get().strip()}\n",
            f"Destination: {self.dest_dir.get().strip()}\n",
            f"Action: {self.action.get().upper()}\n",
            f"Specific Pattern: {' '.join(specific.split())}\n",
            f"Various Pattern: {' '.join(various.split())}\n",
            "=" * 60 + "\n",
            *self._log_entries,
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {self.stats.files_scanned}\n",
            f"Processed: {self.stats.files_processed}\n",
            f"Skipped: {self.stats.files_skipped}\n",
            f"Errors: {self.stats.errors}\n",
            f"Time: {minutes:02d}:{seconds:02d}\n",
        ]
        try:
            with open(self._log_path, "w", encoding="utf-8") as report:
                report.writelines(lines)
            logger.info("Run report written to '%s'", self._log_path)
        except OSError as exc:
            logger.error(
                "Could not write the run report '%s': %s",
                self._log_path,
                exc,
                exc_info=True,
            )

    def _reset_processing_tab(self, status: str) -> None:
        """Clear the Processing tab for a new run."""
        self.overall_status.set(status)
        self.stats_label.config(text="Processed: 0 | Skipped: 0 | Errors: 0")
        self.progress["maximum"] = 1
        self.progress["value"] = 0
        self.file_listbox.delete(0, tk.END)

    def _update_ui(self, path_info: str, stats: ReorganizerStats) -> None:
        """Render one progress tick on the Processing tab."""
        self.stats = stats
        self.overall_status.set(f"Current File: {os.path.basename(path_info)}")
        self.stats_label.config(
            text=(
                f"Scanned: {stats.files_scanned} | "
                f"Processed: {stats.files_processed} | "
                f"Skipped: {stats.files_skipped} | "
                f"Errors: {stats.errors}"
            )
        )
        self.progress["maximum"] = max(stats.files_scanned, 1)
        self.progress["value"] = stats.files_processed
        self._log_entries.append(f"{path_info}\n")
        self.file_listbox.insert(tk.END, path_info)
        self.file_listbox.see(tk.END)

    def _preview_finished(self) -> None:
        """Write the dry-run report and restore the buttons."""
        self._write_run_log(dry_run=True)
        self.overall_status.set("Preview complete")
        self.preview_btn.config(state=tk.NORMAL)
        self.execute_btn.config(state=tk.NORMAL)
        self._thread = None

    # ── Stop / close ──────────────────────────────────────────────────────────

    def _stop(self) -> None:
        """Request that the active scan stop at the next file boundary."""
        self.overall_status.set("Stopping...")
        if self._reorganizer is not None:
            self._reorganizer.stop()

    def _on_close(self) -> None:
        """Cancel the poller, persist settings and shut the engine down."""
        self._closing = True
        if self._poll_id:
            try:
                self.root.after_cancel(self._poll_id)
            except tk.TclError:  # pragma: no cover - root already gone
                pass
            self._poll_id = ""
        self._save_settings()
        if self._reorganizer is not None:
            self._reorganizer.stop()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.root.destroy()

    def _finish(self) -> None:
        """Switch the window to the Results tab after an execute run."""
        self.running.set(False)
        self.preview_btn.config(state=tk.NORMAL)
        self.execute_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.overall_status.set("Complete")
        self._write_run_log(dry_run=bool(self.dry_run.get()))
        self.summary_label.config(text=self._summary_text())
        self.render_completion(
            duration_secs=time.monotonic() - self._run_started,
            output_dir=self.dest_dir.get().strip(),
        )
        self._thread = None

    def _summary_text(self) -> str:
        """The four counters as the Results tab's summary."""
        return (
            f"Scanned: {self.stats.files_scanned}\n"
            f"Processed: {self.stats.files_processed}\n"
            f"Skipped: {self.stats.files_skipped}\n"
            f"Errors: {self.stats.errors}"
        )

    def run(self) -> None:
        """Enter the Tk main loop."""
        self.root.mainloop()


def _failure_message(stage: str, exc: AudioSuiteError) -> str:
    """Map a run failure to the user-facing sentence for *stage*.

    Args:
        stage: ``"Preview"`` or ``"Execute"``.
        exc: The error the worker caught.

    Returns:
        The shared user-facing message, prefixed with the stage that failed.
    """
    return f"{stage} failed. {user_message_for(map_to_audio_error(exc))}"


def main() -> None:
    """Parse the launcher arguments and open the window."""
    args = parse_cli_args(cli_args.parse)
    root = tk.Tk()
    app = FileReorganizerApp(
        root,
        directory=args.folder_path,
        output_dir=args.output_dir,
        action=args.action,
        specific_pattern=args.specific_pattern,
        various_pattern=args.various_pattern,
        live_mode=args.live_mode,
        auto_start=args.auto_start,
        auto_end=args.auto_end,
        clear_logs=args.clear_logs,
        parallel_run=args.parallel_run,
    )
    app.run()
