"""ui_tabs.py - the shared Results and Processing tab builders.

Split out of :mod:`audio_suite_shared.ui_common` in 2.4.3 (WP-9).
``ui_common`` keeps the Setup frame, the worker cap and the optional-dependency
installer, and re-exports every name here, so an existing
``from audio_suite_shared.ui_common import build_results_tab`` keeps working.

Changed in 2.4.3: split out of ``audio_suite_shared.ui_common``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
Changed in 2.5.0: ``_default_open_log`` reads the suite log through
``suite_paths.suite_path`` instead of counting directories up from this file,
so a packaged build finds its ``logs/`` directory (D-44).
"""

import logging
import os
import sys
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional

from . import styles
from .secure_subprocess import SubprocessSecurityError, run_secure_subprocess
from .suite_paths import suite_path
from .ui_audition import add_audition_buttons

_log = logging.getLogger(f"audio_suite.{__name__}")


def _default_open_log() -> None:
    """Default handler to open the latest suite log file."""
    try:
        log_file = str(suite_path("logs", "audio_suite.log"))
        if os.path.exists(log_file):
            if sys.platform == "win32":
                os.startfile(log_file)
            elif sys.platform == "darwin":
                run_secure_subprocess(
                    "open", [log_file], capture_output=True, check=False
                )
            else:
                run_secure_subprocess(
                    "xdg-open", [log_file], capture_output=True, check=False
                )
    except (OSError, SubprocessSecurityError, tk.TclError) as _exc:
        _log.warning("Swallowed exception: %s", _exc, exc_info=True)


def build_results_tab(
    parent: tk.Frame,
    completion_text: str,
    on_open_log: Optional[Callable[[], None]] = None,
    on_open_folder: Optional[Callable[[], None]] = None,
    log_btn_text: str = "View Log",
    extra_labels: list[str] | None = None,
    on_play_original: Optional[Callable[[], None]] = None,
    on_play_result: Optional[Callable[[], None]] = None,
) -> dict[str, Any]:
    """
    Build the standard Results tab layout.

    Args:
        parent:          The notebook tab frame.
        completion_text: Bold heading shown on completion.
        on_open_log:     Callback for the View Log button
                         (defaults to opening suite log).
        on_open_folder:  Callback for the Open Folder button.
        log_btn_text:    Override the log button label (default "View Log").
        extra_labels:    Optional list of extra tk.Label keys to create,
                         pack below summary_label, and return in the dict.
                         e.g. ['genre_label']
        on_play_original: Optional callback for the "Play Original" audition
                         button.  When provided (along with on_play_result) a
                         before/after audition row is added to the results tab.
        on_play_result:   Optional callback for the "Play Result" audition
                         button.  Only wired if on_play_original is also set.

    Returns:
        The widgets the tool drives, keyed by name::

            {
                'completion_label': tk.Label,
                'time_label':       tk.Label,
                'summary_label':    tk.Label,
                'extra keys':       tk.Label,   # one per extra_labels entry
                'play_original_btn': tk.Button,  # if on_play_original set
                'play_result_btn':   tk.Button,  # if on_play_original set
                'audition_caption_var': tk.StringVar,
            }
    """
    if on_open_log is None:
        on_open_log = _default_open_log

    if on_open_folder is None:
        on_open_folder = _default_open_log

    frame = tk.Frame(parent, padx=40, pady=40, bg=styles.BG_WHITE)
    frame.pack(expand=True, fill="both")

    completion_label = tk.Label(
        frame,
        text=completion_text,
        font=styles.FONT_HEADER,
        fg=styles.get_main(),
        bg=styles.BG_WHITE,
    )
    completion_label.pack()

    time_label = tk.Label(
        frame,
        text="Total Time: 00:00",
        font=styles.FONT_LABEL,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    )
    time_label.pack(pady=10)

    summary_label = tk.Label(
        frame,
        text="",
        font=styles.FONT_LABEL,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        justify=tk.LEFT,
    )
    summary_label.pack(pady=10)

    tk.Button(
        frame,
        text=log_btn_text,
        width=30,
        bg=styles.get_main(),
        fg="white",
        pady=10,
        command=on_open_log,
        font=styles.FONT_BUTTON,
    ).pack(pady=10)

    tk.Button(
        frame,
        text="Open Folder",
        width=30,
        bg=styles.get_main(),
        fg="white",
        pady=10,
        command=on_open_folder,
        font=styles.FONT_BUTTON,
    ).pack(pady=10)

    result = {
        "completion_label": completion_label,
        "time_label": time_label,
        "summary_label": summary_label,
    }

    # Extra labels (e.g. genre_label for Album Genre Tagger)
    for key in extra_labels or []:
        extra_label = tk.Label(
            frame, text="", bg=styles.BG_WHITE, fg=styles.FG_MAIN, font=styles.FONT_BODY
        )
        extra_label.pack(pady=(0, 10))
        result[key] = extra_label

    # Optional before/after audition row
    if on_play_original is not None:
        audition = add_audition_buttons(
            frame,
            on_play_original=on_play_original,
            on_play_result=(
                on_play_result if on_play_result is not None else on_play_original
            ),
        )
        result["play_original_btn"] = audition["play_original_btn"]
        result["play_result_btn"] = audition["play_result_btn"]
        result["audition_caption_var"] = audition["caption_var"]

    return result


def build_processing_tab(
    parent: tk.Frame,
    slot_vars: list[tk.StringVar] | None = None,
    stats_text: str = "Processed: 0 | Skipped: 0 | Errors: 0",
) -> dict[str, Any]:
    """
    Build the standard Processing tab layout.

    Args:
        parent:      The notebook tab frame.
        slot_vars:   List of StringVars — one per worker thread.
                     Pass None (or omit) for single-threaded tools — the
                     Active Workers panel is simply not shown.
        stats_text:  Initial text for the stats label.

    Returns:
        The widgets the tool drives, keyed by name::

            {
                'overall_status': tk.StringVar,
                'progress':       ttk.Progressbar,
                'stats_label':    tk.Label,
                'file_listbox':   tk.Listbox,
            }
    """
    frame = tk.Frame(parent, padx=15, pady=15, bg=styles.BG_WHITE)
    frame.pack(expand=True, fill="both")

    overall_status = tk.StringVar(value="Waiting...")
    tk.Label(
        frame,
        textvariable=overall_status,
        font=styles.FONT_LABEL_B,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(anchor="w")

    progress = ttk.Progressbar(
        frame,
        orient="horizontal",
        mode="determinate",
        style="Suite.Horizontal.TProgressbar",
    )
    progress.pack(fill="x", pady=(10, 20))

    stats_frame = tk.Frame(frame, bg=styles.BG_WHITE)
    stats_frame.pack(fill="x", pady=(0, 10))
    stats_label = tk.Label(
        stats_frame,
        text=stats_text,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
    )
    stats_label.pack(anchor="w")

    if slot_vars:
        worker_frame = tk.LabelFrame(
            frame,
            text="Active Workers",
            fg=styles.get_dark(),
            bg=styles.BG_WHITE,
            padx=10,
            pady=10,
        )
        worker_frame.pack(fill="x", pady=10)
        for i, var in enumerate(slot_vars):
            tk.Label(
                worker_frame,
                text=f"W{i + 1}:",
                font=styles.FONT_CAPTION_B,
                bg=styles.BG_WHITE,
                fg=styles.FG_SUB,
            ).grid(row=i, column=0, sticky="w")
            tk.Label(
                worker_frame,
                textvariable=var,
                font=styles.FONT_MONO,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
            ).grid(row=i, column=1, sticky="w", padx=10)

    file_listbox = tk.Listbox(
        frame,
        height=8,
        font=styles.FONT_MONO,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        highlightthickness=0,
        borderwidth=1,
        relief=tk.SOLID,
    )
    file_listbox.pack(fill="both", expand=True, pady=5)
    scrollbar = tk.Scrollbar(file_listbox, bg=styles.BG_WHITE)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    file_listbox.config(yscrollcommand=scrollbar.set)
    scrollbar.config(command=file_listbox.yview)

    return {
        "overall_status": overall_status,
        "progress": progress,
        "stats_label": stats_label,
        "file_listbox": file_listbox,
    }
