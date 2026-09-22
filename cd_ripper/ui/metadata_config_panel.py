"""
cd_ripper/ui/metadata_config_panel.py — Album metadata and track list editing.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any

from audio_suite_shared import styles
from cd_ripper.core.disc import format_duration


class MetadataConfigPanel:
    """Album metadata and track list sub-panel."""

    def __init__(self, parent: tk.Widget) -> None:
        self._tracks: list[dict[str, Any]] = []
        self.frame = tk.Frame(parent, bg=styles.BG_WHITE)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Album metadata
        tk.Label(
            self.frame,
            text="Album Metadata:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(8, 0))
        meta_frame = tk.Frame(self.frame, bg=styles.BG_WHITE)
        meta_frame.pack(fill="x", pady=3)
        meta_frame.columnconfigure(1, weight=1)

        self._album_var = tk.StringVar()
        self._artist_var = tk.StringVar()
        self._year_var = tk.StringVar()
        self._genre_var = tk.StringVar()

        for i, (label, var) in enumerate(
            [
                ("Album:", self._album_var),
                ("Album Artist:", self._artist_var),
                ("Year:", self._year_var),
                ("Genre:", self._genre_var),
            ]
        ):
            tk.Label(
                meta_frame,
                text=label,
                width=14,
                anchor="e",
                font=styles.FONT_BODY,
                fg=styles.FG_MAIN,
                bg=styles.BG_WHITE,
            ).grid(row=i, column=0, sticky="e", padx=(0, 6), pady=2)
            tk.Entry(
                meta_frame,
                textvariable=var,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                insertbackground=styles.FG_MAIN,
            ).grid(row=i, column=1, sticky="ew", pady=2)

        tk.Button(
            meta_frame,
            text="Apply to all tracks",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self.apply_album_to_tracks,
        ).grid(row=4, column=1, sticky="w", pady=(4, 0))

        # Track list
        tk.Label(
            self.frame,
            text="Tracks (double-click Title or Artist to edit):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(8, 0))
        tree_frame = tk.Frame(self.frame, bg=styles.BG_WHITE)
        tree_frame.pack(fill="x", pady=3)

        cols = ("#", "Title", "Artist", "Duration")
        self._tree = ttk.Treeview(
            tree_frame, columns=cols, show="headings", selectmode="extended", height=6
        )
        for col, w in zip(cols, [40, 260, 200, 65]):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, minwidth=30)

        tvsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=tvsb.set)
        self._tree.pack(side="left", fill="x", expand=True)
        tvsb.pack(side="right", fill="y")
        self._tree.bind("<Double-1>", self._on_track_double_click)

    # ── Metadata helpers ──────────────────────────────────────────────────────

    def populate_album_fields(self, tracks: list[dict[str, Any]]) -> None:
        if not tracks:
            return
        t = tracks[0]
        self._album_var.set(t.get("album", ""))
        self._artist_var.set(t.get("artist", ""))
        self._year_var.set(t.get("year", ""))
        self._genre_var.set(t.get("genre", ""))

    def apply_album_to_tracks(self) -> None:
        album = self._album_var.get()
        artist = self._artist_var.get()
        year = self._year_var.get()
        genre = self._genre_var.get()
        for t in self._tracks:
            t.update({"album": album, "year": year, "genre": genre})
            if artist:
                t["artist"] = artist
        self.populate_tracks(self._tracks)

    # ── Track list ────────────────────────────────────────────────────────────

    def populate_tracks(self, tracks: list[dict[str, Any]]) -> None:
        self._tracks = tracks
        for row in self._tree.get_children():
            self._tree.delete(row)
        for t in tracks:
            self._tree.insert(
                "",
                "end",
                iid=str(t["number"]),
                values=(
                    t["number"],
                    t.get("title", ""),
                    t.get("artist", ""),
                    format_duration(t.get("duration", 0)),
                ),
            )

    def _on_track_double_click(self, event: tk.Event[ttk.Treeview]) -> None:
        item = self._tree.identify_row(event.y)
        col = self._tree.identify_column(event.x)
        if not item or col not in ("#2", "#3"):
            return
        col_key = ["number", "title", "artist", "duration"][int(col[1:]) - 1]
        if col_key in ("number", "duration"):
            return
        num = int(item)
        track = next((t for t in self._tracks if t["number"] == num), None)
        if not track:
            return
        bbox = self._tree.bbox(item, col)
        if not bbox or isinstance(bbox, str):
            return
        x, y, w, h = bbox
        popup = tk.Entry(
            self._tree,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        )
        popup.insert(0, track.get(col_key, ""))
        popup.select_range(0, "end")
        popup.place(x=x, y=y, width=w, height=h)
        popup.focus_set()

        def save(_e: Any = None) -> None:
            track[col_key] = popup.get()
            self.populate_tracks(self._tracks)
            popup.destroy()

        popup.bind("<Return>", save)
        popup.bind("<FocusOut>", save)
        popup.bind("<Escape>", lambda _: popup.destroy())
