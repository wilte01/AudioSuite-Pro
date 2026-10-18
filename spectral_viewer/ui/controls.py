"""controls.py — the Spectral Viewer's parameter panel and file list.

Kept out of ``app.py`` so the widget wiring has one home and the app is left
with state, rendering and export. The panel owns no logic: it exposes the
widgets and forwards the five user actions (browse, scan, select, render,
export) to callbacks the app supplies, which is also what lets the GUI tests
assert the wiring without a real mainloop.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from tkinter import ttk

from audio_suite_shared import styles

#: Colour maps offered by the combobox. A short curated list rather than every
#: registered matplotlib map: a readonly dropdown with 170 entries is a scroll
#: bar, not a choice.
CMAP_CHOICES: tuple[str, ...] = ("magma", "inferno", "viridis", "plasma", "gray")

#: Width of the left-hand control column, in pixels.
PANEL_WIDTH = 330


@dataclass(frozen=True)
class ViewerControls:
    """Widgets the app needs to read or enable later.

    Attributes:
        path_entry: The audio file / folder entry.
        file_list: The picked folder's audio files.
        render_button: Re-renders the current selection and settings.
        export_button: Writes the displayed figure as a PNG.
    """

    path_entry: tk.Entry
    file_list: tk.Listbox
    render_button: tk.Button
    export_button: tk.Button


def _labelled(parent: tk.Misc, text: str, row: int, *, width: int = 14) -> tk.Frame:
    """Return a row frame carrying a right-aligned caption label."""
    row_frame = tk.Frame(parent, bg=styles.BG_WHITE)
    row_frame.grid(row=row, column=0, columnspan=2, sticky="ew", pady=1)
    tk.Label(
        row_frame,
        text=text,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=width,
        anchor="w",
    ).pack(side=tk.LEFT)
    return row_frame


def _entry(parent: tk.Misc, variable: tk.StringVar, width: int = 8) -> tk.Entry:
    """Return a small entry bound to *variable*."""
    entry = tk.Entry(
        parent,
        textvariable=variable,
        width=width,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    )
    entry.pack(side=tk.LEFT, padx=(0, 8))
    return entry


def build_controls(
    parent: tk.Misc,
    *,
    path_var: tk.StringVar,
    start_var: tk.StringVar,
    end_var: tk.StringVar,
    max_freq_var: tk.StringVar,
    db_range_var: tk.StringVar,
    n_fft_var: tk.StringVar,
    cmap_var: tk.StringVar,
    on_browse: Callable[[], None],
    on_scan: Callable[[], None],
    on_select: Callable[[object], None],
    on_render: Callable[[], None],
    on_export: Callable[[], None],
) -> ViewerControls:
    """Build the left-hand control panel.

    Args:
        parent: Frame to build into (grid-managed by this function).
        path_var: Holds the audio file or folder path.
        start_var: Window start in seconds.
        end_var: Window end in seconds (``0`` = to the end).
        max_freq_var: Highest displayed frequency in Hz (``0`` = Nyquist).
        db_range_var: Colour floor in dB below the peak.
        n_fft_var: FFT window size in samples.
        cmap_var: Selected colour map name.
        on_browse: Called by the Browse button.
        on_scan: Called by the Scan button (loads the file list).
        on_select: Called when the file list selection changes.
        on_render: Called by the Render button.
        on_export: Called by the Export PNG button.

    Returns:
        A :class:`ViewerControls` holding the widgets the app reads.
    """
    panel = tk.Frame(parent, bg=styles.BG_WHITE, width=PANEL_WIDTH)
    panel.pack(side=tk.LEFT, fill="y", padx=(0, 10))
    panel.pack_propagate(False)

    tk.Label(
        panel,
        text="Audio file or folder",
        font=styles.FONT_LABEL,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(anchor="w")

    path_row = tk.Frame(panel, bg=styles.BG_WHITE)
    path_row.pack(fill="x", pady=(2, 6))
    path_entry = tk.Entry(
        path_row,
        textvariable=path_var,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    )
    path_entry.pack(side=tk.LEFT, fill="x", expand=True)
    tk.Button(
        path_row,
        text="Browse",
        command=on_browse,
        font=styles.FONT_BUTTON,
        bg=styles.get_main(),
        fg="white",
        relief="flat",
        padx=8,
    ).pack(side=tk.LEFT, padx=(4, 0))
    tk.Button(
        path_row,
        text="Scan",
        command=on_scan,
        font=styles.FONT_BUTTON,
        bg=styles.get_main(),
        fg="white",
        relief="flat",
        padx=8,
    ).pack(side=tk.LEFT, padx=(4, 0))

    list_row = tk.Frame(panel, bg=styles.BG_WHITE)
    list_row.pack(fill="both", expand=True)
    file_list = tk.Listbox(
        list_row,
        font=styles.FONT_MONO,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        height=12,
        activestyle="none",
        exportselection=False,
    )
    file_list.pack(side=tk.LEFT, fill="both", expand=True)
    scroll = tk.Scrollbar(list_row, command=file_list.yview)
    scroll.pack(side="right", fill="y")
    file_list.configure(yscrollcommand=scroll.set)
    file_list.bind("<<ListboxSelect>>", on_select)

    settings = tk.Frame(panel, bg=styles.BG_WHITE)
    settings.pack(fill="x", pady=(8, 0))
    settings.grid_columnconfigure(1, weight=1)

    window_row = _labelled(settings, "Time window (s)", 0)
    tk.Label(
        window_row,
        text="start",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
    ).pack(side=tk.LEFT)
    _entry(window_row, start_var, width=6)
    tk.Label(
        window_row,
        text="end",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
    ).pack(side=tk.LEFT)
    _entry(window_row, end_var, width=6)

    freq_row = _labelled(settings, "Max frequency (Hz)", 1)
    _entry(freq_row, max_freq_var)

    range_row = _labelled(settings, "Colour range (dB)", 2)
    _entry(range_row, db_range_var)

    fft_row = _labelled(settings, "FFT size (samples)", 3)
    _entry(fft_row, n_fft_var, width=10)

    cmap_row = _labelled(settings, "Colour map", 4)
    ttk.Combobox(
        cmap_row,
        textvariable=cmap_var,
        state="readonly",
        values=CMAP_CHOICES,
        width=12,
        font=styles.FONT_BODY,
    ).pack(side=tk.LEFT)

    button_row = tk.Frame(panel, bg=styles.BG_WHITE)
    button_row.pack(fill="x", pady=(10, 0))
    render_button = tk.Button(
        button_row,
        text="Render",
        command=on_render,
        font=styles.FONT_BUTTON,
        bg=styles.get_main(),
        fg="white",
        relief="flat",
        padx=10,
    )
    render_button.pack(side=tk.LEFT)
    export_button = tk.Button(
        button_row,
        text="Export PNG",
        command=on_export,
        font=styles.FONT_BUTTON,
        bg=styles.get_main(),
        fg="white",
        relief="flat",
        padx=10,
        state="disabled",
    )
    export_button.pack(side=tk.LEFT, padx=(6, 0))

    return ViewerControls(
        path_entry=path_entry,
        file_list=file_list,
        render_button=render_button,
        export_button=export_button,
    )
