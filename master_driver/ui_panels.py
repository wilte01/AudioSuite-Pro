"""
ui_panels.py — Pure UI-building helpers extracted from AudioSuiteDriver.

Functions return the widgets they create so that the caller (app.py) can
store references needed for tab-switching and accent-colour refresh.
"""

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from audio_suite_shared import styles

from .state.app_state import AppState


def build_control_strip(parent: tk.Frame, state: AppState) -> dict[str, tk.Widget]:
    """Build the shared toolbar row.

    Returns a dict of the created widgets keyed as::

        select_all, mode_combo, auto_start, auto_end, clear_logs,
        batch_status_text, batch_eta_label, batch_progress_bar
    """
    select_all_btn = tk.Checkbutton(
        parent,
        text="SELECT ALL",
        font=styles.FONT_BODY_B,
        bg=styles.BG_APP,
        fg=styles.FG_MAIN,
        activeforeground=styles.FG_MAIN,
        activebackground=styles.BG_APP,
        selectcolor=styles.BG_APP,
    )
    select_all_btn.grid(row=0, column=0, sticky="w", padx=(0, 20))

    tk.Label(
        parent,
        text="Mode:",
        font=styles.FONT_BODY_B,
        bg=styles.BG_APP,
        fg=styles.FG_MAIN,
    ).grid(row=0, column=1, sticky="e", padx=(0, 5))

    mode_combo = ttk.Combobox(
        parent,
        state="readonly",
        font=styles.FONT_BODY,
        values=["Dry Run", "Live Update"],
        width=12,
    )
    mode_combo.grid(row=0, column=2)

    auto_start_btn = tk.Checkbutton(
        parent,
        text="Auto Start",
        font=styles.FONT_BODY,
        bg=styles.BG_APP,
        fg=styles.FG_MAIN,
        activeforeground=styles.FG_MAIN,
        activebackground=styles.BG_APP,
        selectcolor=styles.BG_APP,
    )
    auto_start_btn.grid(row=0, column=3, padx=(20, 10))

    auto_end_btn = tk.Checkbutton(
        parent,
        text="Auto End",
        font=styles.FONT_BODY,
        bg=styles.BG_APP,
        fg=styles.FG_MAIN,
        activeforeground=styles.FG_MAIN,
        activebackground=styles.BG_APP,
        selectcolor=styles.BG_APP,
    )
    auto_end_btn.grid(row=0, column=4, padx=(0, 10))

    clear_logs_btn = tk.Checkbutton(
        parent,
        text="Clear Logs",
        font=styles.FONT_BODY,
        bg=styles.BG_APP,
        fg=styles.FG_MAIN,
        activeforeground=styles.FG_MAIN,
        activebackground=styles.BG_APP,
        selectcolor=styles.BG_APP,
    )
    clear_logs_btn.grid(row=0, column=5, padx=(0, 10))

    parallel_btn = tk.Checkbutton(
        parent,
        text="Parallel",
        font=styles.FONT_BODY,
        bg=styles.BG_APP,
        fg=styles.FG_MAIN,
        activeforeground=styles.FG_MAIN,
        activebackground=styles.BG_APP,
        selectcolor=styles.BG_APP,
    )
    parallel_btn.grid(row=0, column=6, padx=(0, 10))

    # ── Batch progress widgets (rows 1-3, invisible until batch runs) ──────
    # Per-step status text area
    batch_status_text = tk.Text(
        parent,
        height=8,
        width=80,
        font=("Consolas", 9),
        bg=styles.BG_ITEM,
        fg=styles.FG_MAIN,
        relief="flat",
        bd=2,
        wrap="none",
        state="disabled",
    )
    batch_status_text.grid(
        row=1, column=0, columnspan=6, sticky="ew", pady=(4, 2), padx=2
    )
    batch_status_text.grid_remove()

    # Overall summary / ETA label
    batch_eta_label = tk.Label(
        parent,
        text="",
        font=styles.FONT_BODY_B,
        bg=styles.BG_APP,
        fg=styles.FG_MAIN,
        anchor="w",
    )
    batch_eta_label.grid(row=2, column=0, columnspan=6, sticky="w", padx=(4, 0))
    batch_eta_label.grid_remove()

    batch_progress_bar = ttk.Progressbar(
        parent,
        mode="determinate",
        length=400,
    )
    batch_progress_bar.grid(
        row=3, column=0, columnspan=6, sticky="ew", pady=(2, 4), padx=2
    )
    batch_progress_bar.grid_remove()

    return {
        "select_all": select_all_btn,
        "mode_combo": mode_combo,
        "auto_start": auto_start_btn,
        "auto_end": auto_end_btn,
        "clear_logs": clear_logs_btn,
        "parallel": parallel_btn,
        "batch_status_text": batch_status_text,
        "batch_eta_label": batch_eta_label,
        "batch_progress_bar": batch_progress_bar,
    }


def build_header(parent: tk.Misc, title: str) -> None:
    """Build the dark header bar with the application title."""
    header = tk.Frame(parent, bg=styles.get_main(), pady=15)
    header.pack(fill="x")
    tk.Label(
        header,
        text=title,
        font=styles.FONT_HEADER,
        fg="white",
        bg=styles.get_main(),
    ).pack()


def build_sidebar(
    parent: tk.Frame, switch_callback: Callable[[str], None]
) -> dict[str, tk.Button]:
    """Build the left-side tab strip with REFINE / ENRICH / UTIL / SETTINGS buttons.

    Returns a dict of the created buttons keyed by tab name::

        refine, enrich, util, settings
    """
    tab_strip = tk.Frame(parent, bg=styles.BG_APP, width=90)
    tab_strip.pack(side="left", fill="y")
    tab_strip.pack_propagate(False)

    sep = tk.Frame(parent, bg="#cccccc", width=1)
    sep.pack(side="left", fill="y")

    tk.Frame(tab_strip, bg=styles.BG_APP, height=10).pack()

    btn_refine = tk.Button(
        tab_strip,
        text="REFINE",
        font=styles.FONT_LABEL_B,
        fg="white",
        bg=styles.tab_active(),
        relief="flat",
        bd=0,
        padx=5,
        pady=18,
        cursor="hand2",
        width=8,
        command=lambda: switch_callback("refine"),
    )
    btn_refine.pack(fill="x", padx=4, pady=(0, 2))

    btn_enrich = tk.Button(
        tab_strip,
        text="ENRICH",
        font=styles.FONT_LABEL_B,
        fg="white",
        bg=styles.tab_inactive(),
        relief="flat",
        bd=0,
        padx=5,
        pady=18,
        cursor="hand2",
        width=8,
        command=lambda: switch_callback("enrich"),
    )
    btn_enrich.pack(fill="x", padx=4, pady=(0, 2))

    btn_util = tk.Button(
        tab_strip,
        text="UTIL",
        font=styles.FONT_LABEL_B,
        fg="white",
        bg=styles.tab_inactive(),
        relief="flat",
        bd=0,
        padx=5,
        pady=18,
        cursor="hand2",
        width=8,
        command=lambda: switch_callback("util"),
    )
    btn_util.pack(fill="x", padx=4, pady=(0, 2))

    tk.Frame(tab_strip, bg=styles.BG_APP).pack(fill="y", expand=True)
    tk.Frame(tab_strip, bg="#cccccc", height=1).pack(fill="x", padx=4, pady=(0, 4))

    btn_settings = tk.Button(
        tab_strip,
        text="\u2699 SET",
        font=styles.FONT_BODY_B,
        fg="white",
        bg=styles.SETTINGS_TAB_INACTIVE,
        relief="flat",
        bd=0,
        padx=5,
        pady=14,
        cursor="hand2",
        width=8,
        command=lambda: switch_callback("settings"),
    )
    btn_settings.pack(fill="x", padx=4, pady=(0, 8))

    return {
        "refine": btn_refine,
        "enrich": btn_enrich,
        "util": btn_util,
        "settings": btn_settings,
    }
