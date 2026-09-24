"""

cd_ripper/ui/rip_tab.py — Rip tab.
Style matches Music Format Converter processing_tab.py.
"""

import os
import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, messagebox, ttk
from typing import Any

from audio_suite_shared import styles
from audio_suite_shared.cue_split import split_cue_file
from cd_ripper.core.rip_log import write_log_line
from cd_ripper.core.ripper import RipSession


class _TrackRow:
    def __init__(self, parent: Any, track: dict[str, Any], row: int) -> None:
        num = track["number"]
        title = track.get("title", f"Track {num:02d}")

        tk.Label(
            parent,
            text=f"{num:02d}",
            width=4,
            anchor="e",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).grid(row=row, column=0, padx=(0, 6), pady=2, sticky="e")

        tk.Label(
            parent,
            text=title[:42],
            width=42,
            anchor="w",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).grid(row=row, column=1, pady=2, sticky="w")

        self.prog = ttk.Progressbar(
            parent,
            mode="determinate",
            length=180,
            style="Suite.Horizontal.TProgressbar",
        )
        self.prog.grid(row=row, column=2, padx=8, pady=2)

        self.status_lbl = tk.Label(
            parent,
            text="Waiting",
            anchor="w",
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
            font=styles.FONT_BODY,
        )
        self.status_lbl.grid(row=row, column=3, pady=2, sticky="w", padx=(0, 8))

    def set_progress(self, pct: int, msg: str) -> None:
        self.prog["value"] = pct
        self.status_lbl.configure(text=msg)

    def set_done(self, success: bool, msg: str = "") -> None:
        self.prog["value"] = 100 if success else 0
        colour = "#2e9e4f" if success else "#cc3333"
        if success and msg:
            # msg carries the verification outcome (VERIFIED / NO ENTRY / OFFLINE)
            text = f"✓  {msg}"
        elif success:
            text = "✓  Done"
        else:
            text = f"✗  {msg}"
        self.status_lbl.configure(text=text, foreground=colour)

    def set_active(self) -> None:
        self.status_lbl.configure(text="Ripping…", foreground=styles.get_main())


class RipTab:
    """Rip tab UI for CD Ripper."""

    def __init__(
        self, notebook: Any, state: dict[str, Any], done_cb: Callable[[], None]
    ) -> None:
        self.state = state
        self.done_cb = done_cb
        self.frame = tk.Frame(notebook, bg=styles.BG_WHITE)
        self._session: RipSession | None = None
        self._rows: dict[int, _TrackRow] = {}
        self._completed = 0
        self._total = 0
        self._build()

    def _build(self) -> None:
        outer = tk.Frame(self.frame, padx=30, pady=15, bg=styles.BG_WHITE)
        outer.pack(expand=True, fill="both")

        tk.Label(
            outer,
            text="CD Ripper — Ripping Progress",
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=(0, 6))

        self._summary_lbl = tk.Label(
            outer, text="", font=styles.FONT_BODY, bg=styles.BG_WHITE, fg=styles.FG_SUB
        )
        self._summary_lbl.pack(anchor="w", pady=(0, 6))

        # Button row
        btn_row = tk.Frame(outer, bg=styles.BG_WHITE)
        btn_row.pack(fill="x", pady=(0, 8))

        self._start_btn = tk.Button(
            btn_row,
            text="▶  START RIPPING",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_LABEL_B,
            command=self._start,
        )
        self._start_btn.pack(side="left")

        self._cancel_btn = tk.Button(
            btn_row,
            text="⛔  Cancel",
            bg="#888888",
            fg="white",
            font=styles.FONT_LABEL,
            command=self._cancel,
            state="disabled",
        )
        self._cancel_btn.pack(side="left", padx=(8, 0))

        self._split_btn = tk.Button(
            btn_row,
            text="Split CUE Image...",
            bg="#4a7a9b",
            fg="white",
            font=styles.FONT_LABEL,
            command=self._split_cue,
        )
        self._split_btn.pack(side="left", padx=(8, 0))

        # Scrollable track grid
        track_outer = tk.Frame(outer, bg=styles.BG_WHITE, relief=tk.RIDGE, bd=1)
        track_outer.pack(fill="both", expand=True, pady=(0, 8))

        canvas = tk.Canvas(track_outer, bg=styles.BG_WHITE, highlightthickness=0)
        vsb = ttk.Scrollbar(track_outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        self._scroll_frame = tk.Frame(canvas, bg=styles.BG_WHITE)
        self._canvas_window = canvas.create_window(
            (0, 0), window=self._scroll_frame, anchor="nw"
        )
        self._scroll_frame.bind(
            "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.bind(
            "<Configure>",
            lambda e: canvas.itemconfig(self._canvas_window, width=e.width),
        )
        self._canvas = canvas

        # Overall progress
        tk.Frame(outer, bg="#cccccc", height=1).pack(fill="x", pady=(0, 6))
        overall_row = tk.Frame(outer, bg=styles.BG_WHITE)
        overall_row.pack(fill="x", pady=(0, 4))
        tk.Label(
            overall_row,
            text="Overall:",
            font=styles.FONT_BODY_B,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
        ).pack(side="left")
        self._overall_prog = ttk.Progressbar(
            overall_row,
            mode="determinate",
            length=380,
            style="Suite.Horizontal.TProgressbar",
        )
        self._overall_prog.pack(side="left", padx=8)
        self._overall_lbl = tk.Label(
            overall_row, text="", fg="gray", font=styles.FONT_BODY, bg=styles.BG_WHITE
        )
        self._overall_lbl.pack(side="left")

    # ── Prepare ───────────────────────────────────────────────────────────────

    def prepare(self) -> None:
        for w in self._scroll_frame.winfo_children():
            w.destroy()
        self._rows.clear()
        self._overall_prog["value"] = 0
        self._overall_lbl.configure(text="")

        tracks = self.state.get("tracks", [])
        fmt = self.state.get("fmt", "FLAC")
        out_dir = self.state.get("out_dir", "")

        self._summary_lbl.configure(
            text=f"{len(tracks)} track(s)  →  {fmt}  →  {out_dir}"
        )

        # Column headers
        for col, text, col_w in [
            (0, "#", 4),
            (1, "Title", 42),
            (2, "Progress", 0),
            (3, "Status", 0),
        ]:
            tk.Label(
                self._scroll_frame,
                text=text,
                font=styles.FONT_BODY_B,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                width=col_w if col_w else 0,
                anchor="w",
            ).grid(row=0, column=col, padx=(0, 6), pady=(0, 3), sticky="w")

        for i, track in enumerate(tracks):
            row = _TrackRow(self._scroll_frame, track, i + 1)
            self._rows[track["number"]] = row

        self._start_btn.configure(state="normal")
        self._cancel_btn.configure(state="disabled")
        self._split_btn.configure(state="normal")

    # ── Start / Cancel ────────────────────────────────────────────────────────

    def _start(self) -> None:
        tracks = self.state.get("tracks", [])
        if not tracks:
            return

        self._start_btn.configure(state="disabled")
        self._cancel_btn.configure(state="normal")
        self._split_btn.configure(state="disabled")
        self._completed = 0
        self._total = len(tracks)
        self.state["rip_results"] = []

        self._session = RipSession(
            drive=self.state.get("drive", ""),
            tracks=tracks,
            out_dir=self.state.get("out_dir", ""),
            fmt=self.state.get("fmt", "FLAC"),
            quality_args=self.state.get("quality_args"),
            progress_cb=self._on_progress,
            track_done_cb=self._on_track_done,
            session_done_cb=self._on_session_done,
            ffmpeg_path=self.state.get("ffmpeg_path", "ffmpeg"),
            log_cb=write_log_line,
            write_cue=self.state.get("write_cue", False),
            verify_mode=self.state.get("verify_mode", "twice"),
        )
        assert self._session is not None
        self._session.start()

    def _cancel(self) -> None:
        if self._session:
            self._session.cancel()
        self._cancel_btn.configure(state="disabled")
        self._overall_lbl.configure(text="Cancelling…")

    def _split_cue(self) -> None:
        """Split a single-file audio image into tracks using a CUE sheet."""
        filename = filedialog.askopenfilename(
            title="Select a CUE sheet",
            filetypes=[("CUE sheets", "*.cue"), ("All files", "*.*")],
        )
        if not filename:
            return
        out_dir = self.state.get("out_dir", "")
        if not out_dir or not os.path.isdir(out_dir):
            messagebox.showwarning(
                "Output Folder Required",
                "Set an Output Directory on the Setup tab before splitting.",
                parent=self.frame,
            )
            return
        self._split_btn.configure(state="disabled")

        def _run() -> None:
            try:
                written = split_cue_file(
                    filename, out_dir, progress_cb=self._on_split_progress
                )
            except Exception as exc:  # surface any split failure in a dialog
                self.frame.after(0, self._on_split_error, exc)
            else:
                self.frame.after(0, self._on_split_done, written)

        threading.Thread(target=_run, daemon=True).start()

    def _on_split_progress(self, msg: str) -> None:
        def _ui() -> None:
            self._overall_lbl.configure(text=msg)

        self.frame.after(0, _ui)

    def _on_split_done(self, written: list[str]) -> None:
        self._split_btn.configure(state="normal")
        self._overall_lbl.configure(text=f"Split complete — {len(written)} tracks")
        messagebox.showinfo(
            "Split Complete",
            f"Split {len(written)} track(s).",
            parent=self.frame,
        )

    def _on_split_error(self, exc: Exception) -> None:
        self._split_btn.configure(state="normal")
        self._overall_lbl.configure(text="")
        messagebox.showerror("Split Failed", str(exc), parent=self.frame)

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_progress(self, track_num: int, pct: int, msg: str) -> None:
        def _ui() -> None:
            row = self._rows.get(track_num)
            if row:
                row.set_progress(pct, msg)

        self.frame.after(0, _ui)

    def _on_track_done(
        self, track_num: int, success: bool, out_path: str, error: str
    ) -> None:
        def _ui() -> None:
            row = self._rows.get(track_num)
            if row:
                row.set_done(success, error)
            self._completed += 1
            pct = int(self._completed / self._total * 100)
            self._overall_prog["value"] = pct
            self._overall_lbl.configure(
                text=f"{self._completed} / {self._total} tracks"
            )
            self.state["rip_results"].append(
                {
                    "number": track_num,
                    "success": success,
                    "path": out_path,
                    "error": error,
                }
            )

        self.frame.after(0, _ui)

    def _on_session_done(self) -> None:
        def _ui() -> None:
            self._cancel_btn.configure(state="disabled")
            self._start_btn.configure(state="disabled")
            self._split_btn.configure(state="normal")
            self._overall_lbl.configure(text="Complete!")
            self.done_cb()

        self.frame.after(0, _ui)
