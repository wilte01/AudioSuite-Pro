"""
cd_ripper/ui/drive_config_panel.py — Drive selection, disc read, C2 diagnostic.
"""

import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from audio_suite_shared import styles
from audio_suite_shared.exceptions import AudioIOError, AudioSuiteError
from cd_ripper.core.cd_ripper_config import get_log_path
from cd_ripper.core.disc import (
    DiscInfo,
    apply_release,
    list_cd_drives,
    platform_supported,
    read_disc,
)
from cd_ripper.core.rip_log import write_log_line
from cd_ripper.core.track_processor import C2DiagnosticResult


class DriveConfigPanel:
    """Drive configuration sub-panel for CD Ripper setup."""

    def __init__(
        self,
        parent: Any,
        state: dict[str, Any],
        *,
        on_disc_read_cb: Any = None,
        on_release_applied_cb: Any = None,
        set_proceed_enabled: Any = None,
    ) -> None:
        self.state = state
        self._on_disc_read_cb = on_disc_read_cb
        self._on_release_applied_cb = on_release_applied_cb
        self._set_proceed_enabled = set_proceed_enabled
        self._disc_info: DiscInfo | None = None
        self.frame = tk.Frame(parent, bg=styles.BG_WHITE)
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self) -> None:
        # Drive selection row
        tk.Label(
            self.frame,
            text="CD Drive:",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            font=styles.FONT_BODY,
        ).pack(anchor="w")
        drive_row = tk.Frame(self.frame, bg=styles.BG_WHITE)
        drive_row.pack(fill="x", pady=3)

        self._drive_var = tk.StringVar()
        self._drive_combo = ttk.Combobox(
            drive_row,
            textvariable=self._drive_var,
            font=styles.FONT_BODY,
            width=10,
            state="readonly",
        )
        self._drive_combo.pack(side="left", padx=(0, 5))
        tk.Button(
            drive_row,
            text="↻ Refresh",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self.refresh_drives,
        ).pack(side="left", padx=(0, 8))
        self._read_btn = tk.Button(
            drive_row,
            text="📀 Read Disc",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_LABEL_B,
            command=self._read_disc_threaded,
        )
        self._read_btn.pack(side="left")
        self._c2_btn = tk.Button(
            drive_row,
            text="🔍 Test C2 Reliability",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_LABEL_B,
            command=self._test_c2_threaded,
        )
        self._c2_btn.pack(side="left", padx=(8, 0))
        self._offset_btn = tk.Button(
            drive_row,
            text="📏 Detect Read Offset",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_LABEL_B,
            command=self._detect_offset_threaded,
        )
        self._offset_btn.pack(side="left", padx=(8, 0))
        self._status_lbl = tk.Label(
            drive_row,
            text="",
            font=styles.FONT_BODY_I,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
        )
        self._status_lbl.pack(side="left", padx=10)

        self._read_progress = ttk.Progressbar(
            self.frame, mode="indeterminate", style="Suite.Horizontal.TProgressbar"
        )

        # MusicBrainz release selector
        tk.Label(
            self.frame,
            text="MusicBrainz Matches:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(8, 0))
        mb_row = tk.Frame(self.frame, bg=styles.BG_WHITE)
        mb_row.pack(fill="x", pady=3)
        self._release_var = tk.StringVar()
        self._release_combo = ttk.Combobox(
            mb_row,
            textvariable=self._release_var,
            font=styles.FONT_BODY,
            state="readonly",
            width=60,
        )
        self._release_combo.pack(side="left", fill="x", expand=True, padx=(0, 5))
        tk.Button(
            mb_row,
            text="Apply",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self._apply_selected_release,
        ).pack(side="left")

    # ── Drive helpers ─────────────────────────────────────────────────────────

    def set_status(self, msg: str, error: bool = False) -> None:
        self._status_lbl.configure(text=msg, fg="#cc0000" if error else styles.FG_SUB)

    def refresh_drives(self) -> None:
        if not platform_supported():
            self._drive_combo["values"] = []
            self.set_status(
                "CD ripping requires Windows and is not supported on this OS.",
                error=True,
            )
            return
        drives = list_cd_drives()
        self._drive_combo["values"] = drives
        if drives:
            self._drive_combo.current(0)
            self.set_status("Drive(s) found. Insert disc and click Read Disc.")
        else:
            self.set_status("No CD drive detected.", error=True)

    # ── C2 reliability diagnostic ─────────────────────────────────────────────

    def _test_c2_threaded(self) -> None:
        drive = self._drive_var.get()
        if not drive:
            messagebox.showwarning("No Drive", "Please select a CD drive first.")
            return
        self._c2_btn.configure(state="disabled")
        self.set_status("Testing C2 reliability… (reads a track twice)")
        threading.Thread(
            target=self._run_c2_diagnostic, args=(drive,), daemon=True
        ).start()

    def _run_c2_diagnostic(self, drive: str) -> None:
        from cd_ripper.core.drive_handler import SECTORS_PER_SEC
        from cd_ripper.core.ripper import (
            diagnose_c2_reliability,
            read_toc,
        )

        try:
            drive_letter = drive.rstrip("/\\").rstrip(":")
            toc = read_toc(drive_letter, write_log_line)
            if not toc:
                raise AudioIOError(
                    "Could not read the disc TOC -- insert a disc and click "
                    "Read Disc first."
                )
            first_track = toc[0]
            test_lba = first_track["start_lba"] + (SECTORS_PER_SEC * 2)
            result = diagnose_c2_reliability(
                drive_letter, test_lba, write_log_line, sectors=8
            )
        except (AudioSuiteError, OSError, RuntimeError) as e:
            error_message = str(e)
            self.frame.after(
                0, lambda: self._on_c2_diagnostic_done(None, error_message)
            )
            return
        self.frame.after(0, lambda: self._on_c2_diagnostic_done(result, None))

    def _on_c2_diagnostic_done(
        self, result: C2DiagnosticResult | None, error: str | None
    ) -> None:
        self._c2_btn.configure(state="normal")

        if error:
            self.set_status(f"C2 test failed: {error}", error=True)
            messagebox.showerror("C2 Diagnostic Failed", error)
            return

        assert result is not None
        if result.c2_appears_honest:
            summary = (
                "Drive appears to populate C2 error flags rather than "
                "zero-filling them (weak positive evidence -- not certainty)."
            )
        elif result.c2_flags_all_zero:
            summary = (
                "C2 field was all-zero on this test. That's consistent with "
                "either a clean read or a drive that doesn't really support "
                "C2 -- this result alone can't tell them apart. Treat C2 as "
                "unreliable on this drive unless a later test on a "
                "known-bad disc returns non-zero flags."
            )
        else:
            summary = (
                "Audio data differed between the two test reads -- this "
                "location wasn't a valid test spot (or there's a real read "
                "problem here). Try again on a different disc/track."
            )

        self.set_status(summary, error=not result.c2_appears_honest)
        messagebox.showinfo(
            "C2 Diagnostic Result",
            f"{summary}\n\nFull detail written to:\n{get_log_path()}",
        )

    # ── Read-offset detection ─────────────────────────────────────────────────

    def _detect_offset_threaded(self) -> None:
        drive = self._drive_var.get()
        if not drive:
            messagebox.showwarning("No Drive", "Please select a CD drive first.")
            return
        self._offset_btn.configure(state="disabled")
        self.set_status(
            "Measuring read offset… (reads the disc twice — takes a few minutes)"
        )
        threading.Thread(
            target=self._run_offset_detection, args=(drive,), daemon=True
        ).start()

    def _run_offset_detection(self, drive: str) -> None:
        from audio_suite_shared.exceptions import AudioSuiteError
        from cd_ripper.core.offset_detect import run_read_offset_detection

        try:
            offset = run_read_offset_detection(drive, write_log_line)
        except (AudioSuiteError, OSError, RuntimeError, ValueError) as e:
            error_message = str(e)
            self.frame.after(
                0, lambda: self._on_offset_detection_done(None, error_message)
            )
            return
        self.frame.after(0, lambda: self._on_offset_detection_done(offset, None))

    def _on_offset_detection_done(self, offset: int | None, error: str | None) -> None:
        self._offset_btn.configure(state="normal")

        if error is not None:
            self.set_status(f"Read-offset detection failed: {error}", error=True)
            messagebox.showerror("Read-Offset Detection Failed", error)
            return

        assert offset is not None
        drive = self._drive_var.get().rstrip(":/\\")
        summary = (
            f"Drive read offset: {offset:+d} frame(s).\n\n"
            "Stored for this drive — every future rip applies it "
            "automatically. You only need to do this once per drive."
        )
        self.set_status(f"Read offset {offset:+d} frames stored for drive {drive}.")
        messagebox.showinfo(
            "Read-Offset Detection Result",
            f"{summary}\n\nFull detail written to:\n{get_log_path()}",
        )

    # ── Disc read ─────────────────────────────────────────────────────────────

    def _read_disc_threaded(self) -> None:
        drive = self._drive_var.get()
        if not drive:
            messagebox.showwarning("No Drive", "Please select a CD drive first.")
            return
        self._read_btn.configure(state="disabled")
        if self._set_proceed_enabled:
            self._set_proceed_enabled(False)
        self._read_progress.pack(fill="x", pady=2)
        self._read_progress.start(12)
        self.set_status("Reading disc…")
        threading.Thread(
            target=lambda: self.frame.after(
                0, lambda: self._on_disc_read(read_disc(self._drive_var.get()))
            ),
            daemon=True,
        ).start()

    def _on_disc_read(self, info: DiscInfo) -> None:
        self._read_progress.stop()
        self._read_progress.pack_forget()
        self._read_btn.configure(state="normal")
        self._disc_info = info

        if info.error and not info.tracks:
            self.set_status(info.error, error=True)
            messagebox.showerror("Disc Read Error", info.error)
            return

        if info.error:
            self.set_status(f"Warning: {info.error}", error=True)
        else:
            self.set_status(
                f"Found {len(info.tracks)} track(s)."
                + (
                    " MusicBrainz match found."
                    if info.release_info
                    else " No MusicBrainz match."
                )
            )

        self._release_combo["values"] = (
            [self._release_label(r) for r in info.mb_releases]
            if info.mb_releases
            else ["(No MusicBrainz match — enter metadata manually)"]
        )
        self._release_combo.current(0)

        if self._on_disc_read_cb:
            self._on_disc_read_cb(info)

        self.state.update(
            {
                "tracks": info.tracks,
                "disc_id": info.disc_id,
                "release_info": info.release_info,
                "drive": info.drive,
            }
        )

        if self._set_proceed_enabled:
            self._set_proceed_enabled(True)

    def _release_label(self, release: dict[str, Any]) -> str:
        artist = "".join(
            a.get("artist", {}).get("name", "") if isinstance(a, dict) else a
            for a in release.get("artist-credit", [])
        )
        date = release.get("date", "")[:4]
        country = release.get("country", "")
        return f"{artist} – {release.get('title', '?')}  ({date})  [{country}]"

    def _apply_selected_release(self) -> None:
        if not self._disc_info:
            return
        idx = self._release_combo.current()
        if 0 <= idx < len(self._disc_info.mb_releases):
            apply_release(self._disc_info, self._disc_info.mb_releases[idx])
            self.state["tracks"] = self._disc_info.tracks
            if self._on_release_applied_cb:
                self._on_release_applied_cb()
