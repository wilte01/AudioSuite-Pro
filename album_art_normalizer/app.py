"""
app.py — Album Art Normalizer: thin orchestrator that wires UI, core logic,
and utilities together. Contains no business logic itself; it only coordinates.

Changed in 1.0.1: consumes the driver's ``--size`` argument and maps it onto the
resolution setting.

Changed in 1.4.1: ``_on_complete`` and ``_on_progress`` accept ``**_extra: Any``,
so a payload field the processor adds (D112) is ignored instead of aborting an
otherwise-finished run; ``tests/test_callback_payload_contract.py`` locks the
completion, progress and error seams.
Changed in 2.0.0: the completion wiring forwards the processor payload
as published instead of reading each field with ``kw.get(field, 0)``, so
a renamed or dropped count raises with its name instead of rendering a
plausible zero in the finished report (PLAN D117).
Changed in 2.9.0: the progress tick is the shared mixin helper (C1).
Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2), so the shell
owns the Help bar and the Processing and Results tabs; ``_on_complete`` now
writes the report (with the SUMMARY block the shell's contract reads) on
the worker thread, before it renders.

Changed in 2.9.0: the run report's ``SUMMARY:`` footer is
``audio_suite_shared.run_report.summary_lines`` -- this report words its
first counter ``Files examined`` through ``total_label`` -- the one
implementation every window writes with (D39).
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Any, cast

from audio_suite_shared import suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import (
    handle_audio_errors,
)
from audio_suite_shared.run_report import summary_lines
from audio_suite_shared.suite_app import SuiteApp

from .core import file_processor
from .core.art_processor import (
    FOLDER_JPG_TARGET,
    RESOLUTION_MAP,
    FolderImageError,
    process_folder_jpg,
)
from .ui import setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "album_art_normalizer"

_RESOLUTION_CHAR = "\u00d7"  # multiplication sign ×


def _size_to_resolution(size: str) -> str:
    """Map a pixel-dimension string from the driver to a ``RESOLUTION_MAP`` key.

    Args:
        size: A pixel dimension like ``"800"``.

    Returns:
        The matching ``RESOLUTION_MAP`` key (e.g. ``"800×800"``), or
        an empty string when *size* is not a valid dimension.
    """
    dim = size.strip()
    if not dim.isdigit():
        return ""
    key = f"{dim}{_RESOLUTION_CHAR}{dim}"
    from .core.art_processor import RESOLUTION_MAP

    return key if key in RESOLUTION_MAP else ""


class ArtNormalizerApp(SuiteApp):
    """Album Art Normalizer application GUI."""

    title = "Album Art Normalizer"
    window_key = "art_normalizer_window"
    program_name = TOOL_ID
    guide_name = "Album_Art_Normalizer_User_Guide.docx"
    completion_text = "Artwork Normalization Complete!"
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" Setup ", " Processing ", " Results ")

    def __init__(self, root: tk.Tk) -> None:
        # Tk variables
        self.folder_path: tk.StringVar = tk.StringVar()
        self.resolution: tk.StringVar = tk.StringVar(value="800×800")
        self.run_mode: tk.StringVar = tk.StringVar(value="Dry Run")

        # Driver-mirrored run controls (Clear Logs / Parallel are display-only)
        self.auto_start_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.auto_end_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.clear_logs_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.parallel_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # Processing state
        self._log_entries: list[str] = []
        self._log_path: str = ""
        self._dir_path: str = ""

        # The Setup tab's run controls call the handler while the shell
        # builds the window, so it has to exist before the shell runs.
        self.cli_handler = UniversalCLIHandler(self)

        super().__init__(root)

        # Apply CLI arguments
        self._apply_cli_args()

        # Restore last-used directory
        if not self.folder_path.get():
            last: str = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Setup tab ─────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder, resolution and mode controls into *parent*."""
        widgets = setup_tab.build(
            parent,
            folder_path=self.folder_path,
            resolution=self.resolution,
            run_mode=self.run_mode,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            driver_locked=self._launched_from_driver,
        )
        self.start_btn: tk.Button = cast(tk.Button, widgets["start_btn"])
        self.controls_panel: Any = widgets.get("controls_panel")

    def _apply_cli_args(self) -> None:
        """Parse and apply any command-line arguments."""
        parsed = cli_args.parse()
        if parsed.size:
            key = _size_to_resolution(parsed.size)
            if key:
                self.resolution.set(key)
        if not parsed.folder_path:
            return

        # Mirror the driver's run controls onto the Setup tab panel.
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        should_auto_start: bool = self.cli_handler.apply_cli_args(
            parsed,
            folder_var=self.folder_path,
        )
        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    def _browse_folder(self) -> None:
        """Browse for a music directory."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def start_processing(self) -> None:
        """Validate inputs then launch the background thread."""
        folder = self.folder_path.get().strip()

        if not folder:
            messagebox.showwarning("No Directory", "Please select a music directory.")
            return

        if not os.path.exists(folder):
            messagebox.showerror(
                "Directory Not Found", f"Directory not found:\n{folder}"
            )
            return

        if not os.path.isdir(folder):
            messagebox.showerror(
                "Invalid Directory", f"Not a valid directory:\n{folder}"
            )
            return

        resolution_key = self.resolution.get()
        if resolution_key not in RESOLUTION_MAP:
            messagebox.showerror(
                "Invalid Resolution",
                f"Please select a valid resolution. Got: {resolution_key}",
            )
            return

        target = RESOLUTION_MAP[resolution_key]
        dry_run = self.run_mode.get() != "Live Update"
        logger.info(
            "start_processing: folder=%s resolution=%s target=%dx%d dry_run=%s",
            folder,
            resolution_key,
            target[0],
            target[1],
            dry_run,
        )

        self.start_btn.config(state="disabled")
        self.notebook.select(self.processing_frame)
        self.overall_status.set("Normalising artwork...")

        threading.Thread(
            target=self._run_normalization,
            args=(folder, target, dry_run),
            daemon=True,
        ).start()

    @handle_audio_errors(reraise=False, context="art_normalizer_app_run")
    def _run_normalization(
        self, directory: str, target_size: tuple[int, int], dry_run: bool
    ) -> None:
        """Background thread: handle folder.jpg then delegate to file_processor.

        Args:
            directory: The music directory to normalise.
            target_size: Desired embedded artwork ``(width, height)``.
            dry_run: When True, both write sites (``folder.jpg`` and the
                embedded artwork) report what they would do and write nothing.
        """
        self._dir_path = directory
        self._log_entries = []

        def _append_log(msg: str) -> None:
            self._log_entries.append(msg)
            logger.info(msg)

        _append_log("=== Session started ===")
        _append_log(f"Directory: {directory}")
        _append_log(f"Mode: {'Dry Run' if dry_run else 'Live Update'}")
        _append_log(f"Embedded target: {target_size[0]}×{target_size[1]}")
        _append_log(f"folder.jpg target: {FOLDER_JPG_TARGET[0]}×{FOLDER_JPG_TARGET[1]}")
        _append_log("")

        # folder.jpg
        try:
            result = process_folder_jpg(Path(directory), dry_run)
            if result is None:
                _append_log("folder.jpg not present — skipped.")
            else:
                _append_log(f"  {result}")
        except FolderImageError as exc:
            _append_log(f"  ✗ ERROR: {exc}")

        _append_log("")

        self.root.after(0, self._reset_progress_ui)

        with active_batch("album_art_normalizer", "tag_edit"):
            file_processor.run_normalization(
                dir_path=directory,
                target_size=target_size,
                on_progress=self._on_progress,
                # Forward the payload as published.  Reading each field with
                # ``kw.get(field, 0)`` -- what this lambda used to do -- turned
                # a renamed or dropped field into a plausible zero in the
                # finished report, the exact silent-zero the completion seam
                # exists to stop; ``_on_complete`` already declares every field
                # it uses and absorbs extras, so the payload passes straight
                # through and a missing one raises with its name.
                on_complete=self._on_complete,
                on_error=self._on_error,
                is_dry_run=dry_run,
            )

    def _reset_progress_ui(self) -> None:
        self.progress["value"] = 0
        self.stats_label.config(text="Processed: 0 | Images Updated: 0 | Errors: 0")
        self.file_listbox.delete(0, tk.END)

    def _on_progress(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
        self._log_entries.append(display_text)
        self.root.after(
            0, self._update_progress_ui, processed, total, skipped, errors, display_text
        )

    def _update_progress_ui(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        self._render_progress_standard(processed, total, display_text)
        updated = processed - skipped - errors
        self.stats_label.config(
            text=(
                f"Processed: {processed} | Images Updated: {updated} | Errors: {errors}"
            )
        )

    def _on_complete(
        self,
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        **_extra: Any,
    ) -> None:
        """Completion seam: write the report here, render it on the Tk thread."""
        self._write_run_report(
            total=total,
            processed=processed,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
        )
        self.root.after(
            0,
            self._update_ui_on_complete,
            total,
            processed,
            skipped,
            errors,
            duration_secs,
        )

    def _write_run_report(
        self,
        *,
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Serialise the run report View Log opens; a failed write is logged."""
        log_path = os.path.join(self._dir_path, "art_normalize_log.txt")
        self._log_path = log_path
        updated = processed - skipped - errors
        summary = summary_lines(
            total=total,
            total_label="Files examined",
            tagged=updated,
            tagged_label="Images updated",
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            rows=(("Output", self._dir_path),),
        )
        try:
            with open(log_path, "w", encoding="utf-8") as handle:
                for line in [*self._log_entries, *summary]:
                    handle.write(line if line.endswith("\n") else line + "\n")
        except OSError as exc:
            logger.error("Failed to write log '%s': %s", log_path, exc, exc_info=True)

    def _update_ui_on_complete(
        self,
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
    ) -> None:
        """Render the finished run (must run on the main thread)."""
        updated = processed - skipped - errors
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)

        self.summary_label.config(
            text=(
                f"Files examined: {total}\n"
                f"Images updated: {updated}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        )
        self.render_completion(duration_secs=duration_secs, output_dir=self._dir_path)

        logger.info(
            "Processing complete - total=%d updated=%d"
            " skipped=%d errors=%d time=%02d:%02d",
            total,
            updated,
            skipped,
            errors,
            minutes,
            seconds,
        )

        if self.auto_end_var.get():
            self.root.after(2000, self.root.destroy)
