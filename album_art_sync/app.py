"""
app.py — AudioSuiteV6 orchestrator for Album Art Sync.
Contains the thread-safe on_pick bridge that connects background API
queries to the main-thread picker dialog.

Changed in 2.1.3: reads the album-art config through ``load_config()`` with no
argument, so the GUI and the CLI/batch pipeline resolve the same file (audit
R-04, plan B1). The call used to pass ``__file__``, which made this module read
``album_art_sync/album_art_config.json`` while the pipeline read
``album_art_sync/core/album_art_config.json``.
"""

import json
import logging
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Optional

from audio_suite_shared import platform_utils, styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.tag_helper import (
    SUPPORTED_EXTENSIONS,
    read_album_artist,
    read_artist_album,
)
from audio_suite_shared.tag_helper_reader import read_musicbrainz_ids
from audio_suite_shared.ui_helpers import UIHelperMixin

from .api import source_resolver
from .config.settings import ALBUM_MATCH_THRESHOLD, MIN_ART_DIMENSION, load_config
from .core.artwork_applier import apply as apply_artwork
from .ui import main_tabs
from .ui.picker_dialog import PickerDialog
from .utils import cli_args

logger = logging.getLogger(__name__)
TOOL_ID = "album_art_sync"


class AudioSuiteV6(UIHelperMixin):
    """Album Art Synchronizer application GUI."""

    HELP_GUIDE = "Album_Art_Synchronizer_User_Guide.docx"

    def __init__(self, root: tk.Tk, pre_parsed: cli_args.ArtArgs | None = None) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Album Art Synchronizer v6.0 (Optimized)",
            "album_art_sync_window",
            "album_art_sync",
        )

        # Tk variables
        self.folder_path = tk.StringVar()
        self.size_var = tk.StringVar(value="800")
        self.run_mode = tk.StringVar(value="Dry Run")
        self.purge_var = tk.BooleanVar(value=True)

        # CLI argument attributes for UniversalCLIHandler
        self.embed_size = self.size_var
        self.purge = self.purge_var

        # Driver-mirrored run controls (Clear Logs / Parallel are display-only)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        self._log_entries: list[Any] = []
        self._cancel_requested: bool = False
        self._running: bool = False  # guard against concurrent start_thread()
        self.auto_end: bool = False
        self._app_config: dict[str, Any] = load_config()

        # Presets
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # Thread-safe picker dialog
        self._picker = PickerDialog(root)

        # Pre-parsed CLI args supplied by the .pyw launcher (avoids double parse).
        self._pre_parsed_cli: cli_args.ArtArgs | None = pre_parsed

        self._build_ui()
        self._apply_cli_args()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Help button
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
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        self._tab_setup = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        self._tab_processing = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        self._tab_results = tk.Frame(self.notebook, bg=styles.BG_LIGHT)

        self.notebook.add(self._tab_setup, text=" Setup ")
        self.notebook.add(self._tab_processing, text=" Processing ")
        self.notebook.add(self._tab_results, text=" Results ")

        preset_names = list(self._load_presets().keys())

        setup = main_tabs.build_setup_tab(
            self._tab_setup,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            size_var=self.size_var,
            purge_var=self.purge_var,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_start=self.start_thread,
            driver_locked=self._launched_from_driver,
            on_browse=self._browse_folder,
            preset_names=preset_names,
            on_save_preset=self._on_save_preset,
            on_delete_preset=self._on_delete_preset,
            on_preset_selected=self._on_preset_selected,
        )
        self.start_btn = setup["start_btn"]
        self._preset_combo = setup["preset_combo"]
        self._refresh_preset_list = setup["refresh_preset_list"]

        proc = main_tabs.build_processing_tab(
            self._tab_processing, on_cancel=self._cancel_operation
        )
        self.status_txt: tk.StringVar = proc["status_txt"]
        self.progress: ttk.Progressbar = proc["progress"]
        self.log_list: tk.Listbox = proc["log_list"]
        self.cancel_btn: tk.Button = proc["cancel_btn"]

        self.res_msg = main_tabs.build_results_tab(
            self._tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        parsed = (
            self._pre_parsed_cli
            if self._pre_parsed_cli is not None
            else cli_args.parse()
        )
        if not parsed.folder_path:
            return

        # Mirror the driver's run controls onto the Setup tab panel.
        self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        # Universal CLI handling
        cli_handler = UniversalCLIHandler(self)
        cli_handler.apply_cli_args(
            parsed, folder_var=self.folder_path, auto_start_func=self.start_thread
        )

        # Auto-start if instructed by Master Driver (schedule after mainloop starts)
        if getattr(parsed, "auto_start", False):
            self.root.after(0, self.start_thread)

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, str | bool]:
        return {
            "execution_mode": self.run_mode.get(),
            "embedded_resolution": self.size_var.get(),
            "purge_hidden": self.purge_var.get(),
        }

    def _load_presets(self) -> dict[str, dict[str, Any]]:
        presets_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "presets.json"
        )
        if os.path.exists(presets_file):
            try:
                with open(presets_file, "r", encoding="utf-8") as f:
                    presets: dict[str, dict[str, Any]] = json.load(f)
                    return presets
            except (json.JSONDecodeError, OSError):
                return {}
        return {}

    def _save_presets(self, presets: dict[str, dict[str, Any]]) -> None:
        presets_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "presets.json"
        )
        with open(presets_file, "w", encoding="utf-8") as f:
            json.dump(presets, f, indent=2)

    def _refresh_preset_dropdown(self) -> None:
        presets = self._load_presets()
        if self._refresh_preset_list:
            self._refresh_preset_list(list(presets.keys()))

    def _on_save_preset(self) -> None:
        from tkinter.simpledialog import askstring

        name = askstring("Save Preset", "Enter preset name:", parent=self.root)
        if not name:
            return
        name = name.strip()
        if not name:
            return
        presets = self._load_presets()
        presets[name] = self._collect_settings()
        self._save_presets(presets)
        self._refresh_preset_dropdown()

    def _on_delete_preset(self) -> None:
        if not self._preset_combo:
            return
        name = self._preset_combo.get()
        if not name:
            return
        presets = self._load_presets()
        if name not in presets:
            return
        if messagebox.askyesno(
            "Delete Preset", f"Delete preset '{name}'?", parent=self.root
        ):
            del presets[name]
            self._save_presets(presets)
            self._refresh_preset_dropdown()

    def _on_preset_selected(self, preset_name: str) -> None:
        presets = self._load_presets()
        settings = presets.get(preset_name)
        if settings is not None:
            self._apply_preset(settings)

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "execution_mode" in settings:
            self.run_mode.set(str(settings["execution_mode"]))
        if "embedded_resolution" in settings:
            self.size_var.set(str(settings["embedded_resolution"]))
        if "purge_hidden" in settings:
            self.purge_var.set(bool(settings["purge_hidden"]))

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _open_help(self) -> None:
        self._open_help_standard(self.HELP_GUIDE)

    def _open_folder(self) -> None:
        """Open the source folder since Album Art Sync processes files in-place."""
        folder_path = self.folder_path.get()
        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Source folder not available.")

    def _open_log(self) -> None:
        platform_utils.open_path(
            os.path.join(self.folder_path.get(), "art_sync_log.txt")
        )

    def _cancel_operation(self) -> None:
        self._cancel_requested = True
        self._add_log("[User requested cancellation...]")
        self.cancel_btn.config(state=tk.DISABLED)

    def start_thread(self) -> None:
        if getattr(self, "_running", False) or not self.folder_path.get():
            return
        self._running = True
        self.log_list.delete(0, tk.END)
        self._log_entries = []
        self._cancel_requested = False
        self.cancel_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.DISABLED)
        self.notebook.select(self._tab_processing)
        # Snapshot every Tk variable on the main thread: _run_logic must not
        # call .get() off-thread (see its thread-safety note below).
        self._run_path = self.folder_path.get()
        self._run_mode = self.run_mode.get()
        self._run_embed_size = int(self.size_var.get())
        self._run_purge = self.purge_var.get()
        threading.Thread(target=self._run_logic, daemon=True).start()

    # ── Logging ────────────────────────────────────────────────────────────────
    #
    # Thread safety: _add_log is called from the worker thread, so it appends
    # to the plain in-memory list immediately (that list is what the log file
    # is written from) and schedules the Listbox update onto the Tk main
    # thread. update_idletasks is kept only to force a repaint -- it does not
    # make cross-thread Tk access safe.

    def _add_log(self, txt: str) -> None:
        """Append a line to the on-screen log and the in-memory log list."""
        self._log_entries.append(txt + "\n")
        self.root.after(0, self._append_log_line, txt)

    def _append_log_line(self, txt: str) -> None:
        """Append one line to the log Listbox (must run on the main thread)."""
        self.log_list.insert(tk.END, txt)
        self.log_list.see(tk.END)
        self.root.update_idletasks()

    def _set_status(self, text: str) -> None:
        """Set the status label from any thread."""
        self.root.after(0, self._apply_status, text)

    def _apply_status(self, text: str) -> None:
        """Write the status label (must run on the main thread)."""
        self.status_txt.set(text)

    def _set_progress(self, value: int, maximum: int | None = None) -> None:
        """Update the progress bar from any thread."""
        self.root.after(0, self._apply_progress, value, maximum)

    def _apply_progress(self, value: int, maximum: int | None = None) -> None:
        """Write the progress bar (must run on the main thread)."""
        if maximum is None:
            self.progress.config(value=value)
        else:
            self.progress.config(value=value, maximum=maximum)

    def _show_result(self, text: str) -> None:
        """Show a result message and switch to the results tab, from any thread."""
        self.root.after(0, self._apply_result, text)

    def _apply_result(self, text: str) -> None:
        """Write the result label and select the results tab (main thread only)."""
        self.res_msg.config(text=text)
        self.notebook.select(self._tab_results)

    def _show_results_tab(self) -> None:
        """Switch to the results tab from any thread."""
        self.root.after(0, self.notebook.select, self._tab_results)

    def _restore_controls(self) -> None:
        """Re-enable Start / disable Cancel from any thread (see _apply_controls)."""
        self.root.after(0, self._apply_controls)

    def _apply_controls(self) -> None:
        """Enable Start and disable Cancel (must run on the main thread)."""
        self.start_btn.config(state=tk.NORMAL)
        self.cancel_btn.config(state=tk.DISABLED)

    # ── Thread-safe picker bridge ─────────────────────────────────────────────

    def _on_pick(self, items: list[Any], artist: str, engine: str) -> Optional[bytes]:
        """
        Called from the background thread whenever an API returns candidates.
        Safely delegates to PickerDialog.show_threadsafe() which schedules
        the actual UI on the main thread and blocks here until the user responds.
        """
        return self._picker.show_threadsafe(items, artist, engine)

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="art_sync_app_run")
    def _run_logic(self) -> None:
        """Resolve artwork and embed it, on a worker thread.

        Thread safety: this runs off the Tk main thread, so it must not touch
        a widget or call ``.get()`` on a Tk variable. The inputs are
        snapshotted by ``start_thread`` on the main thread, and every UI write
        goes through the small ``_set_*``/``_show_*`` helpers above, which
        schedule a main-thread method via ``root.after(0, ...)``.
        """
        path = self._run_path
        mode = self._run_mode
        self._add_log(f"--- SESSION START: {mode.upper()} ---")
        self._add_log(f"Directory: {path}")

        if not os.path.exists(path):
            self._add_log("Error: Directory does not exist")
            self._running = False
            self._restore_controls()
            return

        files = [
            f for f in os.listdir(path) if f.lower().endswith(SUPPORTED_EXTENSIONS)
        ]
        if not files:
            self._add_log("Error: No supported audio files found in directory")
            self._running = False
            self._restore_controls()
            return

        # Read artist/album from first file.
        try:
            first_file = os.path.join(path, files[0])
            artist, album = read_artist_album(first_file)
            album_artist = read_album_artist(first_file)
            lookup_artist = album_artist if album_artist else artist
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
            self._add_log(
                f"Error reading file metadata:"
                f" {user_message_for(map_to_audio_error(exc))}"
            )
            self._running = False
            self._restore_controls()
            return

        self._add_log(f"Album: {lookup_artist} - {album}")
        # Never raises: an unreadable/untagged file yields an empty dict.
        album_mbid = read_musicbrainz_ids(first_file).get("MUSICBRAINZ_ALBUMID", "")
        if album_mbid:
            self._add_log(f"MusicBrainz release ID: {album_mbid}")
        self._add_log(f"Files: {len(files)} audio file(s)")
        self._add_log("")

        try:
            self._set_status("Searching for artwork...")
            # Use the Master Driver's per-run tuning values when launched via
            # the .pyw handshake; otherwise fall back to the suite defaults.
            parsed = getattr(self, "_pre_parsed_cli", None)
            min_dim = (
                parsed.min_art_dimension if parsed is not None else MIN_ART_DIMENSION
            )
            match_threshold = (
                parsed.album_match_threshold
                if parsed is not None
                else ALBUM_MATCH_THRESHOLD
            )
            img_raw, source_used = source_resolver.resolve(
                artist=lookup_artist,
                album=album,
                fanart_config=self._app_config.get("fanart", {}),
                min_art_dimension=min_dim,
                album_match_threshold=match_threshold,
                log=self._add_log,
                cancel_flag=lambda: self._cancel_requested,
                on_pick=self._on_pick,
                album_mbid=album_mbid,
            )
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
            self._add_log("\nCRITICAL ERROR: " + user_message_for(mapped))
            self._show_result("Error - See Log")
            self._maybe_auto_end(delay=3000)
            self._running = False
            self._restore_controls()
            return

        if self._cancel_requested:
            self._add_log("\n--- CANCELLED BY USER ---")
            self._show_result("Operation Cancelled")
            self._maybe_auto_end(delay=2000)
        elif img_raw:
            self._add_log(f"\n✓ Artwork retrieved from {source_used}")
            self._set_status("Applying artwork...")
            applier_mode = "Dry Run" if mode == "Dry Run" else "Update Artwork"
            self._set_progress(0, len(files))

            def _on_file_progress(i: int) -> None:
                self._set_progress(i)

            success = False
            with active_batch("album_art_sync", "tag_edit"):
                success = apply_artwork(
                    path=path,
                    files=files,
                    img_raw=img_raw,
                    mode=applier_mode,
                    embed_size=self._run_embed_size,
                    purge=self._run_purge,
                    log=self._add_log,
                    cancel_flag=lambda: self._cancel_requested,
                    on_file_progress=_on_file_progress,
                )

            if success:
                self._show_result(f"Sync Complete via {source_used}")
                self._add_log("\n✓ Artwork sync completed successfully")
            else:
                self._show_result("Partial Success - Check Log")
                self._add_log("\n⚠ Artwork sync completed with warnings")
        else:
            self._show_result("No Artwork Found")
            self._add_log("\n✗ No artwork was found or selected")

        if not self._cancel_requested:
            log_path = os.path.join(path, "art_sync_log.txt")
            with open(log_path, "w", encoding="utf-8") as f_log:
                f_log.writelines(self._log_entries)
            self._add_log(f"\n✓ Log saved: {log_path}")
            self._show_results_tab()
            self._maybe_auto_end(delay=2000)

        self._running = False
        self._restore_controls()

    def _maybe_auto_end(self, delay: int = 2000) -> None:
        if self.auto_end:
            self._add_log(
                f"\n[Auto End enabled - closing in {delay // 1000} seconds...]"
            )
            self.root.after(delay, self.root.destroy)
