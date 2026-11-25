"""
app.py — AudioSuiteV6 orchestrator for Album Art Sync.
Contains the thread-safe on_pick bridge that connects background API
queries to the main-thread picker dialog.

Changed in 2.1.3: reads the album-art config through ``load_config()`` with no
argument, so the GUI and the CLI/batch pipeline resolve the same file (audit
R-04, plan B1). The call used to pass ``__file__``, which made this module read
``album_art_sync/album_art_config.json`` while the pipeline read
``album_art_sync/core/album_art_config.json``.

Changed in 2.5.0: presets moved off a tool-local ``presets.json`` onto the
shared ``suite_config`` preset store, and the save/delete prompts are the
shared ``ui_presets`` dialogs. A file left by an earlier version is imported
once and renamed (plan D-49).

Changed in 2.9.0: the source-folder opener is the shared mixin helper (A1).
Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2), so the shell owns
the Help bar and the Processing and Results tabs; this tool adds its Cancel
button to the shell's ``processing_panel``, its log lines fill the shared file
list, and the run report ends with the SUMMARY block the shell's contract
reads.
Changed in 2.9.0: the Processing tab's stats line counts the run — the file
total as soon as the folder is read, then the applier's per-file ticks — so it
no longer sits at zero for the whole run. A dry run writes nothing, so its line
counts what the run examined (``Examined: N / N (dry run, nothing written)``)
rather than claiming files were processed.
Changed in 2.9.0: the preset trio (select, save, delete) is the shell's,
so this window keeps only its own settings mapping (D58).

Changed in 2.9.0: Auto End is the shell's - the condition is
``auto_end_requested``, the sentence ``auto_end_sentence`` and the close
``close_for_auto_end`` - so this window's 2 s (3 s after a failure) is
stated once (D61).
"""

import json
import logging
import os
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Any, Optional

from audio_suite_shared import styles, suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.suite_app import (
    AUTO_END_CLOSE_MS,
    SuiteApp,
    auto_end_sentence,
)
from audio_suite_shared.suite_paths import package_path
from audio_suite_shared.tag_helper import (
    SUPPORTED_EXTENSIONS,
    read_album_artist,
    read_artist_album,
)
from audio_suite_shared.tag_helper_reader import read_musicbrainz_ids
from audio_suite_shared.ui_common import delete_preset_action, save_preset_dialog

from .api import source_resolver
from .config.settings import ALBUM_MATCH_THRESHOLD, MIN_ART_DIMENSION, load_config
from .core.artwork_applier import apply as apply_artwork
from .ui import main_tabs
from .ui.picker_dialog import PickerDialog
from .utils import cli_args

logger = logging.getLogger(__name__)
TOOL_ID = "album_art_sync"

#: Presets written by versions before 2.5.0, imported once into the shared
#: config and then renamed so a deleted preset cannot come back.
LEGACY_PRESETS_PATH: Path = package_path(__file__, "presets.json")


class AudioSuiteV6(SuiteApp):
    """Album Art Synchronizer application GUI."""

    title = "Album Art Synchronizer v6.0 (Optimized)"
    window_key = "album_art_sync_window"
    program_name = TOOL_ID
    guide_name = "Album_Art_Synchronizer_User_Guide.docx"
    completion_text = "Album Art Sync Complete!"
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" Setup ", " Processing ", " Results ")

    #: The key these presets live under in the shared store.
    TOOL_ID = TOOL_ID
    #: The settings a preset carries, in the order it has always stored them.
    PRESET_FIELDS = ("run_mode", "size_var", "purge_var")
    #: This window's saved keys are not its variables' names.
    PRESET_ALIASES = {
        "execution_mode": "run_mode",
        "embedded_resolution": "size_var",
        "purge_hidden": "purge_var",
    }

    def __init__(self, root: tk.Tk, pre_parsed: cli_args.ArtArgs | None = None) -> None:
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
        self._migrate_legacy_presets()

        # Thread-safe picker dialog
        self._picker = PickerDialog(root)

        # Pre-parsed CLI args supplied by the .pyw launcher (avoids double parse).
        self._pre_parsed_cli: cli_args.ArtArgs | None = pre_parsed

        super().__init__(root)
        self._apply_cli_args()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Shell tabs ────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the run controls, configuration and presets into *parent*."""
        widgets = main_tabs.build_setup_tab(
            parent,
            title=self.title,
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
            preset_names=self._preset_names(),
            on_save_preset=self._on_save_preset,
            on_delete_preset=self._on_delete_preset,
            on_preset_selected=self.use_preset,
        )
        self.start_btn = widgets["start_btn"]
        self._preset_combo = widgets["preset_combo"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self.controls_panel = widgets["controls_panel"]

    def _build_processing_tab(self, parent: tk.Frame) -> None:
        """Build the shared Processing tab, then add this tool's Cancel button."""
        super()._build_processing_tab(parent)
        self.cancel_btn = tk.Button(
            self.processing_panel,
            text="Cancel",
            bg="#999",
            fg="white",
            font=styles.FONT_BUTTON,
            command=self._cancel_operation,
            state=tk.DISABLED,
        )
        self.cancel_btn.pack(fill="x", pady=5)

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

    def _migrate_legacy_presets(self) -> None:
        """Import a pre-2.5.0 ``presets.json`` once, then rename it.

        The shared store wins when it already holds presets, so a user who has
        saved a preset since upgrading never sees an old file reappear after
        deleting everything; the legacy file is renamed rather than removed, so
        its contents stay available for manual recovery.
        """
        legacy = LEGACY_PRESETS_PATH
        if not legacy.is_file() or suite_config.list_presets(TOOL_ID):
            return
        try:
            with open(legacy, "r", encoding="utf-8") as f:
                stored = json.load(f)
        except (json.JSONDecodeError, OSError):
            logger.warning("Could not read legacy presets from %s", legacy)
            return
        if not isinstance(stored, dict):
            return
        imported = 0
        for name, settings in stored.items():
            if isinstance(settings, dict):
                suite_config.save_preset(TOOL_ID, str(name), settings)
                imported += 1
        try:
            legacy.replace(legacy.with_name(legacy.name + ".migrated"))
        except OSError:
            logger.warning("Could not rename legacy presets %s", legacy)
        logger.info(
            "Migrated %d album-art preset(s) from %s to the suite config",
            imported,
            legacy,
        )

    def _on_save_preset(self) -> None:
        """Ask for a name with the shared dialog and store the current settings."""
        if self._preset_combo is None:
            return
        save_preset_dialog(self._preset_combo, self.store_preset)

    def _on_delete_preset(self) -> None:
        """Confirm with the shared prompt and remove the selected preset."""
        if self._preset_combo is None:
            return
        delete_preset_action(self._preset_combo, self.remove_preset)

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _open_folder(self) -> None:
        """Open the source folder since Album Art Sync processes files in-place."""
        self._open_source_folder_standard()

    def _cancel_operation(self) -> None:
        self._cancel_requested = True
        self._add_log("[User requested cancellation...]")
        self.cancel_btn.config(state=tk.DISABLED)

    def start_thread(self) -> None:
        if getattr(self, "_running", False) or not self.folder_path.get():
            return
        self._running = True
        self.file_listbox.delete(0, tk.END)
        self._log_entries = []
        # No report for this run yet: _maybe_auto_end marks only the report a
        # run writes, never the previous run's.
        self._log_path = ""
        self._cancel_requested = False
        self.cancel_btn.config(state=tk.NORMAL)
        self.start_btn.config(state=tk.DISABLED)
        self.notebook.select(self.processing_frame)
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
    # is written from) and schedules the file-list update onto the Tk main
    # thread. update_idletasks is kept only to force a repaint -- it does not
    # make cross-thread Tk access safe.

    def _add_log(self, txt: str) -> None:
        """Append a line to the on-screen log and the in-memory log list."""
        self._log_entries.append(txt + "\n")
        self.root.after(0, self._append_log_line, txt)

    def _append_log_line(self, txt: str) -> None:
        """Append one line to the Processing tab's file list (main thread)."""
        self.file_listbox.insert(tk.END, txt)
        self.file_listbox.see(tk.END)
        self.root.update_idletasks()

    def _set_status(self, text: str) -> None:
        """Set the status label from any thread."""
        self.root.after(0, self._apply_status, text)

    def _apply_status(self, text: str) -> None:
        """Write the status label (must run on the main thread)."""
        self.overall_status.set(text)

    def _set_progress(self, value: int, maximum: int | None = None) -> None:
        """Update the progress bar from any thread."""
        self.root.after(0, self._apply_progress, value, maximum)

    def _apply_progress(self, value: int, maximum: int | None = None) -> None:
        """Write the progress bar (must run on the main thread)."""
        if maximum is None:
            self.progress.config(value=value)
        else:
            self.progress.config(value=value, maximum=maximum)

    def _set_stats(self, processed: int, total: int, *, dry_run: bool = False) -> None:
        """Update the stats line's file counter from any thread."""
        self.root.after(0, self._apply_stats, processed, total, dry_run)

    def _apply_stats(self, processed: int, total: int, dry_run: bool = False) -> None:
        """Write the stats line (must run on the main thread)."""
        if dry_run:
            self.stats_label.config(
                text=f"Examined: {processed} / {total} (dry run, nothing written)"
            )
        else:
            self.stats_label.config(text=f"Processed: {processed} / {total}")

    def _show_result(
        self,
        text: str,
        *,
        files: int = 0,
        source: str = "",
        duration_secs: float = 0.0,
    ) -> None:
        """Show a result message and switch to the results tab, from any thread."""
        self.root.after(0, self._apply_result, text, files, source, duration_secs)

    def _apply_result(
        self, text: str, files: int, source: str, duration_secs: float
    ) -> None:
        """Write the result widgets and select the results tab (main thread)."""
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        self.completion_label.config(text=text)
        self.summary_label.config(
            text=f"Files: {files}\nArtwork source: {source or 'none'}"
        )
        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.notebook.select(self.results_frame)

    def _show_results_tab(self) -> None:
        """Switch to the results tab from any thread."""
        self.root.after(0, self.notebook.select, self.results_frame)

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
        start = time.monotonic()
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

        # The stats line counts this run from the moment the folder is read, so
        # it shows the file total through the artwork search as well.  A dry run
        # writes nothing, so its line counts files examined, not processed.
        self._set_stats(0, len(files), dry_run=mode == "Dry Run")

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

        source_used: str | None = None
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
            self._show_result(
                "Error - See Log",
                files=len(files),
                source=source_used or "",
                duration_secs=time.monotonic() - start,
            )
            self._maybe_auto_end(delay_ms=3000)
            self._running = False
            self._restore_controls()
            return

        outcome = ""
        if self._cancel_requested:
            outcome = "Operation Cancelled"
            self._add_log("\n--- CANCELLED BY USER ---")
            self._show_result(
                outcome,
                files=len(files),
                source=source_used or "",
                duration_secs=time.monotonic() - start,
            )
            self._maybe_auto_end()
        elif img_raw:
            self._add_log(f"\n✓ Artwork retrieved from {source_used}")
            self._set_status("Applying artwork...")
            applier_mode = "Dry Run" if mode == "Dry Run" else "Update Artwork"
            self._set_progress(0, len(files))

            def _on_file_progress(i: int) -> None:
                self._set_progress(i)
                self._set_stats(i, len(files))

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

            if applier_mode == "Dry Run":
                # A dry run writes nothing, so the applier reports no per-file
                # ticks; it still examined the whole list, and the line says so
                # rather than freezing at the starting count.
                self._set_stats(len(files), len(files), dry_run=True)

            if success:
                outcome = f"Sync Complete via {source_used}"
                self._add_log("\n✓ Artwork sync completed successfully")
            else:
                outcome = "Partial Success - Check Log"
                self._add_log("\n⚠ Artwork sync completed with warnings")
            self._show_result(
                outcome,
                files=len(files),
                source=source_used or "",
                duration_secs=time.monotonic() - start,
            )
        else:
            outcome = "No Artwork Found"
            self._show_result(
                outcome,
                files=len(files),
                source=source_used or "",
                duration_secs=time.monotonic() - start,
            )
            self._add_log("\n✗ No artwork was found or selected")

        if not self._cancel_requested:
            self._write_run_report(
                folder=path,
                files=len(files),
                source=source_used or "",
                outcome=outcome,
                duration_secs=time.monotonic() - start,
            )
            self._add_log(f"\n✓ Log saved: {self._log_path}")
            self._show_results_tab()
            self._maybe_auto_end()

        self._running = False
        self._restore_controls()

    def _write_run_report(
        self,
        *,
        folder: str,
        files: int,
        source: str,
        outcome: str,
        duration_secs: float,
    ) -> None:
        """Serialise the run report View Log opens; a failed write is logged."""
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        summary = [
            "",
            "=" * 60,
            "SUMMARY:",
            f"Directory: {folder}",
            f"Files examined: {files}",
            f"Artwork source: {source or 'none'}",
            f"Outcome: {outcome or 'none'}",
            f"Time: {minutes:02d}:{seconds:02d}",
        ]
        self._log_path = os.path.join(folder, "art_sync_log.txt")
        try:
            with open(self._log_path, "w", encoding="utf-8") as handle:
                for line in [*self._log_entries, *summary]:
                    handle.write(line if line.endswith("\n") else line + "\n")
        except OSError as exc:
            logger.error(
                "Failed to write log '%s': %s", self._log_path, exc, exc_info=True
            )

    def _maybe_auto_end(self, delay_ms: int = AUTO_END_CLOSE_MS) -> None:
        """Show the Auto End sentence in the log, then close through the shell.

        The run this ends is on the worker thread; the sentence is queued with
        the other log lines and the shell marks the report this run just wrote.
        A cancelled or failed run wrote none, so nothing is marked.
        """
        if not self.auto_end_requested():
            return
        self._add_log(f"\n[{auto_end_sentence(delay_ms)}]")
        self.close_for_auto_end(delay_ms=delay_ms)
