"""
suite_app.py — The one window shell for the suite's batch-transformer tools.

A batch transformer is a tool with a source folder, an output target, settings
staged in a Setup tab and a run it reports on a Results tab.  Eighteen of them
hand-built the same window around those pieces: a Help bar, a notebook, a
Processing tab with a progress bar, a stats line, a worker grid and a file list,
a Results tab with a completion heading and two buttons, and the three
callbacks the processor drives.  ``SuiteApp`` composes that window once from the
builders that already exist (``ui_common.build_processing_tab`` and
``ui_common.build_results_tab``), so a tool supplies its settings panel and its
run, and nothing about the frame around them.

What the shell owns:

- bootstrap (window geometry, theme, logger) through ``bootstrap_tool_app``;
- the Help button and the notebook;
- the Processing tab (progress, stats, worker grid, file list) and the Results
  tab (completion, summary and time labels, View Log, Open Folder);
- the progress and completion tails, ``_on_error``, and the help/log/folder
  helpers, all obeying the GUI callback contract in ``AGENTS.md``;
- the worker hand-off: the run's queue, its daemon thread and the
  ``event_pump.pump_events`` poller, so a tool supplies only its
  ``_dispatch_ui_message``;
- the run report: one writer for the ``SUMMARY:`` block every tool's View Log
  reads, so a tool supplies its header, its per-file lines and its own rows;
- the run controls a preset-carrying window shares: its
  ``audio_suite_config`` keys, its preset trio, the driver's argv mirror and
  the start every analysis window takes, so the window supplies its parser
  and its run and nothing about the panel around them;
- the Auto End marker a finished run appends to its report before the window
  closes itself.

What a tool supplies:

- ``title``, ``window_key``, ``program_name``, ``guide_name`` and
  ``completion_text`` as class attributes;
- ``slot_vars`` (optional) *before* calling ``super().__init__``: the Processing
  tab renders its worker grid from that list when it is present;
- ``_build_setup_tab(parent)``, the one layout hook.  A tool that needs an extra
  tab overrides ``_tab_specs`` and extends ``tab_labels`` in lockstep;
- ``_dispatch_ui_message(message)``, the rendering of one message the run's
  thread queued.  ``_start_worker`` starts the run and the poller that feeds it.

A tool keeps a payload handler when the payload is its own.  The shell offers
``render_progress`` / ``render_completion`` for the universal widgets and a
tool's handler calls them after doing its own work.  They are helpers rather
than overridable callbacks on purpose: a tool's completion payload is wider
than the universal one, and an override that *requires* those extra fields is
an LSP break (mypy's ``[override]``) — silencing it with ``# type: ignore`` is
what this repository forbids.  ``music_format_converter`` is the worked
example.

Changed in 2.4.3: adds SuiteApp (PLAN_2026-11-03_2.4.3_structure.md, WP-8).
Changed in 2.9.0: the progress-tick writes are the shared mixin helper (C1).
Changed in 2.9.0: the shell publishes the Processing tab's panel as
``processing_panel``, so a tool that adds a control of its own beside the
shared ones names that parent instead of reaching through ``progress.master``
(C1 stage 2).
Changed in 2.9.0: ``processing_stats_text`` lets an adopter keep its own stats
wording (Genre Sync counts updated/skipped/errors) instead of the shell's
starting line (C1 stage 2).
Changed in 2.9.0: ``window_size`` and ``apply_ttk_styles`` carry the two
``bootstrap_tool_app`` arguments an adopter set for itself (ASX Playlist
Extractor opens at 700 px and styles its own ttk widgets), so joining the shell
does not resize or restyle its window (C1 stage 2).
Changed in 2.9.0: the shell keeps the Help bar's frame as ``help_frame``, so a
test that builds a real window can destroy the two widgets ``_build_ui`` puts on
the root (the bar and the notebook) and leave the shared root empty.
Changed in 2.9.0: ``result_extra_labels`` lets an adopter keep a label of its
own on the Results tab (the fingerprinter's ISRC submission line), built by the
shared builder and published on the instance under its name (C1 stage 2).
Changed in 2.9.0: the shell owns the worker hand-off.  ``_start_worker`` builds
the run's queue and starts its daemon thread, and ``_poll_ui_updates`` drains it
through ``event_pump.pump_events``; a tool supplies only
``_dispatch_ui_message``.  The four queue-driven adopters had written that
wrapper four times, byte for byte (C1 stage 2, D31).
Changed in 2.9.0: the shell owns the run report.  ``_write_run_report_standard``
writes the header, the per-file lines and the ``SUMMARY:`` footer into
``_log_path``; a tool supplies its own rows, and a failed write is logged rather
than raised off the worker thread.  Three adopters had carried the same block
(C1 stage 2, D32).
Changed in 2.9.0: the writer creates the report's folder when it is missing,
so a tool that writes into a fresh output directory still finishes with a report
View Log can open rather than a logged failure (D33).
Changed in 2.9.0: the report's ``SUMMARY:`` footer is
``run_report.summary_lines``, shared with the analysis scaffold instead
of built in each writer (D35).
Changed in 2.9.0: ``audition_row`` gives the shared Results tab the
before/after audition row and binds ``AuditionMixin``, so an in-place repair
tool's last capability is the shell's instead of a base class of its own
(C1 stage 2, D34).
Changed in 2.9.0: ``SKIPPED_LABEL`` names the report's skipped count, so a
tool whose skips mean something specific (Key Detector's already-tagged
files) keeps its own word instead of the shell's fallback (C1 stage 3).
Changed in 2.9.0: the shell owns the run controls a preset-carrying window
needs - ``_setting_key``, ``_collect_settings``/``_apply_preset``, the preset
trio, ``_mirror_cli_args`` and ``start_processing`` - so Key Detector and
Mood Analyzer stop carrying them twice, byte for byte, and the fourteen
other preset-carrying windows can drop their copies onto the same methods
without changing a literal (D56).
Changed in 2.9.0: ``close_for_auto_end`` gives the Auto End marker and its
close delay one home; the pair had become the marker's sixth and seventh
copies (D56).
Changed in 2.9.0: ``PRESET_ALIASES`` and ``PRESET_KEY_PREFIX`` let one preset
trio serve every preset-carrying window: a window whose saved key is not its
variable's name maps the two, and a window whose presets still live under the
older ``<prefix>_preset_<name>`` keys keeps reading them, so no adoption
renames a preset a user already saved (D58).

"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from collections.abc import Callable
from pathlib import Path
from queue import SimpleQueue
from tkinter import messagebox, ttk
from typing import Any, ClassVar

from . import styles, suite_config
from .app_bootstrap import bootstrap_tool_app
from .event_pump import pump_events
from .exceptions import map_to_audio_error
from .run_report import summary_lines
from .ui_audition import AuditionMixin
from .ui_common import (
    build_processing_tab,
    build_results_tab,
    cap_typed_workers,
)
from .ui_helpers import UIHelperMixin
from .ui_presets import (
    delete_tool_preset,
    load_preset_names,
    load_tool_preset,
    save_tool_preset,
)

logger = logging.getLogger(f"audio_suite.{__name__}")

#: The line a run appends to its report when the window closes itself.
_AUTO_END_MARKER = "\n[Auto End enabled - closing in 2 seconds...]\n"
#: How long a finished window stays readable before Auto End closes it.
_AUTO_END_CLOSE_MS = 2000

#: Emits one tab's widgets into the frame the shell created for it.
TabBuilder = Callable[[tk.Frame], Any]


class SuiteApp(UIHelperMixin, AuditionMixin):
    """One window shell for a batch-transformer tool.

    Subclasses set the identity attributes, finish any state a tab reads (Tk
    variables, worker slots) and then call ``super().__init__(root)``, which
    bootstraps the window and builds the notebook.  See the module docstring
    for the split of responsibilities.

    Attributes:
        title: Window title, and the heading the Setup tab shows.
        window_key: ``platform_utils.setup_window`` key for saved geometry.
        program_name: Program name for this tool's ``logs/<program>.log``.
        guide_name: Help-guide filename the Help button opens.
        completion_text: Heading the Results tab shows when a run finishes.
        tab_labels: Notebook labels in order; ``_tab_specs`` supplies a builder
            for each one.
        notebook: The tool's notebook (set by the shell).
        setup_frame / processing_frame / results_frame: The shell-built tab
            frames, in notebook order.
        progress, stats_label, file_listbox, overall_status: Processing-tab
            widgets.
        processing_panel: The frame those Processing-tab widgets are packed
            into; a tool that adds a control of its own beside them (Album Art
            Sync's Cancel button) packs it here.
        processing_stats_text: The stats line's starting text; a tool whose
            counters differ from the default names its own.
        completion_label, summary_label, time_label: Results-tab widgets.
        start_btn: The tool's start button, once its Setup tab has built it.
        controls_panel: The Setup tab's run-controls strip, when the tool
            embeds one.
        result_extra_labels: Extra Results-tab labels the tool drives; the
            shell builds each one and publishes it on the instance under its
            name.
        audition_row: Whether the shared Results tab carries the before/after
            audition row; the shell binds the shared mixin when it does.
    """

    #: Window title, and the heading the Setup tab shows.  Shown once.
    title: str = ""
    #: ``platform_utils.setup_window`` key for saved geometry/position.
    window_key: str = ""
    #: Program name for this tool's ``logs/<program>.log``.
    program_name: str = ""
    #: Help-guide filename the Help button opens.
    guide_name: str = ""
    #: Completion heading the Results tab shows.
    completion_text: str = "Complete!"
    #: Notebook labels, in order.  ``_tab_specs`` supplies one builder each.
    tab_labels: tuple[str, ...] = (" 1. Setup ", " 2. Processing ", " 3. Results ")
    #: The Processing tab's starting stats line, until the run reports its own.
    processing_stats_text: str = "Processed: 0 | Skipped: 0 | Errors: 0"
    #: Default window size, until a saved geometry from ``window_key`` wins.
    window_size: tuple[int, int] = (850, 950)
    #: Whether ``bootstrap_tool_app`` applies the suite's ttk styles.  An
    #: adopter that styles its own ttk widgets sets this ``False``.
    apply_ttk_styles: bool = True
    #: Extra Results-tab labels this tool drives, below the summary line.
    result_extra_labels: tuple[str, ...] = ()
    #: Whether the shared Results tab carries the before/after audition row.
    #: An in-place tool sets it, so Play Original has the snapshot the mixin
    #: captured before the run and Play Result the file it rewrote.
    audition_row: bool = False
    #: The run report's label for its handled count.  A tool whose runs count
    #: something else (``Files read``, ``Files scanned``) names its own.
    TAGGED_LABEL: str = "Tagged"
    #: The run report's label for its skipped count.  A tool whose skips mean
    #: something specific (Key Detector's already-tagged files) names its own.
    SKIPPED_LABEL: str = "Skipped"
    #: Prefix of this tool's ``audio_suite_config.json`` keys and of its
    #: report file names (``key_parallel_mode``, ``key_dry_run_log.txt``).
    SETTINGS_PREFIX: ClassVar[str] = ""
    #: The status line a run shows while it works.
    STARTING_STATUS: ClassVar[str] = "Processing..."
    #: The settings a preset carries, by the name of the Tk variable holding
    #: each one.  A tool with other settings overrides ``_collect_settings``
    #: and ``_apply_preset``, which one loop over this tuple implements.
    PRESET_FIELDS: ClassVar[tuple[str, ...]] = (
        "folder_path",
        "run_mode",
        "analysis_duration",
        "parallel_mode",
        "max_workers",
    )
    #: The older per-tool preset store's prefix (``bpm`` → ``bpm_preset_<name>``).
    #: Empty means this window's presets live in the shared ``presets`` block.
    PRESET_KEY_PREFIX: ClassVar[str] = ""
    #: Stored preset key -> Tk variable name, for a window whose saved key is
    #: not the variable's own name (``{"execution_mode": "run_mode"}``).
    PRESET_ALIASES: ClassVar[dict[str, str]] = {}
    #: Set from argv by a window that arms its Setup controls for a driver
    #: launch; the default keeps an ``object.__new__`` test shell on the
    #: interactive (modal-warning) path.
    _launched_from_driver: bool = False
    #: The Setup tab's run controls, set in the tool's ``__init__``.
    folder_path: tk.StringVar
    run_mode: tk.StringVar
    analysis_duration: tk.IntVar
    parallel_mode: tk.BooleanVar
    max_workers: tk.IntVar
    auto_start_var: tk.BooleanVar
    auto_end_var: tk.BooleanVar
    clear_logs_var: tk.BooleanVar
    parallel_var: tk.BooleanVar
    #: The driver's Auto End flag, mirrored from argv by ``_mirror_cli_args``.
    auto_end: bool = False
    #: The tool's start button, published by its Setup builder.
    start_btn: tk.Button
    #: The Setup tab's preset-combo refresher, published by that builder.
    _refresh_preset_list: Callable[[list[str]], None] | None = None

    #: Messages the run's thread queues for the Tk poller; built per run by
    #: ``_start_worker``.
    _ui_updates: SimpleQueue[tuple[Any, ...]]
    #: The run's thread; the poller stops when it ends.
    _run_thread: threading.Thread | None = None

    def __init__(self, root: tk.Tk) -> None:
        """Bootstrap the window and build the shell's notebook.

        Args:
            root: The Tk root the launcher created.
        """
        self.root = root
        width, height = self.window_size
        self.error_logger, _style = bootstrap_tool_app(
            root,
            self.title,
            self.window_key,
            self.program_name,
            width=width,
            height=height,
            apply_ttk_styles=self.apply_ttk_styles,
        )
        self._log_path: str = ""
        self._out_dir: str = ""
        self._build_ui()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Build the Help header, the notebook and every declared tab."""
        self.help_frame = tk.Frame(self.root, bg=styles.BG_LIGHT)
        self.help_frame.pack(fill="x", padx=10, pady=(10, 0))
        tk.Button(
            self.help_frame,
            text="Help",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BODY,
            padx=15,
            pady=3,
            command=self._open_help,
        ).pack(side=tk.RIGHT)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        frames: list[tk.Frame] = []
        for label, builder in self._tab_specs():
            frame = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
            self.notebook.add(frame, text=label)
            builder(frame)
            frames.append(frame)

        self.setup_frame = frames[0]
        self.processing_frame = frames[1]
        self.results_frame = frames[2]

    def _tab_specs(self) -> tuple[tuple[str, TabBuilder], ...]:
        """The tabs the shell builds, in notebook order.

        A tool with an extra tab overrides this and extends ``tab_labels`` in
        lockstep; the three entries here are the ones every batch transformer
        shares, and the last two are built by the shell.

        Returns:
            ``(label, builder)`` pairs, one per notebook tab.
        """
        return (
            (self.tab_labels[0], self._build_setup_tab),
            (self.tab_labels[1], self._build_processing_tab),
            (self.tab_labels[2], self._build_results_tab),
        )

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the tool's own settings controls into *parent*.

        Args:
            parent: The Setup tab frame the shell created.

        Raises:
            NotImplementedError: Always, in the base class: the settings panel
                is the one piece the shell cannot supply.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _build_setup_tab(parent)"
        )

    def _build_processing_tab(self, parent: tk.Frame) -> None:
        """Build the shared Processing tab, including the worker grid."""
        slot_vars: list[tk.StringVar] | None = getattr(self, "slot_vars", None)
        widgets = build_processing_tab(
            parent, slot_vars, stats_text=self.processing_stats_text
        )
        self.processing_panel: tk.Frame = widgets["panel"]
        self.overall_status: tk.StringVar = widgets["overall_status"]
        self.progress: ttk.Progressbar = widgets["progress"]
        self.stats_label: tk.Label = widgets["stats_label"]
        self.file_listbox: tk.Listbox = widgets["file_listbox"]

    def _build_results_tab(self, parent: tk.Frame) -> None:
        """Build the shared Results tab and wire its buttons."""
        widgets = build_results_tab(
            parent,
            self.completion_text,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
            extra_labels=list(self.result_extra_labels) or None,
            on_play_original=self._play_original if self.audition_row else None,
            on_play_result=self._play_result if self.audition_row else None,
        )
        self.completion_label: tk.Label = widgets["completion_label"]
        self.summary_label: tk.Label = widgets["summary_label"]
        self.time_label: tk.Label = widgets["time_label"]
        for name in self.result_extra_labels:
            setattr(self, name, widgets[name])
        if self.audition_row:
            self.setup_audition(widgets)

    # ── Shared helpers ────────────────────────────────────────────────────────

    def _open_help(self) -> None:
        """Open the guide named by ``guide_name``."""
        self._open_help_standard(self.guide_name)

    def _open_log(self) -> None:
        """Open this tool's processing log."""
        self._open_log_standard()

    def _open_folder(self) -> None:
        """Open the folder the last run wrote to."""
        self._open_folder_standard()

    # ── Run controls ──────────────────────────────────────────────────────────

    def _setting_key(self, name: str) -> str:
        """Return this tool's ``audio_suite_config.json`` key for *name*.

        Args:
            name: The setting's bare name (``parallel_mode``).

        Returns:
            ``<SETTINGS_PREFIX>_<name>``.
        """
        return f"{self.SETTINGS_PREFIX}_{name}"

    def _collect_settings(self) -> dict[str, Any]:
        """Snapshot the settings a preset carries.

        Returns:
            One entry per :attr:`PRESET_FIELDS` field, read from its Tk
            variable and keyed by :meth:`_preset_key`.
        """
        return {
            self._preset_key(name): getattr(self, name).get()
            for name in self.PRESET_FIELDS
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        """Restore the settings a preset carries.

        A name the preset does not carry keeps its current value, so an older
        preset still applies to a window that has gained a setting.

        Args:
            settings: The preset's stored mapping.
        """
        for name in self.PRESET_FIELDS:
            key = self._preset_key(name)
            if key in settings:
                getattr(self, name).set(settings[key])

    def _preset_tool_id(self) -> str:
        """Return the key this tool's presets live under.

        Adopters disagree on the shape of ``TOOL_ID`` - a class attribute
        for most, an assignment in ``__init__`` for the four grid tools -
        so the shell reads it by name rather than declaring a type over
        both.
        """
        tool_id: str = getattr(self, "TOOL_ID")
        return tool_id

    def _preset_key(self, name: str) -> str:
        """Return the stored key the *name* field is saved under.

        Args:
            name: The Tk variable's attribute name.

        Returns:
            The key :attr:`PRESET_ALIASES` maps it to, or *name* itself.
        """
        for key, attribute in self.PRESET_ALIASES.items():
            if attribute == name:
                return key
        return name

    def _read_preset(self, name: str) -> dict[str, Any] | None:
        """Return the named preset's settings, or None when it is absent.

        Args:
            name: The preset's name as the user saved it.
        """
        if self.PRESET_KEY_PREFIX:
            return load_tool_preset(self.PRESET_KEY_PREFIX, name)
        return suite_config.load_preset(self._preset_tool_id(), name)

    def _write_preset(self, name: str, settings: dict[str, Any]) -> None:
        """Store *settings* under *name* in this window's preset store."""
        if self.PRESET_KEY_PREFIX:
            save_tool_preset(self.PRESET_KEY_PREFIX, name, settings)
        else:
            suite_config.save_preset(self._preset_tool_id(), name, settings)

    def _drop_preset(self, name: str) -> None:
        """Delete the named preset from this window's preset store."""
        if self.PRESET_KEY_PREFIX:
            delete_tool_preset(self.PRESET_KEY_PREFIX, name)
        else:
            suite_config.delete_preset(self._preset_tool_id(), name)

    def _preset_names(self) -> list[str]:
        """Return the names this window's preset store holds."""
        if self.PRESET_KEY_PREFIX:
            return load_preset_names(f"{self.PRESET_KEY_PREFIX}_presets_list")
        return suite_config.list_presets(self._preset_tool_id())

    def use_preset(self, name: str) -> None:
        """Apply the named preset to the Setup tab.

        A missing preset is a no-op in both stores; one the store returns
        whole is applied, so the older per-tool store keeps filling its own
        defaults for a key an old preset does not carry.
        """
        settings = self._read_preset(name)
        if settings is not None:
            self._apply_preset(settings)

    def store_preset(self, name: str) -> None:
        """Store the Setup tab's current settings under *name*."""
        self._write_preset(name, self._collect_settings())
        self._refresh_preset_names()

    def remove_preset(self, name: str) -> None:
        """Delete the named preset and refresh the combo."""
        self._drop_preset(name)
        self._refresh_preset_names()

    def _refresh_preset_names(self) -> None:
        """Re-read this window's preset names into its Setup-tab combo."""
        if self._refresh_preset_list is not None:
            self._refresh_preset_list(self._preset_names())

    def _mirror_cli_args(self, parsed: Any) -> None:
        """Mirror the Master Driver's handshake onto the Setup tab.

        A standalone launch passes no folder, and then nothing is touched: the
        window keeps the settings its own ``__init__`` restored.

        Args:
            parsed: The tool's parsed argv.
        """
        if not parsed.folder_path:
            return

        self.folder_path.set(parsed.folder_path)
        self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)
        self.analysis_duration.set(parsed.analysis_duration)
        self.parallel_mode.set(parsed.parallel_mode)
        self.max_workers.set(parsed.max_workers)
        self.auto_end = parsed.auto_end

        if parsed.auto_start:
            self.root.after(1500, self.start_processing)

    def start_processing(self) -> None:
        """Validate the inputs, snapshot the run's settings and start the run.

        The settings the run reads are snapshotted here, on the Tk thread, so
        the worker and the completion read no widget and no Tk variable
        (``AGENTS.md``, GUI callback contract).  A window whose run needs more
        settings overrides this and keeps :meth:`_start_run` as its entry
        point.
        """
        folder = self.folder_path.get()
        if not folder:
            messagebox.showwarning("Warning", "Please select a music directory first.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Error", "Selected path is not a valid directory.")
            return

        # A typed worker count can exceed the fixed slot grid; cap it on the
        # main thread (with a visible warning) before anything is persisted,
        # so the saved setting matches the run that actually happens (D66).
        workers = cap_typed_workers(
            self.max_workers,
            getattr(self, "slot_vars", None),
            unattended=self._launched_from_driver,
        )
        suite_config.save_value(
            self._setting_key("parallel_mode"), self.parallel_mode.get()
        )
        suite_config.save_value(self._setting_key("max_workers"), workers)

        self._dir_path = folder
        self._is_dry_run = self.run_mode.get() == "Dry Run"
        self._analysis_seconds = self.analysis_duration.get()
        self._parallel = self.parallel_mode.get()
        self._workers = workers

        self.start_btn.config(state="disabled")
        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        self.notebook.select(self.processing_frame)
        self.overall_status.set(self.STARTING_STATUS)

        self._start_run()

    def _start_run(self) -> None:
        """Start the run ``start_processing`` snapshot, on the shell's thread.

        Raises:
            NotImplementedError: Always, in the base class: the run is the
                tool's own.
        """
        raise NotImplementedError(f"{type(self).__name__} must implement _start_run()")

    # ── Auto End ──────────────────────────────────────────────────────────────

    def close_for_auto_end(self) -> None:
        """Mark the run's report and close the window (Tk thread only).

        Called from the completion render, so the report the marker is appended
        to is the one the run just wrote.
        """
        self._mark_auto_end()
        self.root.after(_AUTO_END_CLOSE_MS, self.root.destroy)

    def _mark_auto_end(self) -> None:
        """Append the Auto End marker to the run's report (best effort).

        The audio work is already done and the window is about to close, so a
        report that cannot be appended to is a log line, never a dialog.
        """
        try:
            with open(self._log_path, "a", encoding="utf-8") as handle:
                handle.write(_AUTO_END_MARKER)
        except OSError as exc:
            logger.warning("Could not append the Auto End marker: %s", exc)

    # ── Worker protocol ───────────────────────────────────────────────────────

    def _start_worker(self, target: Callable[..., None], args: tuple[Any, ...]) -> None:
        """Run *target* on a daemon thread and start the Tk poller.

        A fresh queue per run: the poller drains it and stops with the run's
        thread, so no message from an earlier run can reach a widget.

        Args:
            target: The window's thread entry point.  It may not touch a widget
                or call ``root.after``.
            args: Its arguments, in order.
        """
        self._ui_updates = SimpleQueue()
        self._run_thread = threading.Thread(target=target, args=args, daemon=True)
        self._run_thread.start()
        self._poll_ui_updates()

    def _poll_ui_updates(self) -> None:
        """Apply the run's queued messages while its thread is alive.

        The loop is ``event_pump.pump_events``: it drains in order, re-arms
        while the run's thread lives, and drains once more after it ends, so the
        completion queued as the worker exited still renders.  No tick id is
        kept - the shell has no close handler, and a destroyed root drops its
        pending ``after`` callbacks itself.
        """
        pump_events(
            self.root,
            self._ui_updates,
            self._dispatch_ui_message,
            is_running=lambda: (
                self._run_thread is not None and self._run_thread.is_alive()
            ),
            next_tick=self._poll_ui_updates,
        )

    def _dispatch_ui_message(self, message: tuple[Any, ...]) -> None:
        """Render one queued message on the Tk thread.

        Args:
            message: One item the run's thread queued.

        Raises:
            NotImplementedError: Always, in the base class: what a message
                means is the tool's own.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _dispatch_ui_message(message)"
        )

    # ── Run report ────────────────────────────────────────────────────────────

    def _write_run_report_standard(
        self,
        *,
        header: list[str],
        log_entries: list[str],
        rows: tuple[tuple[str, str], ...],
        total: int,
        tagged: int,
        skipped: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Serialise one run's report into ``_log_path``.

        The footer is the one every peer writes, so the run-report lock reads
        this file the way it reads an adopter's.  Call it from the completion
        handler, which runs off the Tk thread; a failed write is logged, never
        raised, because the audio work is already done.

        The report's folder is created when it does not exist, so a run that
        writes into a fresh output directory still leaves a report View Log can
        open instead of a logged failure.

        Args:
            header: Report header lines for this run.
            log_entries: The per-file report lines.
            rows: This run's extra summary rows, in display order.
            total: Files the run visited.
            tagged: Files handled without being skipped or erroring.
            skipped: Files left alone.
            errors: Files that failed.
            duration_secs: Wall-clock run time.
        """
        summary: list[str] = summary_lines(
            total=total,
            tagged=tagged,
            tagged_label=self.TAGGED_LABEL,
            skipped_label=self.SKIPPED_LABEL,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            rows=rows,
        )

        try:
            Path(self._log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(header + log_entries + summary)
            logger.info("Log written to '%s'", self._log_path)
        except Exception as exc:
            # The audio work is already done by the time the report is
            # serialised, so a failed write is logged, never raised (AGENTS.md).
            mapped = map_to_audio_error(exc, context={"log_path": self._log_path})
            logger.error(
                "[%s] Could not write log '%s': %s",
                type(mapped).__name__,
                self._log_path,
                mapped,
                exc_info=True,
            )

    # ── Callback contract ─────────────────────────────────────────────────────

    def render_progress(self, *, processed: int, total: int, display_text: str) -> None:
        """Render one progress tick on the Processing tab.

        Call this from the tool's ``on_progress`` handler, after any tool-owned
        counters are rendered; the widget writes are marshalled to the Tk
        thread.

        Args:
            processed: Files finished so far.
            total: Files the run will attempt.
            display_text: The per-file line the processor published.
        """
        self.root.after(0, self._render_progress, processed, total, display_text)

    def _render_progress(self, processed: int, total: int, display_text: str) -> None:
        """Write one progress tick to the widgets (Tk thread)."""
        self._render_progress_standard(processed, total, display_text)

    def render_completion(self, *, duration_secs: float, output_dir: str) -> None:
        """Record the run's target and switch the window to its results.

        Call this from the tool's ``on_complete`` handler after it has written
        its own report and summary; the widget writes are marshalled to the Tk
        thread.

        Args:
            duration_secs: Wall-clock seconds the run took.
            output_dir: Directory the run wrote to; the Open Folder button and
                the Master Driver's report read it from here.
        """
        self._out_dir = output_dir
        self.root.after(0, self._render_completion, duration_secs)

    def _render_completion(self, duration_secs: float) -> None:
        """Write the completion state to the widgets (Tk thread)."""
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.completion_label.config(text=self.completion_text)
        self.notebook.select(self.results_frame)
        start_btn = getattr(self, "start_btn", None)
        if start_btn is not None:
            start_btn.config(state="normal")

    def _on_error(self, message: str) -> None:
        """Show a run failure and re-enable the start button.

        Args:
            message: The user-facing message the processor published.
        """
        messagebox.showerror("Error", message)
        start_btn = getattr(self, "start_btn", None)
        if start_btn is not None:
            start_btn.config(state="normal")
