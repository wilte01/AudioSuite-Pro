"""
ui/results_tab.py
The Results tab's album report table.

Changed in 2.7.0: the tab shows the album plan's per-track table, the same rows
``refinery_album.csv`` records, so a run's numbers can be read without leaving
the window (F-S6).  The table is built here rather than in the shared builder
because it is the Refinery's own: no other tool plans an album.
Changed in 2.9.0: the shared Results tab is the shell's, so this module keeps
only the album table and the window adds it to the tab the shell built (C1).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any

from audio_suite_shared import styles

#: The album table's columns, in the order ``refinery_album.csv`` writes them.
ALBUM_COLUMNS: tuple[tuple[str, str], ...] = (
    ("file", "File"),
    ("album_lufs", "Album LUFS"),
    ("track_lufs", "Track LUFS"),
    ("track_tp", "True peak dBTP"),
    ("applied_gain_db", "Gain dB"),
    ("limited", "Limited"),
    ("deviation_lu", "From target LU"),
)


def build_album_table(parent: tk.Frame) -> dict[str, Any]:
    """Build the album report table under the standard results widgets.

    Args:
        parent: The notebook's Results tab frame.

    Returns:
        ``album_frame``, ``album_tree`` and ``album_caption``.  The frame is not
        packed: a run that planned no album has nothing to show, and the
        completion handler packs it only when it has rows.
    """
    panel = tk.Frame(parent, bg=styles.BG_WHITE, padx=40)

    caption = tk.Label(
        panel,
        text=(
            "Album report — every track measured once, before the run.  "
            "The same table is written to refinery_album.csv."
        ),
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        justify=tk.LEFT,
        anchor="w",
    )
    caption.pack(fill="x")

    columns = [key for key, _heading in ALBUM_COLUMNS]
    tree = ttk.Treeview(panel, columns=columns, show="headings", height=6)
    for key, heading in ALBUM_COLUMNS:
        tree.heading(key, text=heading)
        # The true-peak column is wider because its heading is the longest one:
        # at 110 px it was clipped to "True peak dBT", which reads as a
        # different unit.  Every other column stays at 110 so the seven of them
        # still fit the tab's width - a Treeview with no horizontal scrollbar
        # hides its last column rather than wrapping it.
        tree.column(
            key,
            width=200 if key == "file" else 120 if key == "track_tp" else 110,
            anchor="w" if key == "file" else "e",
            stretch=key == "file",
        )
    scroll = ttk.Scrollbar(panel, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)

    tree.pack(side=tk.LEFT, fill="x", expand=True)
    scroll.pack(side=tk.RIGHT, fill="y")

    return {"album_frame": panel, "album_tree": tree, "album_caption": caption}
