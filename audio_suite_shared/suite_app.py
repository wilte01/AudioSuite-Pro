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
  helpers, all obeying the GUI callback contract in ``AGENTS.md``.

What a tool supplies:

- ``title``, ``window_key``, ``program_name``, ``guide_name`` and
  ``completion_text`` as class attributes;
- ``slot_vars`` (optional) *before* calling ``super().__init__``: the Processing
  tab renders its worker grid from that list when it is present;
- ``_build_setup_tab(parent)``, the one layout hook.  A tool that needs an extra
  tab overrides ``_tab_specs`` and extends ``tab_labels`` in lockstep.

A tool keeps a payload handler when the payload is its own.  The shell offers
``render_progress`` / ``render_completion`` for the universal widgets and a
tool's handler calls them after doing its own work.  They are helpers rather
than overridable callbacks on purpose: a tool's completion payload is wider
than the universal one, and an override that *requires* those extra fields is
an LSP break (mypy's ``[override]``) — silencing it with ``# type: ignore`` is
what this repository forbids.  ``music_format_converter`` is the worked
example.

Changed in 2.4.3: adds SuiteApp (PLAN_2026-11-03_2.4.3_structure.md, WP-8).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Any

from . import styles
from .app_bootstrap import bootstrap_tool_app
from .ui_common import build_processing_tab, build_results_tab
from .ui_helpers import UIHelperMixin

#: Emits one tab's widgets into the frame the shell created for it.
TabBuilder = Callable[[tk.Frame], Any]


class SuiteApp(UIHelperMixin):
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
        completion_label, summary_label, time_label: Results-tab widgets.
        start_btn: The tool's start button, once its Setup tab has built it.
        controls_panel: The Setup tab's run-controls strip, when the tool
            embeds one.
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

    def __init__(self, root: tk.Tk) -> None:
        """Bootstrap the window and build the shell's notebook.

        Args:
            root: The Tk root the launcher created.
        """
        self.root = root
        self.error_logger, _style = bootstrap_tool_app(
            root, self.title, self.window_key, self.program_name
        )
        self._log_path: str = ""
        self._out_dir: str = ""
        self._build_ui()

    # ── Construction ──────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Build the Help header, the notebook and every declared tab."""
        help_frame = tk.Frame(self.root, bg=styles.BG_LIGHT)
        help_frame.pack(fill="x", padx=10, pady=(10, 0))
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
        widgets = build_processing_tab(parent, slot_vars)
        self.overall_status: tk.StringVar = widgets["overall_status"]
        self.progress: ttk.Progressbar = widgets["progress"]
        self.stats_label: tk.Label = widgets["stats_label"]
        self.file_listbox: tk.Listbox = widgets["file_listbox"]

    def _build_results_tab(self, parent: tk.Frame) -> None:
        """Build the shared Results tab and wire its two buttons."""
        widgets = build_results_tab(
            parent,
            self.completion_text,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = widgets["completion_label"]
        self.summary_label: tk.Label = widgets["summary_label"]
        self.time_label: tk.Label = widgets["time_label"]

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
        self.progress["maximum"] = total
        self.progress["value"] = processed
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

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
