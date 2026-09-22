"""
app.py
ASXExtractorTool — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.
"""

import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any

from audio_suite_shared import platform_utils, styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.styles import apply_styles
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core import asx_parser, file_ops
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

TOOL_ID = "asx_extractor"


class ASXExtractorTool(UIHelperMixin):
    """ASX Playlist Extractor application GUI."""

    HELP_GUIDE = "ASX_Playlist_Extractor_User_Guide.docx"

    def __init__(
        self,
        root: tk.Tk,
        initial_directory: str | None = None,
        initial_mode: str | None = None,
        auto_start: bool = False,
        auto_end: bool = False,
        clear_logs: bool = False,
        parallel_run: bool = False,
    ) -> None:
        self.root = root
        self.auto_end = auto_end
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "ASX Playlist Extractor",
            "asx_extractor_window",
            "asx_extractor",
            height=700,
            apply_ttk_styles=False,
        )

        # ── Tk variables ─────────────────────────────────────────────────────
        self.current_folder = tk.StringVar()
        self.asx_action_mode = tk.StringVar(value="Dry Run (Simulated)")

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
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Restore last-used directory (if not set by caller) ───────────────
        if not self.current_folder.get():
            last = suite_config.load_last_directory()
            if last:
                self.current_folder.set(last)

        # ── Build UI ─────────────────────────────────────────────────────────
        self._build_ui()

        # ── Auto-start (Master Driver handshake) ─────────────────────────────
        if auto_start:
            self.root.after(500, self.start_extraction)

    # ── UI construction ──────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        styles.set_active_palette(suite_config.load_palette())
        styles.set_active_typography(
            suite_config.load_font_family(), suite_config.load_font_sizes()
        )

        style = ttk.Style()
        apply_styles(style)

        # Help button above the notebook
        help_frame = tk.Frame(self.root, bg=styles.BG_LIGHT)
        help_frame.pack(fill="x", padx=10, pady=(10, 0))
        tk.Button(
            help_frame,
            text="Help",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BODY,
            padx=15,
            pady=3,
            command=self._open_help,
        ).pack(side=tk.RIGHT)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=15, pady=15)

        tab_control = tk.Frame(self.notebook, bg=styles.BG_WHITE)
        tab_extractor = tk.Frame(self.notebook, bg=styles.BG_WHITE)
        tab_review = tk.Frame(self.notebook, bg=styles.BG_WHITE)

        self.notebook.add(tab_control, text=" 1. Setup ")
        self.notebook.add(tab_extractor, text=" 2. Processing ")
        self.notebook.add(tab_review, text=" 3. Results ")

        widgets = setup_tab.build(
            tab_control,
            current_folder=self.current_folder,
            asx_action_mode=self.asx_action_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse_folder,
            on_start=self.start_extraction,
            preset_names=suite_config.list_presets(TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
            driver_locked=self._launched_from_driver,
        )
        self._start_btn = widgets["start_btn"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self._preset_combo = widgets["preset_combo"]
        self._controls_panel = widgets["controls_panel"]

        # update_step() callable; update_step.reset() resets all labels
        self._update_step: Any = processing_tab.build(tab_extractor)

        # btn_log returned so we can enable it after the run completes
        self._btn_log = results_tab.build(
            tab_review,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )

        self._tab_extractor = tab_extractor
        self._tab_review = tab_review

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "run_mode": self.asx_action_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "run_mode" in settings:
            self.asx_action_mode.set(settings["run_mode"])

    def _on_preset_selected(self, name: str) -> None:
        settings = suite_config.load_preset(TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        suite_config.save_preset(TOOL_ID, name, self._collect_settings())
        self._refresh_preset_list(suite_config.list_presets(TOOL_ID))

    def _delete_preset(self, name: str) -> None:
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

    def _open_log(self) -> None:
        log_path = Path(self.current_folder.get()) / "Extraction_Log.txt"
        if not log_path.exists():
            messagebox.showwarning(
                "Log Not Found", "Extraction log file does not exist."
            )
            return
        platform_utils.open_path(str(log_path))

    def _open_folder(self) -> None:
        """Open the output folder in the system file explorer."""
        folder = self.current_folder.get()
        if not folder:
            messagebox.showwarning("No Folder", "Output folder not available.")
            return
        self._out_dir = str(Path(folder))
        self._open_folder_standard()

    def start_extraction(self) -> None:
        """Start the ASX extraction process."""
        if not self.current_folder.get():
            messagebox.showwarning(
                "No Directory", "Please select a target directory first."
            )
            return
        self._update_step.reset()
        self.notebook.select(self._tab_extractor)
        threading.Thread(target=self._run, daemon=True).start()

    # ── Background thread ────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="asx_extract_run")
    def _run(self) -> None:
        source_dir = Path(self.current_folder.get()).resolve()
        is_dry_run = "Dry Run" in self.asx_action_mode.get()
        mode_label = self.asx_action_mode.get()
        log_path = source_dir / "Extraction_Log.txt"

        step = self._update_step  # shorthand

        # ── Step 1: Scan ─────────────────────────────────────────────────────
        self.root.after(0, lambda: step(0, "active"))
        time.sleep(0.5)

        # Set prevents duplicates on case-insensitive filesystems (Windows)
        asx_files = list(
            {
                f
                for f in source_dir.iterdir()
                if f.is_file() and f.suffix.lower() == ".asx"
            }
        )
        asx_count = len(asx_files)
        self.root.after(0, lambda: step(0, "done", f" ({asx_count} found)"))

        successes: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        # ── Steps 2 & 3: Parse + verify ──────────────────────────────────────
        time.sleep(0.5)
        self.root.after(0, lambda: step(1, "active"))
        self.root.after(0, lambda: step(2, "active"))

        for asx_file in asx_files:
            result = asx_parser.process_asx_file(asx_file, source_dir)
            (successes if result["success"] else failures).append(result)

        self.root.after(0, lambda: step(1, "done"))
        self.root.after(0, lambda: step(2, "done"))

        # ── Step 4: Copy audio ───────────────────────────────────────────────
        time.sleep(0.5)
        self.root.after(0, lambda: step(3, "active"))

        copy_failed_paths: set[Path] = set()
        if not is_dry_run:
            with active_batch("asx_extractor", "file_reorg"):
                for item in successes:
                    if not file_ops.copy_audio_file(item["audio_path"], source_dir):
                        copy_failed_paths.add(item["asx_path"])

        self.root.after(0, lambda: step(3, "done"))

        # ── Step 5: Remove ASX files ─────────────────────────────────────────
        time.sleep(0.5)
        self.root.after(0, lambda: step(4, "active"))

        # Only remove an ASX playlist if its audio copy actually succeeded;
        # otherwise the user would lose the playlist pointer with nothing
        # copied to show for it. Items whose copy failed are reclassified
        # as failures so the log accurately reflects what happened.
        remaining_successes = []
        if not is_dry_run:
            for item in successes:
                if item["asx_path"] in copy_failed_paths:
                    failures.append(
                        {
                            "asx_fn": item["asx_fn"],
                            "audio_path": str(item["audio_path"]),
                            "reason": "COPY FAILED",
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

        self.root.after(0, lambda: step(4, "done"))

        # ── Step 6: Write log ────────────────────────────────────────────────
        time.sleep(0.5)
        self.root.after(0, lambda: step(5, "active"))

        ok = file_ops.write_extraction_log(
            log_path=log_path,
            source_dir=source_dir,
            mode_label=mode_label,
            successes=successes,
            failures=failures,
        )
        if not ok:
            self.root.after(
                0,
                lambda: messagebox.showerror(
                    "Log Error", "Could not write the extraction log."
                ),
            )

        self.root.after(0, lambda: step(5, "done"))
        self.root.after(0, lambda: self._btn_log.config(state="normal"))
        self.root.after(1000, lambda: self.notebook.select(self._tab_review))

        # ── Auto-end (Master Driver handshake) ───────────────────────────────
        # Read the panel variable so a standalone toggle takes effect too;
        # the plain attribute stays for backward compatibility.
        if self.auto_end_var.get():
            self.root.after(2000, self.root.destroy)

    def _open_help(self) -> None:
        """Open the help guide for ASX Playlist Extractor."""
        self._open_help_standard(self.HELP_GUIDE)
