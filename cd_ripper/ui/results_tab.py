"""
cd_ripper/ui/results_tab.py — Results tab.
Style matches Music Format Converter results_tab.py.

Changed in 1.2.0: surfaces each track's EAC-style verification label (with
its AccurateRip confidence) and adds the manual "Re-rip flagged tracks"
action (PLAN_feature_expansion.md D30).
Changed in 2.1.4: eject and reveal go through ``core/drive_control`` - no
PowerShell command string, no raw ``subprocess.Popen`` (audit R-08, plan C3).
"""

import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from audio_suite_shared import styles
from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.secure_subprocess import run_secure_subprocess
from cd_ripper.core.drive_control import eject_drive, reveal_in_file_manager


class ResultsTab:
    """Results tab UI for CD Ripper."""

    def __init__(self, notebook: tk.Widget, state: dict[str, Any]) -> None:
        self.state = state
        self.frame = tk.Frame(notebook, bg=styles.BG_WHITE)
        self._build()

    def _build(self) -> None:
        outer = tk.Frame(self.frame, padx=30, pady=15, bg=styles.BG_WHITE)
        outer.pack(expand=True, fill="both")

        tk.Label(
            outer, text="Rip Complete!", font=styles.FONT_TITLE, bg=styles.BG_WHITE
        ).pack(pady=(0, 4))

        self._summary_lbl = tk.Label(
            outer,
            text="",
            font=styles.FONT_LABEL_B,
            bg=styles.BG_WHITE,
            fg=styles.get_main(),
        )
        self._summary_lbl.pack(anchor="w", pady=(0, 8))

        # Results treeview
        tree_frame = tk.Frame(outer, bg=styles.BG_WHITE, relief=tk.RIDGE, bd=1)
        tree_frame.pack(fill="both", expand=True, pady=(0, 8))

        cols = ("#", "Title", "Output File", "Status")
        self._tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=12)
        for col, w in zip(cols, [40, 220, 300, 100]):
            self._tree.heading(col, text=col)
            self._tree.column(col, width=w, minwidth=30)

        self._tree.tag_configure("ok", foreground="#2e9e4f")
        self._tree.tag_configure("fail", foreground="#cc3333")

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self._tree.bind("<Double-1>", self._on_row_double)

        # Buttons
        btn_row = tk.Frame(outer, bg=styles.BG_WHITE)
        btn_row.pack(fill="x", pady=(0, 4))
        tk.Button(
            btn_row,
            text="📂  Open Output Folder",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_LABEL_B,
            command=self._open_folder,
        ).pack(side="left")

        tk.Button(
            btn_row,
            text="⏏  Eject Disc",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_LABEL_B,
            command=self._eject,
        ).pack(side="left", padx=(8, 0))

        self._rerip_btn = tk.Button(
            btn_row,
            text="⟲  Re-rip flagged tracks",
            bg="#4a7a9b",
            fg="white",
            font=styles.FONT_LABEL_B,
            command=self._rerip,
            state="disabled",
        )
        self._rerip_btn.pack(side="left", padx=(8, 0))

        tk.Label(
            outer,
            text=(
                "Double-click a row to reveal the file in Explorer. "
                "Re-rip runs only the flagged tracks — nothing is retried "
                "automatically."
            ),
            font=styles.FONT_CAPTION,
            fg="gray",
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

    def refresh(self) -> None:
        for row in self._tree.get_children():
            self._tree.delete(row)

        results = self.state.get("rip_results", [])
        tracks = {t["number"]: t for t in self.state.get("tracks", [])}

        ok = sum(1 for r in results if r["success"])
        fail = len(results) - ok

        # Aggregate verification outcomes for the summary line.
        status_counts: dict[str, int] = {}
        for r in results:
            if r["success"] and r["error"]:
                status_counts[r["error"]] = status_counts.get(r["error"], 0) + 1

        if status_counts:
            parts = [
                f"{count} {status}" for status, count in sorted(status_counts.items())
            ]
            summary = (
                f"Rip complete  —  {ok} succeeded ({', '.join(parts)}),  {fail} failed"
            )
        else:
            summary = f"Rip complete  —  {ok} succeeded,  {fail} failed"

        self._rerip_btn.configure(
            state="normal" if self.flagged_numbers() else "disabled"
        )

        self._summary_lbl.configure(
            text=summary,
            fg=styles.get_main() if fail == 0 else "#cc3333",
        )

        for r in sorted(results, key=lambda x: x["number"]):
            num = r["number"]
            title = tracks.get(num, {}).get("title", f"Track {num:02d}")
            fname = os.path.basename(r["path"]) if r["path"] else "—"
            if r["success"] and r["error"]:
                status = f"✓  {r['error']}"
            elif r["success"]:
                status = "✓  OK"
            else:
                status = f"✗  {r['error']}"
            tag = "ok" if r["success"] else "fail"
            self._tree.insert(
                "", "end", iid=str(num), tags=(tag,), values=(num, title, fname, status)
            )

    def flagged_numbers(self) -> list[int]:
        """The track numbers a re-rip may be offered for, in disc order.

        A failed track is one whose row carries no output file: a failed
        encode, a read error, or an AccurateRip mismatch (which deliberately
        never writes a file). Successful rows are never flagged, whatever
        their verification label says.

        Returns:
            Ascending track numbers with an unsuccessful result.
        """
        return sorted(
            int(r["number"])
            for r in self.state.get("rip_results", [])
            if not r.get("success")
        )

    def _rerip(self) -> None:
        """Hand the flagged track numbers to the app's re-rip action."""
        numbers = self.flagged_numbers()
        callback = self.state.get("on_rerip")
        if not numbers or not callable(callback):
            return
        callback(numbers)

    def _open_folder(self) -> None:
        out_dir = self.state.get("out_dir", "")
        if out_dir and os.path.isdir(out_dir):
            if os.name == "nt":
                os.startfile(out_dir)
            else:
                run_secure_subprocess(
                    "xdg-open", [out_dir], capture_output=True, check=False
                )

    def _eject(self) -> None:
        drive = self.state.get("drive", "")
        if not drive:
            return
        try:
            eject_drive(drive)
        except AudioSuiteError as exc:
            # A tray that will not open is worth saying out loud: the button
            # looks like it did nothing otherwise.
            messagebox.showerror("Eject Failed", str(exc), parent=self.frame)

    def _on_row_double(self, event: Any) -> None:
        item = self._tree.identify_row(event.y)
        if not item:
            return
        r = next(
            (x for x in self.state.get("rip_results", []) if x["number"] == int(item)),
            None,
        )
        if r and r["path"] and os.path.exists(r["path"]):
            try:
                reveal_in_file_manager(r["path"])
            except AudioSuiteError as exc:
                messagebox.showerror("Cannot Open Folder", str(exc), parent=self.frame)
