"""
setup_tab.py
Builds the Setup tab widgets for Tag Field Updater.
Receives parent frame and tk variables; returns a dict of widgets.


Changed in 2.2.1: extracted from ``ui/app.py`` into the module layout every
peer uses (maintenance item U4), with the tool-specific options emitted by
``_SetupFrame._build_options``.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame

from ..core.filename_patterns import DEFAULT_PATTERNS


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    filename_mode: tk.BooleanVar,
    only_fill_blanks: tk.BooleanVar,
    action_group: tk.StringVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    on_stop: Callable[[], None],
    on_filename_mode_toggled: Callable[[], None],
    on_load_group: Callable[[], None],
    on_save_group: Callable[[], None],
    group_names: list[str],
    driver_locked: bool = False,
    modes: tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """
    Populate the Setup tab.

    Args:
        parent:                  The tab Frame to populate.
        folder_path:             StringVar bound to the source directory entry.
        run_mode:                StringVar for the Dry Run / Live Update
                                 combobox.
        auto_start_var:          BooleanVar bound to the Auto Start checkbox.
        auto_end_var:            BooleanVar bound to the Auto End checkbox.
        clear_logs_var:          Tk variable mirroring the driver's Clear Logs
                                 state (checkbox stays inert).
        parallel_var:            Tk variable mirroring the driver's Parallel
                                 state (checkbox stays inert).
        filename_mode:           BooleanVar for the filename source (F-01).
        only_fill_blanks:        BooleanVar for the filename source's write mode.
        action_group:            StringVar holding the selected group name.
        on_browse:               Callback for the Browse button.
        on_start:                Callback for the start button.
        on_stop:                 Callback for the Stop button.
        on_filename_mode_toggled: Callback for the filename mode checkbox.
        on_load_group:           Callback for the Load button.
        on_save_group:           Callback for the Save as button.
        group_names:             Saved action-group names for the combobox.
        driver_locked:           True when launched via the Master Driver; locks
                                 the Run Controls panel to inherited values.
        modes:                   Mode labels for the strip; the driver's own
                                 strings.

    Returns:
        Dict with keys: setup_frame, start_btn, controls_panel, stop_btn,
        patterns_text, group_combo.
    """
    frame = _SetupFrame(
        parent,
        title="Tag Field Updater",
        start_text="START SCANNING",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        browse_text="Browse & Scan",
        driver_locked=driver_locked,
        modes=modes,
        filename_mode=filename_mode,
        only_fill_blanks=only_fill_blanks,
        action_group=action_group,
        on_stop=on_stop,
        on_filename_mode_toggled=on_filename_mode_toggled,
        on_load_group=on_load_group,
        on_save_group=on_save_group,
        group_names=group_names,
    )
    widgets = frame.get_widgets()
    widgets["setup_frame"] = frame
    return widgets


class _SetupFrame(BaseSetupFrame):
    """Tag Field Updater Setup tab skeleton on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        *,
        filename_mode: tk.BooleanVar,
        only_fill_blanks: tk.BooleanVar,
        action_group: tk.StringVar,
        on_stop: Callable[[], None],
        on_filename_mode_toggled: Callable[[], None],
        on_load_group: Callable[[], None],
        on_save_group: Callable[[], None],
        group_names: list[str],
        **kwargs: Any,
    ) -> None:
        # Tool-specific option state must be bound before super().__init__,
        # which calls _layout() -> _build_options() during construction.
        self._filename_mode = filename_mode
        self._only_fill_blanks = only_fill_blanks
        self._action_group = action_group
        self._on_stop = on_stop
        self._on_filename_mode_toggled = on_filename_mode_toggled
        self._on_load_group = on_load_group
        self._on_save_group = on_save_group
        self._group_names = group_names
        #: Filled by ``_build_options`` and handed back by ``get_widgets``.
        self.patterns_text: tk.Text | None = None
        self.group_combo: ttk.Combobox | None = None
        self.stop_btn: tk.Button | None = None
        super().__init__(parent, **kwargs)

    def get_widgets(self) -> dict[str, Any]:
        """Return the widgets the window drives after construction."""
        widgets = super().get_widgets()
        widgets.update(
            {
                "stop_btn": self.stop_btn,
                "patterns_text": self.patterns_text,
                "group_combo": self.group_combo,
            }
        )
        return widgets

    def _build_options(self) -> None:
        """Emit the filename source, the field pointer and the Stop button."""
        self._build_filename_frame()

        # A pointer at the guide, not a copy of it: the rules and the field
        # list live in one document the Help button opens.
        tk.Label(
            self,
            text=(
                "Tag Fields to Update: the custom TXXX fields ALBUMARTISTGENRE, "
                "ALBUMGENRE and ARTISTGENRE, plus the standard TIT1 (content "
                "group) and TCON (genre).\nThe replacement rules — a bare '/' "
                "becomes '; ' while ' / ' is preserved, and only fields that "
                "already exist are touched — are in the Help guide."
            ),
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            justify=tk.LEFT,
            anchor="w",
            wraplength=760,
        ).pack(fill="x", pady=(6, 4))

        # Stop sits above the shared full-width start button: a scan is
        # cooperative, so stopping must not require switching tabs.
        stop_row = tk.Frame(self, bg=styles.BG_WHITE)
        stop_row.pack(fill="x", pady=(0, 4))
        self.stop_btn = tk.Button(
            stop_row,
            text="Stop",
            bg=styles.BG_LIGHT,
            fg=styles.FG_MAIN,
            font=styles.FONT_BUTTON,
            padx=15,
            pady=6,
            state=tk.DISABLED,
            command=self._on_stop,
        )
        self.stop_btn.pack(side=tk.RIGHT)

    def _build_filename_frame(self) -> None:
        """Build the filename-source controls (F-01)."""
        frame = tk.LabelFrame(
            self,
            text="Tag from Filenames",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            padx=10,
            pady=10,
        )
        frame.pack(fill="both", expand=True, pady=(0, 10))

        tk.Checkbutton(
            frame,
            text="Tag from filenames (patterns below, one per line, tried in order)",
            variable=self._filename_mode,
            command=self._on_filename_mode_toggled,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            activebackground=styles.BG_WHITE,
            selectcolor=styles.BG_WHITE,
            font=styles.FONT_BODY,
            anchor="w",
        ).pack(fill="x", anchor="w")

        # The box grows with the window and scrolls: a long pattern list is
        # read in place instead of being cut at a fixed height, and Tk's word
        # wrapping is display-only, so a wrapped pattern is still one line.
        box = tk.Frame(frame, bg=styles.BG_WHITE)
        box.pack(fill="both", expand=True, pady=(4, 4))
        self.patterns_text = tk.Text(
            box,
            height=5,
            width=70,
            wrap=tk.WORD,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
            font=styles.FONT_MONO,
            relief=tk.SOLID,
            borderwidth=1,
        )
        pattern_scroll = ttk.Scrollbar(
            box, orient="vertical", command=self.patterns_text.yview
        )
        self.patterns_text.configure(yscrollcommand=pattern_scroll.set)
        self.patterns_text.pack(side=tk.LEFT, fill="both", expand=True)
        pattern_scroll.pack(side=tk.RIGHT, fill="y")
        self.patterns_text.insert("1.0", "\n".join(DEFAULT_PATTERNS))

        tk.Checkbutton(
            frame,
            text="Only fill blank tags (never overwrite an existing value)",
            variable=self._only_fill_blanks,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            activebackground=styles.BG_WHITE,
            selectcolor=styles.BG_WHITE,
            font=styles.FONT_BODY,
            anchor="w",
        ).pack(fill="x", anchor="w")

        group_row = tk.Frame(frame, bg=styles.BG_WHITE)
        group_row.pack(fill="x", pady=(6, 0))
        tk.Label(
            group_row,
            text="Action group:",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT)
        self.group_combo = ttk.Combobox(
            group_row, textvariable=self._action_group, state="readonly", width=28
        )
        self.group_combo.pack(side=tk.LEFT, padx=(5, 5))
        self.group_combo["values"] = sorted(self._group_names)
        ttk.Button(group_row, text="Load", command=self._on_load_group).pack(
            side=tk.LEFT, padx=(0, 5)
        )
        ttk.Button(group_row, text="Save as...", command=self._on_save_group).pack(
            side=tk.LEFT
        )
