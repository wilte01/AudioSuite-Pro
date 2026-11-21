# Changed in 2.4.0: duplicate dispositions and ASX stubs.
"""
app.py
ASXExtractorTool — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, the seventh window
of D8's wave 2), so the shell owns the Help bar and the Processing and Results
tabs and this tool keeps its Setup panel. The Processing tab was a six-stage
checklist of its own; it is now the shared progress bar, counters and per-file
list, one line per playlist. ``Extraction_Log.txt`` is named as ``_log_path``
when the run starts, so View Log is the shell's report opener instead of a
button this window enabled by hand. The run's folder, mode and subfolder choice
are passed to the worker as arguments, so it never reads a Tk variable off the
Tk thread.
"""

import logging
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from audio_suite_shared import suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.suite_app import SuiteApp

from .core import asx_parser, file_ops
from .ui import setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "asx_extractor"


class ASXExtractorTool(SuiteApp):
    """ASX Playlist Extractor application GUI."""

    title = "ASX Playlist Extractor"
    window_key = "asx_extractor_window"
    program_name = TOOL_ID
    #: Kept for the guide registry's scan; the shell reads ``guide_name``.
    HELP_GUIDE = "ASX_Playlist_Extractor_User_Guide.docx"
    guide_name = HELP_GUIDE
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" 1. Setup ", " 2. Processing ", " 3. Results ")
    #: This window has always opened at 700 px and left its ttk widgets to the
    #: theme the launcher set, rather than restyling them a second time.
    window_size = (850, 700)
    apply_ttk_styles = False

    #: Word used in the report and the Results summary for a playlist whose
    #: audio was extracted.
    TAGGED_LABEL = "Extracted"
    #: Results-tab completion captions, by run mode.
    DRY_COMPLETE_LABEL = "Dry Run Complete!"
    LIVE_COMPLETE_LABEL = "Extraction Complete!"
    completion_text = DRY_COMPLETE_LABEL
    #: This window counts playlists extracted and playlists that failed.
    processing_stats_text = "Extracted: 0 | Failed: 0"

    #: Set from argv in ``__init__``.  The default keeps an ``object.__new__``
    #: test shell on the interactive (modal-warning) path.
    _launched_from_driver: bool = False
    #: Set by ``_run``; the Results tab's Open Folder target.
    _dir_path: str = ""

    def __init__(
        self,
        root: tk.Tk,
        initial_directory: str | None = None,
        initial_mode: str | None = None,
        recursive: bool = False,
        auto_start: bool = False,
        auto_end: bool = False,
        clear_logs: bool = False,
        parallel_run: bool = False,
    ) -> None:
        # ── Tk variables ─────────────────────────────────────────────────────
        self.current_folder = tk.StringVar()
        self.asx_action_mode = tk.StringVar(value="Dry Run (Simulated)")
        self.recursive_var = tk.BooleanVar(value=recursive)

        # Driver-mirrored run controls (Clear Logs / Parallel are display-only)
        self.auto_start_var = tk.BooleanVar(value=auto_start)
        self.auto_end_var = tk.BooleanVar(value=auto_end)
        self.clear_logs_var = tk.BooleanVar(value=clear_logs)
        self.parallel_var = tk.BooleanVar(value=parallel_run)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        if initial_directory:
            self.current_folder.set(initial_directory)
        if initial_mode:
            self.asx_action_mode.set(initial_mode)

        # ── State ─────────────────────────────────────────────────────────────
        # The run's mode, snapshotted by start_extraction on the Tk thread.
        self._run_mode: str = ""

        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Restore last-used directory (if not set by caller) ───────────────
        if not self.current_folder.get():
            last = suite_config.load_last_directory()
            if last:
                self.current_folder.set(last)

        super().__init__(root)

        # ── Auto-start (Master Driver handshake) ─────────────────────────────
        if auto_start:
            self.root.after(500, self.start_extraction)

    # ── Shell tabs ────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the target folder, the action mode, presets and the start button."""
        widgets: dict[str, Any] = setup_tab.build(
            parent,
            current_folder=self.current_folder,
            asx_action_mode=self.asx_action_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            recursive_var=self.recursive_var,
            on_browse=self._browse_folder,
            on_start=self.start_extraction,
            preset_names=suite_config.list_presets(TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
            driver_locked=self._launched_from_driver,
        )
        self.start_btn = widgets["start_btn"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self._preset_combo = widgets["preset_combo"]
        self.controls_panel = widgets["controls_panel"]

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        """Collect current UI settings into a dict for preset storage."""
        return {
            "run_mode": self.asx_action_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        """Apply a preset dict to the UI variables."""
        if "run_mode" in settings:
            self.asx_action_mode.set(settings["run_mode"])

    def _on_preset_selected(self, name: str) -> None:
        """Load a named preset and apply its settings."""
        settings = suite_config.load_preset(TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        """Save the current settings as a named preset."""
        suite_config.save_preset(TOOL_ID, name, self._collect_settings())
        self._refresh_preset_list(suite_config.list_presets(TOOL_ID))

    def _delete_preset(self, name: str) -> None:
        """Delete a named preset."""
        suite_config.delete_preset(TOOL_ID, name)
        self._refresh_preset_list(suite_config.list_presets(TOOL_ID))

    # ── User actions ─────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        """Browse for folder with enhanced error handling."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.current_folder,
            save_last_dir=True,
        )

    def start_extraction(self) -> None:
        """Validate the target folder, then run the extraction on a worker."""
        folder = self.current_folder.get().strip()
        if not folder:
            messagebox.showwarning(
                "No Directory", "Please select a target directory first."
            )
            return

        self.start_btn.config(state="disabled")
        self.progress["value"] = 0
        self.stats_label.config(text=self.processing_stats_text)
        self.file_listbox.delete(0, tk.END)
        self.notebook.select(self.processing_frame)
        self.overall_status.set("Scanning for ASX playlists...")

        # Snapshot the mode on the main thread: the completion renders from it,
        # and the worker must not call .get() (see _run).
        mode_label = self.asx_action_mode.get()
        self._run_mode = "Dry Run" if "Dry Run" in mode_label else "Live Update"

        threading.Thread(
            target=self._run,
            args=(Path(folder), mode_label, bool(self.recursive_var.get())),
            daemon=True,
        ).start()

    # ── Background thread ────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="asx_extract_run")
    def _run(self, source_dir: Path, mode_label: str, recursive: bool) -> None:
        """Background thread: scan, parse, extract, then write the report."""
        started = time.monotonic()
        source_dir = source_dir.resolve()
        is_dry_run = "Dry Run" in mode_label
        self._dir_path = str(source_dir)
        self._log_path = str(source_dir / "Extraction_Log.txt")

        # Set prevents duplicates on case-insensitive filesystems (Windows)
        candidates = source_dir.rglob("*") if recursive else source_dir.iterdir()
        asx_files = sorted(
            {f for f in candidates if f.is_file() and f.suffix.lower() == ".asx"}
        )
        total = len(asx_files)

        successes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        # ── Steps 2 & 3: Parse + verify ──────────────────────────────────────
        for index, asx_file in enumerate(asx_files, start=1):
            result = asx_parser.process_asx_file(asx_file, source_dir)
            if result["success"]:
                successes.append(result)
            else:
                failures.append(result)
            self.root.after(
                0,
                self._render_tick,
                index,
                total,
                len(successes),
                len(failures),
                f"[{'OK' if result['success'] else 'FAILED'}] {result['asx_fn']}",
            )

        # ── Step 4: Copy audio ───────────────────────────────────────────────
        copy_failed_paths: dict[Path, str] = {}
        if not is_dry_run:
            with active_batch(TOOL_ID, "file_reorg"):
                for item in successes:
                    if item.get("stub") is not None:
                        ok, reason = file_ops.recreate_from_stub(
                            item["asx_path"], item["audio_path"], item["stub"]
                        )
                        if not ok:
                            copy_failed_paths[item["asx_path"]] = (
                                f"RECREATE FAILED: {reason}"
                            )
                    elif not file_ops.copy_audio_file(item["audio_path"], source_dir):
                        copy_failed_paths[item["asx_path"]] = "COPY FAILED"

        # ── Step 5: Remove ASX files ─────────────────────────────────────────
        # Only remove an ASX playlist if its audio copy actually succeeded;
        # otherwise the user would lose the playlist pointer with nothing
        # copied to show for it. Items whose copy failed are reclassified
        # as failures so the log accurately reflects what happened.
        remaining_successes: list[dict[str, Any]] = []
        if not is_dry_run:
            for item in successes:
                if item["asx_path"] in copy_failed_paths:
                    failures.append(
                        {
                            "asx_fn": item["asx_fn"],
                            "audio_path": str(item["audio_path"]),
                            "reason": copy_failed_paths[item["asx_path"]],
                        }
                    )
                    continue
                if not file_ops.remove_asx_file(item["asx_path"]):
                    failures.append(
                        {
                            "asx_fn": item["asx_fn"],
                            "audio_path": str(item["audio_path"]),
                            "reason": "AUDIO COPIED BUT ASX REMOVAL FAILED",
                        }
                    )
                    continue
                remaining_successes.append(item)
            successes = remaining_successes

        # ── Step 6: Write log ────────────────────────────────────────────────
        written = file_ops.write_extraction_log(
            log_path=Path(self._log_path),
            source_dir=source_dir,
            mode_label=mode_label,
            successes=successes,
            failures=failures,
        )
        self.root.after(
            0,
            self._finish,
            total,
            len(successes),
            len(failures),
            time.monotonic() - started,
            written,
        )

    # ── Callbacks (called from the worker thread — all UI via root.after) ────

    def _render_tick(
        self,
        index: int,
        total: int,
        extracted: int,
        failed: int,
        line: str,
    ) -> None:
        """Render one playlist's line and the run's counters (Tk thread)."""
        self._render_progress_standard(index, total, line)
        self.stats_label.config(text=f"Extracted: {extracted} | Failed: {failed}")

    def _finish(
        self,
        total: int,
        extracted: int,
        failed: int,
        duration_secs: float,
        log_written: bool,
    ) -> None:
        """Render the finished run (must run on the main thread)."""
        if not log_written:
            messagebox.showerror("Log Error", "Could not write the extraction log.")

        self.summary_label.config(
            text=(
                f"Total: {total} playlists\n"
                f"{self.TAGGED_LABEL}: {extracted}\n"
                f"Failed: {failed}"
            )
        )
        logger.info(
            "Extraction complete - total=%d extracted=%d failed=%d",
            total,
            extracted,
            failed,
        )

        # This window has always labelled a finished run by its mode; the shell
        # renders ``completion_text``, so point it at this run's wording first.
        self.completion_text = (
            self.DRY_COMPLETE_LABEL
            if self._run_mode == "Dry Run"
            else self.LIVE_COMPLETE_LABEL
        )
        self.render_completion(duration_secs=duration_secs, output_dir=self._dir_path)

        # Read the panel variable so a standalone toggle takes effect too.
        if self.auto_end_var.get():
            self.root.after(2000, self.root.destroy)
