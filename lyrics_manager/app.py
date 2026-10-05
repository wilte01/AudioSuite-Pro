"""
app.py
LyricsManagerApp — thin orchestrator that wires UI, core logic, and utilities together.
Contains no business logic itself; it only coordinates.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, cast

from audio_suite_shared import platform_utils, styles
from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.audio_formats import is_supported_format
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import (
    UniversalCLIHandler as UniversalCLIHandler,
)
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.tool_app_base import AnalysisTagToolApp

from .core import file_processor
from .core.providers import get_provider
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "lyrics_manager"


class LyricsManagerApp(AnalysisTagToolApp):
    """Lyrics Manager application GUI."""

    # Name of the user-guide document expected alongside this script.
    HELP_GUIDE: str = "Lyrics_Manager_User_Guide.docx"

    TAGGED_LABEL: str = "Tagged/Updated"
    DRY_COMPLETE_LABEL: str = "Lyric Lookup Complete!"
    LIVE_COMPLETE_LABEL: str = "Lyrics Tagging Complete!"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Lyrics Manager",
            "lyrics_manager_window",
            "lyrics_manager",
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path: tk.StringVar = tk.StringVar()
        self.run_mode: tk.StringVar = tk.StringVar(value="Dry Run")
        self.provider: tk.StringVar = tk.StringVar(
            value=str(_suite_config.load_value("lyrics_provider", "lrclib"))
        )
        self.request_timeout: tk.StringVar = tk.StringVar(
            value=str(_suite_config.load_value("lyrics_request_timeout", 10.0))
        )
        self.skip_existing: tk.BooleanVar = tk.BooleanVar(
            value=bool(_suite_config.load_value("lyrics_skip_existing", True))
        )
        self.plain_fallback: tk.BooleanVar = tk.BooleanVar(
            value=bool(_suite_config.load_value("lyrics_plain_fallback", True))
        )
        saved_parallel: bool = cast(
            bool, _suite_config.load_value("lyrics_parallel_mode", False)
        )
        saved_workers: int = int(
            cast(str, _suite_config.load_value("lyrics_max_workers", 4))
        )
        self.parallel_mode: tk.BooleanVar = tk.BooleanVar(value=saved_parallel)
        self.max_workers: tk.IntVar = tk.IntVar(value=saved_workers)

        # Run Controls panel variables (driver handshake display state).
        self.auto_start_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.auto_end_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.clear_logs_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.parallel_var: tk.BooleanVar = tk.BooleanVar(value=False)

        # Master Driver handshake: any CLI argument means driver-launched,
        # in which case the Run Controls panel is locked to inherited values.
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # ── Processing state ─────────────────────────────────────────────────
        self._log_entries: list[str] = []
        self._log_path: str = ""
        self._dir_path: str = ""
        self.auto_end: bool = False

        # ── Worker slot pool (4 concurrent workers) ──────────────────────────
        self.slot_vars: list[tk.StringVar] = [
            tk.StringVar(value="IDLE") for _ in range(4)
        ]
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self.slot_queue: Queue[int] = Queue()
        for i in range(4):
            self.slot_queue.put(i)

        # ── Preset support ────────────────────────────────────────────────────
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Build UI ──────────────────────────────────────────────────────────
        self._build_ui()
        assert self._refresh_preset_list is not None
        self._refresh_preset_list()

        # ── Apply CLI arguments ───────────────────────────────────────────────
        self._apply_cli_args()

        # Force UI refresh so Entry widgets display current variable values.
        self.root.update_idletasks()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last: str = _suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Construct the full application UI."""
        # Help button above the notebook.
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

        # Notebook with three tabs.
        self.notebook: ttk.Notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        tab_setup = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_processing = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_results = tk.Frame(self.notebook, bg=styles.BG_LIGHT)

        self.notebook.add(tab_setup, text=" 1. Setup ")
        self.notebook.add(tab_processing, text=" 2. Processing ")
        self.notebook.add(tab_results, text=" 3. Results ")

        setup_widgets: dict[str, Any] = setup_tab.build(
            tab_setup,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            provider=self.provider,
            request_timeout=self.request_timeout,
            skip_existing=self.skip_existing,
            plain_fallback=self.plain_fallback,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse_folder,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
            parallel_mode=self.parallel_mode,
            max_workers=self.max_workers,
            on_preset_selected=self._on_preset_selected,
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
        )
        self.start_btn = setup_widgets["start_btn"]
        self._preset_combo = setup_widgets["preset_combo"]
        self._refresh_preset_list = setup_widgets["refresh_preset_list"]

        proc_widgets: dict[str, Any] = processing_tab.build(
            tab_processing, self.slot_vars
        )
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]

        res_widgets: dict[str, Any] = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]
        self.time_label: tk.Label = res_widgets["time_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]

        # Keep tab references for programmatic switching.
        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        """Parse and apply any command-line arguments supplied by the Master Driver."""
        parsed = cli_args.parse()
        self._apply_driver_cli_args(parsed)

    def _apply_tool_cli_options(self, parsed: Any) -> None:
        """Lyrics-specific tool options from the driver handshake."""
        self.provider.set(parsed.provider)
        self.request_timeout.set(str(parsed.request_timeout))
        self.skip_existing.set(parsed.skip_existing)
        self.plain_fallback.set(parsed.plain_fallback)

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        """Browse for a music directory with standard error handling."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _open_help(self) -> None:
        """Open the tool user guide."""
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        """Open the most recent analysis log file."""
        self._open_log_standard()

    def _open_folder(self) -> None:
        """Open the source folder in the system file manager."""
        folder_path: str = self.folder_path.get()
        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Source folder not available.")

    def start_processing(self) -> None:
        """Validate inputs then launch the background lookup thread."""
        try:
            folder: str = self.folder_path.get().strip()

            if not folder:
                messagebox.showerror(
                    "No Directory Selected",
                    "Please select a music directory containing audio files.",
                )
                return

            if not os.path.exists(folder):
                messagebox.showerror(
                    "Directory Not Found",
                    f"The selected directory does not exist:\n{folder}",
                )
                return

            if not os.path.isdir(folder):
                messagebox.showerror(
                    "Invalid Directory",
                    f"The selected path is not a valid directory:\n{folder}",
                )
                return

            try:
                has_audio: bool = any(
                    is_supported_format(f) for f in os.listdir(folder)
                )
                if not has_audio:
                    messagebox.showerror(
                        "No Audio Files",
                        f"No supported audio files found in:\n{folder}\n\n"
                        "Supported formats: MP3, FLAC, OGG, M4A, Opus, WAV, AIFF",
                    )
                    return
            except PermissionError as exc:
                messagebox.showerror(
                    "Access Denied",
                    f"Cannot access directory:\n{folder}\n\n{exc}",
                )
                return

            provider_name: str = self.provider.get().strip()
            if not provider_name:
                messagebox.showerror(
                    "No Lyric Source",
                    "Please select a lyric source provider.",
                )
                return

            try:
                get_provider(provider_name)
            except Exception as exc:
                mapped = map_to_audio_error(exc, context={"provider": provider_name})
                messagebox.showerror(
                    "Unknown Lyric Source",
                    f"'{provider_name}' is not a registered lyric source.\n\n"
                    f"{user_message_for(mapped)}",
                )
                return

            try:
                timeout: float = float(self.request_timeout.get().strip())
            except ValueError:
                messagebox.showerror(
                    "Invalid Timeout",
                    "Request Timeout must be a number of seconds.",
                )
                return
            if timeout <= 0:
                messagebox.showerror(
                    "Invalid Timeout",
                    "Request Timeout must be greater than zero.",
                )
                return

            workers: int = self.max_workers.get()
            if workers < 1:
                messagebox.showerror(
                    "Invalid Workers",
                    f"Number of workers must be at least 1 (current: {workers}).",
                )
                return

            # Persist settings
            _suite_config.save_value("lyrics_provider", self.provider.get())
            _suite_config.save_value("lyrics_request_timeout", timeout)
            _suite_config.save_value("lyrics_skip_existing", self.skip_existing.get())
            _suite_config.save_value("lyrics_plain_fallback", self.plain_fallback.get())
            _suite_config.save_value("lyrics_parallel_mode", self.parallel_mode.get())
            _suite_config.save_value("lyrics_max_workers", workers)

            # All validations passed — start processing.
            self.start_btn.config(state="disabled")
            self.notebook.select(self._tab_processing)
            self.overall_status.set("Looking up lyrics...")
            is_dry_run: bool = self.run_mode.get() == "Dry Run"
            parallel: bool = self.parallel_mode.get()
            logger.info(
                "start_processing: folder=%s dry_run=%s provider=%s timeout=%s "
                "skip_existing=%s plain_fallback=%s parallel=%s workers=%d",
                folder,
                is_dry_run,
                provider_name,
                timeout,
                self.skip_existing.get(),
                self.plain_fallback.get(),
                parallel,
                workers,
            )

            threading.Thread(
                target=self._run_fetch,
                args=(
                    folder,
                    is_dry_run,
                    provider_name,
                    timeout,
                    self.skip_existing.get(),
                    self.plain_fallback.get(),
                    parallel,
                    workers,
                ),
                daemon=True,
            ).start()

        except Exception as exc:
            mapped = map_to_audio_error(exc, context={"action": "start_processing"})
            logger.error(
                "[%s] Validation error in start_processing: %s",
                type(mapped).__name__,
                mapped,
                exc_info=True,
            )
            messagebox.showerror(
                "Validation Error",
                f"Failed to validate inputs:\n{user_message_for(mapped)}",
            )

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="lyrics_manager_app_run")
    def _run_fetch(
        self,
        dir_path: str,
        is_dry_run: bool,
        provider_name: str,
        request_timeout: float,
        skip_existing: bool,
        plain_fallback: bool,
        parallel_mode: bool = False,
        max_workers: int | None = None,
    ) -> None:
        """Background thread: delegate to file_processor.run_fetch."""
        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            "lyrics_dry_run_log.txt" if is_dry_run else "lyrics_sync_log.txt",
        )

        header: list[str] = [
            "LYRIC LOOKUP REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Provider: {provider_name}\n",
            f"Request Timeout: {request_timeout} seconds\n",
            f"Skip Existing Lyrics: {'Yes' if skip_existing else 'No'}\n",
            f"Store Unsynced Lyrics: {'Yes' if plain_fallback else 'No'}\n",
            f"Parallel: {'Yes' if parallel_mode else 'No'}\n",
            f"Workers: {max_workers or 4}\n",
            "=" * 60 + "\n",
        ]

        self.root.after(0, self._reset_progress_ui)

        with active_batch("lyrics_manager", "tag_edit"):
            file_processor.run_fetch(
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                provider_name=provider_name,
                request_timeout=request_timeout,
                skip_existing=skip_existing,
                plain_fallback=plain_fallback,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(header=header, **kw),
                on_error=self._on_error,
                parallel_mode=parallel_mode,
                max_workers=max_workers,
            )

    # ── Presets ───────────────────────────────────────────────────────────────
    def _collect_settings(self) -> dict[str, int | bool | str]:
        """Collect current UI settings into a dict for preset storage."""
        return {
            "provider": self.provider.get(),
            "request_timeout": self.request_timeout.get(),
            "skip_existing": self.skip_existing.get(),
            "plain_fallback": self.plain_fallback.get(),
            "parallel_mode": self.parallel_mode.get(),
            "max_workers": self.max_workers.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, int | bool | str]) -> None:
        """Apply a preset dict to the UI variables."""
        self.provider.set(str(settings.get("provider", "lrclib")))
        self.request_timeout.set(str(settings.get("request_timeout", 10.0)))
        self.skip_existing.set(bool(settings.get("skip_existing", True)))
        self.plain_fallback.set(bool(settings.get("plain_fallback", True)))
        self.parallel_mode.set(bool(settings.get("parallel_mode", False)))
        self.max_workers.set(int(settings.get("max_workers", 4)))
        self.run_mode.set(str(settings.get("run_mode", "Dry Run")))

    def _on_preset_selected(self, event: object = None) -> None:
        """Handle preset combobox selection change."""
        name: str = self._preset_combo.get() if self._preset_combo else ""
        if not name:
            return
        data: str | None = cast(
            str | None, _suite_config.load_value(f"lyrics_preset_{name}", None)
        )
        if data is not None:
            try:
                settings: dict[str, int | bool | str] = json.loads(data)
                self._apply_preset(settings)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.error("Failed to load preset '%s': %s", name, exc)

    def _save_current_as_preset(self) -> None:
        """Prompt for a name and save the current settings as a preset."""
        from tkinter.simpledialog import askstring

        name: str | None = askstring("Save Preset", "Preset name:", parent=self.root)
        if not name or not name.strip():
            return
        name = name.strip()
        settings: dict[str, int | bool | str] = self._collect_settings()
        _suite_config.save_value(f"lyrics_preset_{name}", json.dumps(settings))
        # Update the preset names list
        names_json: str | None = cast(
            str | None, _suite_config.load_value("lyrics_presets_list", None)
        )
        names: list[str] = json.loads(names_json) if names_json else []
        if name not in names:
            names.append(name)
        _suite_config.save_value("lyrics_presets_list", json.dumps(names))
        self._refresh_preset_list()

    def _delete_preset(self) -> None:
        """Delete the currently selected preset."""
        name: str = self._preset_combo.get() if self._preset_combo else ""
        if not name:
            return
        confirm: bool = messagebox.askyesno(
            "Delete Preset",
            f"Delete preset '{name}'?",
        )
        if not confirm:
            return
        # Remove from the preset names list
        names_json: str | None = cast(
            str | None, _suite_config.load_value("lyrics_presets_list", None)
        )
        names: list[str] = json.loads(names_json) if names_json else []
        if name in names:
            names.remove(name)
        _suite_config.save_value("lyrics_presets_list", json.dumps(names))
        self._refresh_preset_list()
