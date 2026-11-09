"""app.py — the CUE Sheet Generator window.

The window is a ``SuiteApp``: the shell supplies the Help bar, the notebook,
the Processing tab and the Results tab, and this module supplies the Setup tab,
the run and the three callback seams.  The run happens on a worker thread and
hands every result to the Tk thread through a ``SimpleQueue`` — a worker thread
that called ``root.after`` (or any widget method) would raise on 3.14 and leave
the window waiting for a result that never arrives.

Changed in 2.6.0: new module (PLAN_2026-11-03_2.6.0_feature_wave_2.md F-E8).
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox
from typing import Any

from audio_suite_shared import styles, suite_config
from audio_suite_shared.cli_helpers import was_launched_from_driver
from audio_suite_shared.cue_generator import scan_audio_files
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.ui_driver_controls import DriverControlsPanel

from .core.export import default_output, report_name, run_export
from .utils import cli_args

logger = logging.getLogger(__name__)

LIVE_MODE = "Live Update"
DRY_MODE = "Dry Run"
RUN_MODES = (LIVE_MODE, DRY_MODE)


class CueSheetApp(SuiteApp):
    """Write one CUE sheet describing a folder's track files."""

    title = "CUE Sheet Generator"
    window_key = "cue_sheet_window"
    program_name = "cue_sheet"
    guide_name = "CUE_Sheet_Generator_User_Guide.docx"
    completion_text = "CUE Sheet Written!"

    def __init__(
        self,
        root: tk.Tk,
        *,
        directory: str = "",
        output: str = "",
        album_title: str = "",
        album_artist: str = "",
        dry_run: bool = False,
    ) -> None:
        self.folder_path = tk.StringVar(value=suite_config.load_last_directory())
        self.output_path = tk.StringVar(value="")
        self.album_title = tk.StringVar(value="")
        self.album_artist = tk.StringVar(value="")
        self.run_mode = tk.StringVar(value=LIVE_MODE)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        self.controls_panel: DriverControlsPanel | None = None
        self._launched_from_driver = was_launched_from_driver()
        self._tracks: list[Path] = []
        self._events: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._poll_id: str = ""
        self._closing = False
        self._preview_label: tk.Label | None = None

        self._apply_cli_args(
            directory=directory,
            output=output,
            album_title=album_title,
            album_artist=album_artist,
            dry_run=dry_run,
        )
        super().__init__(root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self._refresh_preview()
        if self.folder_path.get() and self._launched_from_driver:
            self.root.after(500, self._start_export)

    def _apply_cli_args(
        self,
        *,
        directory: str,
        output: str,
        album_title: str,
        album_artist: str,
        dry_run: bool,
    ) -> None:
        """Pre-fill the window from the Master Driver / launcher arguments.

        Runs before the shell builds the tabs, so every widget is constructed
        from the value it will show rather than corrected afterwards.

        Args:
            directory: Source folder.
            output: Sheet path.
            album_title: Album title.
            album_artist: Album artist.
            dry_run: Whether the launch asks for a dry run.
        """
        if directory:
            self.folder_path.set(directory)
        if output:
            self.output_path.set(output)
        if album_title:
            self.album_title.set(album_title)
        if album_artist:
            self.album_artist.set(album_artist)
        if dry_run:
            self.run_mode.set(DRY_MODE)

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder, the sheet target, the album fields and Start."""
        frame = tk.Frame(parent, padx=30, pady=16, bg=styles.BG_WHITE)
        frame.pack(expand=True, fill="both")

        tk.Label(
            frame,
            text=self.title,
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=(0, 12))

        panel = DriverControlsPanel(
            frame,
            source_var=self.folder_path,
            mode_var=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse,
            modes=RUN_MODES,
        )
        panel.pack(fill="x", pady=(0, 10))
        panel.set_driven(self._launched_from_driver)
        self.controls_panel = panel

        self._build_path_row(frame, "Sheet file:", self.output_path, browse=True)
        self._build_path_row(frame, "Album title:", self.album_title)
        self._build_path_row(frame, "Album artist:", self.album_artist)

        self._preview_label = tk.Label(
            frame,
            text="Tracks: 0",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            anchor="w",
        )
        self._preview_label.pack(fill="x", pady=(6, 6))

        self.start_btn = tk.Button(
            frame,
            text="Write CUE Sheet",
            command=self._start_export,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief="flat",
            padx=12,
        )
        self.start_btn.pack(anchor="w", pady=(4, 8))

        tk.Label(
            frame,
            text=(
                "One FILE block is written per track, numbered from the file's "
                "track tag, then its 'NN - Title' name, then its position. "
                "An existing sheet at the target path is replaced; a dry run "
                "writes the report and leaves the sheet alone."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=760,
            justify=tk.LEFT,
        ).pack(anchor="w")

    def _build_path_row(
        self,
        parent: tk.Frame,
        label: str,
        variable: tk.StringVar,
        *,
        browse: bool = False,
    ) -> None:
        """Emit one labelled entry, with an optional Browse button.

        Args:
            parent: The Setup tab's content frame.
            label: The field's caption.
            variable: The value the entry edits.
            browse: Whether to offer a file chooser for it.
        """
        row = tk.Frame(parent, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=2)
        tk.Label(
            row,
            text=label,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=22,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            row,
            textvariable=variable,
            width=46,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)
        if browse:
            tk.Button(
                row,
                text="Browse",
                command=self._browse_output,
                font=styles.FONT_CAPTION,
                bg=styles.BG_LIGHT,
                fg=styles.FG_MAIN,
                relief="flat",
                padx=6,
            ).pack(side=tk.LEFT)

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse(self) -> None:
        """Choose the source folder and preview its track count."""
        folder = filedialog.askdirectory(initialdir=self.folder_path.get() or "")
        if folder:
            self.folder_path.set(folder)
            suite_config.save_last_directory(folder)
            self._refresh_preview()

    def _browse_output(self) -> None:
        """Choose where the sheet is written."""
        folder = self.folder_path.get().strip()
        initial = self.output_path.get() or (
            str(default_output(Path(folder))) if folder else ""
        )
        chosen = filedialog.asksaveasfilename(
            initialdir=str(Path(initial).parent) if initial else "",
            initialfile=Path(initial).name if initial else "album.cue",
            defaultextension=".cue",
            filetypes=[("CUE sheet", "*.cue"), ("All files", "*.*")],
        )
        if chosen:
            self.output_path.set(chosen)

    def _refresh_preview(self) -> None:
        """Re-read the folder and show how many tracks the sheet describes."""
        folder = self.folder_path.get().strip()
        self._tracks = []
        if folder and os.path.isdir(folder):
            self._tracks = scan_audio_files(Path(folder))
        if self._preview_label is not None:
            self._preview_label.config(text=f"Tracks: {len(self._tracks)}")

    def _start_export(self) -> None:
        """Validate the window, name the report, then run on a worker thread."""
        folder = self.folder_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning(
                "Invalid Folder", "Please select a valid source folder."
            )
            return
        self._refresh_preview()
        if not self._tracks:
            messagebox.showwarning(
                "No Tracks",
                "The folder holds no supported audio files, so there is nothing "
                "to describe.",
            )
            return
        if self._thread is not None and self._thread.is_alive():
            return

        dry_run = self.run_mode.get() == DRY_MODE
        self._log_path = str(Path(folder) / report_name(dry_run))
        self.start_btn.config(state="disabled", text="Writing...")
        self.progress["mode"] = "determinate"
        self.progress["value"] = 0
        self.progress["maximum"] = len(self._tracks)
        self.stats_label.config(text="Writing...")
        self._thread = threading.Thread(
            target=self._worker,
            args=(
                folder,
                self.output_path.get().strip(),
                self.album_title.get().strip(),
                self.album_artist.get().strip(),
                dry_run,
            ),
            daemon=True,
        )
        self._thread.start()
        self._poll_events()

    def _worker(
        self,
        folder: str,
        output: str,
        title: str,
        performer: str,
        dry_run: bool,
    ) -> None:
        """Run the export off the Tk thread; never touch a widget here."""
        try:
            run_export(
                folder,
                output=output,
                title=title,
                performer=performer,
                dry_run=dry_run,
                on_progress=self._on_progress,
                on_complete=self._on_complete,
                on_error=self._on_error,
            )
        except Exception as exc:  # noqa: BLE001 - surfaced in the window, never lost
            self._events.put(("fatal", exc))

    # ── Callback seams ────────────────────────────────────────────────────────

    def _on_progress(self, **payload: Any) -> None:
        """Queue one progress payload for the Tk thread."""
        self._events.put(("progress", payload))

    def _on_complete(
        self,
        *,
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        **_extra: Any,
    ) -> None:
        """Queue the completion payload for the Tk thread.

        The five shared counters are declared because the poller displays them;
        the tool's own fields (``output``, ``tracks``, ``dry_run``) ride the
        catch-all, so a payload that grows cannot raise inside the callback.
        """
        self._events.put(
            (
                "complete",
                {
                    "total": total,
                    "processed": processed,
                    "skipped": skipped,
                    "errors": errors,
                    "duration_secs": duration_secs,
                    **_extra,
                },
            )
        )

    def _on_error(self, message: str) -> None:
        """Queue a run-failure message for the Tk thread."""
        self._events.put(("error", message))

    # ── Tk-thread poller ──────────────────────────────────────────────────────

    def _poll_events(self) -> None:
        """Apply every queued worker result, then re-arm while it still runs."""
        self._poll_id = ""
        if self._closing:
            return
        while True:
            try:
                kind, payload = self._events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                self.render_progress(
                    processed=int(payload.get("processed", 0)),
                    total=int(payload.get("total", 0)),
                    display_text=str(payload.get("display_text", "")),
                )
                self.stats_label.config(
                    text=(
                        f"Tracks: {payload.get('processed', 0)}"
                        f"/{payload.get('total', 0)}"
                    )
                )
            elif kind == "complete":
                self._finish(payload)
            else:
                self._failed(payload if isinstance(payload, str) else str(payload))
        if self._thread is not None and self._thread.is_alive():
            self._poll_id = self.root.after(100, self._poll_events)

    def _finish(self, payload: dict[str, Any]) -> None:
        """Render a finished run on the Results tab."""
        self.start_btn.config(state="normal", text="Write CUE Sheet")
        self.progress["value"] = self.progress["maximum"]
        output = str(payload.get("output", ""))
        mode = "Dry run" if payload.get("dry_run") else "Written"
        self.summary_label.config(
            text=(
                f"Tracks: {payload.get('tracks', 0)}\n"
                f"Sheet: {output}\n"
                f"Mode: {mode}\n"
                f"Errors: {payload.get('errors', 0)}"
            )
        )
        self.render_completion(
            duration_secs=float(payload.get("duration_secs", 0.0)),
            output_dir=str(Path(output).parent) if output else "",
        )
        if self.auto_end_var.get():
            self.root.after(1500, self.root.destroy)

    def _failed(self, message: str) -> None:
        """Show a run failure and re-enable the start button."""
        self.start_btn.config(state="normal", text="Write CUE Sheet")
        self.stats_label.config(text="Sheet refused.")
        messagebox.showerror("CUE Sheet Error", message)

    def _on_close(self) -> None:
        """Stop the poller, then close the window."""
        self._closing = True
        if self._poll_id:
            self.root.after_cancel(self._poll_id)
            self._poll_id = ""
        self.root.destroy()


def main() -> None:
    """Parse the launcher argv, pre-fill the window and enter the mainloop."""
    from audio_suite_shared.styles import bootstrap_theme

    args = parse_cli_args(cli_args.parse)
    root = tk.Tk()
    bootstrap_theme()
    if args is None:
        CueSheetApp(root)
    else:
        CueSheetApp(
            root,
            directory=args.folder_path,
            output=args.output,
            album_title=args.album_title,
            album_artist=args.album_artist,
            dry_run=getattr(args, "live_mode", True) is False,
        )
    root.mainloop()
