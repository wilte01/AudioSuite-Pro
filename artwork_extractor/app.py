"""app.py — the Artwork Extractor window.

A ``SuiteApp``: the shell supplies the Help bar, the notebook, the Processing
tab and the Results tab; this module supplies the Setup tab, the run and the
three callback seams.  The run happens on a worker thread and hands every
result to the Tk thread through a ``SimpleQueue`` — a worker thread that called
``root.after`` (or any widget method) would raise on 3.14 and leave the window
waiting for a result that never arrives.

The window is the tool's Master Driver batch step: the driver launches it with
the folder, its Live/Dry choice and its Auto Start / Auto End pair, and closes
it again when the run finishes.  The extraction itself is
:func:`artwork_extractor.core.extract.run_extraction`, which reads and writes
through the same shared artwork helpers ``audiosuite artwork extract`` uses.

Changed in 2.6.0: new module — the Artwork Extractor's window.
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
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.ui_driver_controls import DriverControlsPanel

from .core.extract import report_name, run_extraction
from .utils import cli_args

logger = logging.getLogger(__name__)

LIVE_MODE = "Live Update"
DRY_MODE = "Dry Run"
RUN_MODES = (LIVE_MODE, DRY_MODE)


class ArtworkExtractorApp(SuiteApp):
    """Write each file's embedded cover beside it as a sidecar."""

    title = "Artwork Extractor"
    window_key = "artwork_extractor_window"
    program_name = "artwork_extractor"
    guide_name = "Artwork_Extractor_User_Guide.docx"
    completion_text = "Artwork Extracted!"

    def __init__(
        self,
        root: tk.Tk,
        *,
        directory: str = "",
        sidecar_name: str = cli_args.DEFAULT_SIDECAR_NAME,
        force: bool = False,
        recursive: bool = False,
        dry_run: bool = False,
        auto_start: bool = False,
        auto_end: bool = False,
        clear_logs: bool = False,
        parallel: bool = False,
    ) -> None:
        self.folder_path = tk.StringVar(value=suite_config.load_last_directory())
        self.sidecar_name = tk.StringVar(value=cli_args.DEFAULT_SIDECAR_NAME)
        self.force_var = tk.BooleanVar(value=False)
        self.recursive_var = tk.BooleanVar(value=False)
        self.run_mode = tk.StringVar(value=LIVE_MODE)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        self.controls_panel: DriverControlsPanel | None = None
        self._launched_from_driver = was_launched_from_driver()
        self._events: queue.SimpleQueue[tuple[str, Any]] = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._poll_id: str = ""
        self._closing = False

        self._apply_cli_args(
            directory=directory,
            sidecar_name=sidecar_name,
            force=force,
            recursive=recursive,
            dry_run=dry_run,
            auto_start=auto_start,
            auto_end=auto_end,
            clear_logs=clear_logs,
            parallel=parallel,
        )
        super().__init__(root)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        # Auto Start is the driver's choice, not a consequence of being
        # launched by it: a batch step passes `--start`, and a driver run with
        # it unchecked must leave the window waiting for the user.
        if self.folder_path.get() and self.auto_start_var.get():
            self.root.after(500, self._start_extraction)

    def _apply_cli_args(
        self,
        *,
        directory: str,
        sidecar_name: str,
        force: bool,
        recursive: bool,
        dry_run: bool,
        auto_start: bool,
        auto_end: bool,
        clear_logs: bool,
        parallel: bool,
    ) -> None:
        """Pre-fill the window from the Master Driver / launcher arguments.

        Runs before the shell builds the tabs, so every widget is constructed
        from the value it will show rather than corrected afterwards.

        Args:
            directory: Source folder.
            sidecar_name: Sidecar base name.
            force: Whether an existing sidecar may be replaced.
            recursive: Whether sub-folders are read.
            dry_run: Whether the launch asks for a dry run.
            auto_start: Whether the launch asks the run to begin on its own.
            auto_end: Whether the launch asks the window to close after the run.
            clear_logs: The driver's display-only Clear Logs state.
            parallel: The driver's display-only Parallel state.
        """
        if directory:
            self.folder_path.set(directory)
        if sidecar_name:
            self.sidecar_name.set(sidecar_name)
        if force:
            self.force_var.set(True)
        if recursive:
            self.recursive_var.set(True)
        if dry_run:
            self.run_mode.set(DRY_MODE)
        if auto_start:
            self.auto_start_var.set(True)
        if auto_end:
            self.auto_end_var.set(True)
        if clear_logs:
            self.clear_logs_var.set(True)
        if parallel:
            self.parallel_var.set(True)

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder, the sidecar options and Start."""
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

        row = tk.Frame(frame, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=2)
        tk.Label(
            row,
            text="Sidecar name:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=22,
            anchor="w",
        ).pack(side=tk.LEFT)
        tk.Entry(
            row,
            textvariable=self.sidecar_name,
            width=24,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=6)
        tk.Label(
            row,
            text="(.jpg or .png follows the image's own format)",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
        ).pack(side=tk.LEFT)

        for text, variable in (
            ("Replace an existing sidecar", self.force_var),
            ("Also read sub-folders", self.recursive_var),
        ):
            tk.Checkbutton(
                frame,
                text=text,
                variable=variable,
                font=styles.FONT_BODY,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                selectcolor=styles.BG_WHITE,
                activebackground=styles.BG_WHITE,
                activeforeground=styles.FG_MAIN,
            ).pack(anchor="w")

        self.start_btn = tk.Button(
            frame,
            text="Extract Artwork",
            command=self._start_extraction,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
            relief="flat",
            padx=12,
        )
        self.start_btn.pack(anchor="w", pady=(8, 8))

        tk.Label(
            frame,
            text=(
                "Each file's embedded cover is written beside it as "
                "'cover.jpg' or 'cover.png', chosen from the image's own bytes "
                "rather than the container's claim. An existing sidecar is kept "
                "unless 'Replace an existing sidecar' is ticked, because "
                "overwriting a curated cover destroys the better copy. A dry "
                "run writes the report and no sidecar."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=760,
            justify=tk.LEFT,
        ).pack(anchor="w")

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse(self) -> None:
        """Choose the source folder."""
        folder = filedialog.askdirectory(initialdir=self.folder_path.get() or "")
        if folder:
            self.folder_path.set(folder)
            suite_config.save_last_directory(folder)

    def _start_extraction(self) -> None:
        """Validate the window, name the report, then run on a worker thread."""
        folder = self.folder_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning(
                "Invalid Folder", "Please select a valid source folder."
            )
            return
        if self._thread is not None and self._thread.is_alive():
            return

        dry_run = self.run_mode.get() == DRY_MODE
        self._log_path = str(Path(folder) / report_name(dry_run))
        self.start_btn.config(state="disabled", text="Extracting...")
        self.progress["mode"] = "determinate"
        self.progress["value"] = 0
        self.stats_label.config(text="Reading artwork...")
        self._thread = threading.Thread(
            target=self._worker,
            args=(
                folder,
                self.sidecar_name.get().strip(),
                self.force_var.get(),
                self.recursive_var.get(),
                dry_run,
            ),
            daemon=True,
        )
        self._thread.start()
        self._poll_events()

    def _worker(
        self,
        folder: str,
        name: str,
        force: bool,
        recursive: bool,
        dry_run: bool,
    ) -> None:
        """Run the extraction off the Tk thread; never touch a widget here."""
        try:
            run_extraction(
                folder,
                name=name or cli_args.DEFAULT_SIDECAR_NAME,
                force=force,
                recursive=recursive,
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
        the tool's own fields (``extracted``, ``kept``, ``no_art``,
        ``dry_run``, ``report_path``) ride the catch-all, so a payload that
        grows cannot raise inside the callback.
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
                        f"Files: {payload.get('processed', 0)}"
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
        self.start_btn.config(state="normal", text="Extract Artwork")
        self.progress["value"] = self.progress["maximum"]
        mode = "Dry run" if payload.get("dry_run") else "Written"
        self.summary_label.config(
            text=(
                f"Files: {payload.get('total', 0)}\n"
                f"Extracted: {payload.get('extracted', 0)}\n"
                f"Kept: {payload.get('kept', 0)}\n"
                f"Without art: {payload.get('no_art', 0)}\n"
                f"Mode: {mode}\n"
                f"Errors: {payload.get('errors', 0)}"
            )
        )
        self.render_completion(
            duration_secs=float(payload.get("duration_secs", 0.0)),
            output_dir=self.folder_path.get().strip(),
        )
        if self.auto_end_var.get():
            self.root.after(1500, self.root.destroy)

    def _failed(self, message: str) -> None:
        """Show a run failure and re-enable the start button."""
        self.start_btn.config(state="normal", text="Extract Artwork")
        self.stats_label.config(text="Extraction refused.")
        messagebox.showerror("Artwork Extractor Error", message)

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
        ArtworkExtractorApp(root)
    else:
        ArtworkExtractorApp(
            root,
            directory=args.folder_path,
            sidecar_name=args.sidecar_name,
            force=args.force,
            recursive=args.recursive,
            dry_run=getattr(args, "live_mode", True) is False,
            auto_start=getattr(args, "auto_start", False),
            auto_end=getattr(args, "auto_end", False),
            clear_logs=getattr(args, "clear_logs", False),
            parallel=getattr(args, "parallel_run", False),
        )
    root.mainloop()
