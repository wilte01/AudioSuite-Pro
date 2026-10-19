"""
processing_tab.py
Processing tab for ReplayGain Analyzer.

Changed in 1.4.0: the slot-panel docstring no longer claims a fixed count; the
grid follows ``DEFAULT_MAX_WORKERS`` (D67).

Builds the progress bar, per-worker status panel, and the live results
treeview.  No business logic — purely view.
"""

import tkinter as tk
from tkinter import ttk

from audio_suite_shared import styles


def build(parent: tk.Frame, slot_vars: list[tk.StringVar]) -> dict[str, object]:
    """
    Populate the Processing tab widgets.

    Args:
        parent:    Container frame provided by the notebook.
        slot_vars: List of Tk StringVars, one per worker slot.

    Returns:
        Dictionary with keys:
            'overall_status' -> tk.StringVar  (overall status text)
            'progress'       -> ttk.Progressbar
            'stats_label'    -> tk.Label      (processed/errors counter)
            'tree'           -> ttk.Treeview  (per-file results)
    """
    frame = tk.Frame(parent, padx=15, pady=15, bg=styles.BG_APP)
    frame.pack(expand=True, fill="both")

    overall_status = tk.StringVar(value="Waiting...")
    tk.Label(
        frame,
        textvariable=overall_status,
        font=styles.FONT_LABEL_B,
        bg=styles.BG_APP,
        fg=styles.FG_MAIN,
    ).pack(anchor="w")

    progress = ttk.Progressbar(
        frame,
        orient="horizontal",
        mode="determinate",
        style="Suite.Horizontal.TProgressbar",
    )
    progress.pack(fill="x", pady=(10, 20))

    stats_frame = tk.Frame(frame, bg=styles.BG_APP)
    stats_frame.pack(fill="x", pady=(0, 10))
    stats_label = tk.Label(
        stats_frame,
        text="Processed: 0 | Errors: 0",
        font=styles.FONT_BODY,
        bg=styles.BG_APP,
        fg=styles.FG_SUB,
    )
    stats_label.pack(anchor="w")

    # ── Worker status panel ───────────────────────────────────────────────────
    worker_frame = tk.LabelFrame(
        frame,
        text="Active Workers",
        fg=styles.get_dark(),
        bg=styles.BG_APP,
        padx=10,
        pady=10,
    )
    worker_frame.pack(fill="x", pady=10)
    for i, var in enumerate(slot_vars):
        tk.Label(
            worker_frame,
            text=f"W{i + 1}:",
            font=styles.FONT_CAPTION_B,
            bg=styles.BG_APP,
            fg=styles.FG_SUB,
        ).grid(row=i, column=0, sticky="w")
        tk.Label(
            worker_frame,
            textvariable=var,
            font=styles.FONT_MONO,
            bg=styles.BG_APP,
            fg=styles.FG_MAIN,
        ).grid(row=i, column=1, sticky="w", padx=10)

    # ── Results treeview ──────────────────────────────────────────────────────
    _style = ttk.Style()
    _style.configure(
        "Suite.Treeview",
        font=styles.FONT_BODY,
        background=styles.BG_APP,
        foreground=styles.FG_MAIN,
        fieldbackground=styles.BG_APP,
    )
    _style.configure(
        "Suite.Treeview.Heading",
        font=styles.FONT_BODY_B,
        background=styles.BG_APP,
        foreground=styles.FG_MAIN,
    )
    _style.map(
        "Suite.Treeview",
        background=[("selected", styles.get_dark())],
        foreground=[("selected", "white")],
    )

    cols = ("File", "Track LUFS", "Track Gain", "Album Gain", "Status")
    tree = ttk.Treeview(
        frame, columns=cols, show="headings", height=10, style="Suite.Treeview"
    )
    for col in cols:
        tree.heading(col, text=col)
        tree.column(col, anchor="center", width=100)
    tree.column("File", width=250, anchor="w")

    scrollbar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scrollbar.set)
    tree.pack(side=tk.LEFT, fill="both", expand=True, pady=5)
    scrollbar.pack(side=tk.RIGHT, fill="y")

    return {
        "overall_status": overall_status,
        "progress": progress,
        "stats_label": stats_label,
        "tree": tree,
    }
