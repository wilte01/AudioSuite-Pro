"""
app.py — MetadataScrubberApp orchestrator.
Wires UI, core logic, and utilities. Contains no business logic itself.

Tag preference persistence:
  - On Browse & Scan: load tag_prefs.json and pass saved set to populate_tags()
    so previously-kept tags are auto-ticked.
  - On completion of a LIVE run: save the ticked set back to tag_prefs.json
    (rolling 'last used' preference; dry runs don't update prefs).
"""

import logging
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any

from audio_suite_shared import styles, suite_config
from audio_suite_shared.app_bootstrap import BaseSuiteApp
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars

from .core import scrubber, tag_scanner
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args, tag_prefs

logger = logging.getLogger(__name__)

_PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
TOOL_ID = "metadata_scrubber"


class MetadataScrubberApp(BaseSuiteApp):
    """Metadata Scrubber application GUI."""

    HELP_GUIDE = "Metadata_Scrubber_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(
            root,
            "Metadata Scrubber & Tagger",
            "metadata_scrubber_window",
            "metadata_scrubber",
            help_guide=self.HELP_GUIDE,
        )
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)

        # Tk variables
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self.preserve_lyrics = tk.BooleanVar(value=True)
        self.preserve_album_artist = tk.BooleanVar(value=True)
        self.preserve_embedded_art = tk.BooleanVar(value=True)

        # Master Driver handshake: any CLI argument means driver-launched,
        # in which case the Run Controls panel is locked to inherited values.
        self._launched_from_driver = cli_args.was_launched_from_driver()

        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        self._build_ui()
        self._apply_cli_args()

        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)
                self.root.after(500, self._do_scan)

    def _build_ui(self) -> None:
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

        tab_setup_frame = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_processing_frame = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_results_frame = tk.Frame(self.notebook, bg=styles.BG_LIGHT)

        self.notebook.add(tab_setup_frame, text=" 1. Setup ")
        self.notebook.add(tab_processing_frame, text=" 2. Processing ")
        self.notebook.add(tab_results_frame, text=" 3. Results ")

        self._setup_tab = setup_tab.SetupTab(
            tab_setup_frame,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            preserve_lyrics=self.preserve_lyrics,
            preserve_album_artist=self.preserve_album_artist,
            preserve_embedded_art=self.preserve_embedded_art,
            on_browse_scan=self._browse_and_scan,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
            preset_names=suite_config.list_presets(TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
        )
        self.start_btn = self._setup_tab.start_btn
        self._refresh_preset_list = self._setup_tab.refresh_preset_list

        proc_widgets = processing_tab.build(tab_processing_frame, self.slot_vars)
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]

        res_widgets = results_tab.build(
            tab_results_frame,
            on_open_log=self._open_log_standard,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]
        self.time_label: tk.Label = res_widgets["time_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]

        self._tab_processing = tab_processing_frame
        self._tab_results = tab_results_frame

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "run_mode": self.run_mode.get(),
            "preserve_lyrics": self.preserve_lyrics.get(),
            "preserve_album_artist": self.preserve_album_artist.get(),
            "preserve_embedded_art": self.preserve_embedded_art.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])
        if "preserve_lyrics" in settings:
            self.preserve_lyrics.set(settings["preserve_lyrics"])
        if "preserve_album_artist" in settings:
            self.preserve_album_artist.set(settings["preserve_album_artist"])
        if "preserve_embedded_art" in settings:
            self.preserve_embedded_art.set(settings["preserve_embedded_art"])

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

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        parsed = cli_args.parse()

        # Mirror the inherited driver arguments onto the Run Controls
        # panel before any early return so the display always reflects
        # exactly what the Master Driver passed.
        self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        if not parsed.folder_path:
            return

        should_auto_start = self.cli_handler.apply_cli_args(
            parsed, folder_var=self.folder_path, auto_start_func=self._do_scan
        )

        self.root.after(500, self._do_scan)

        if should_auto_start:
            self.root.after(1000, self.start_processing)

    # ── User actions ──────────────────────────────────────────────────────────

    def _do_scan(self) -> None:
        folder = self.folder_path.get()
        if not folder:
            return

        def _report_scan_error(msg: str) -> None:
            # showerror returns a str; discard it to satisfy the callback contract.
            messagebox.showerror("Error", msg)

        discovered = tag_scanner.scan_custom_tags(
            folder,
            on_error=_report_scan_error,
        )

        previously_kept = tag_prefs.load_kept_tags(_PACKAGE_DIR)
        self._setup_tab.populate_tags(discovered, previously_kept=previously_kept)

        if self.auto_start:
            self.root.after(500, self.start_processing)

    def _browse_and_scan(self) -> None:
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )
        self._do_scan()

    def start_processing(self) -> None:
        folder = self.folder_path.get()
        if not folder:
            messagebox.showwarning("Warning", "Please select a music directory first.")
            return
        if not os.path.isdir(folder):
            messagebox.showerror("Error", "Selected path is not a valid directory.")
            return

        self.start_btn.config(state="disabled")
        self.notebook.select(self._tab_processing)
        self.overall_status.set("Scrubbing metadata...")

        preserve_list = self._setup_tab.get_preserve_list()
        preserve_lyrics = self.preserve_lyrics.get()
        preserve_album_artist = self.preserve_album_artist.get()
        preserve_embedded_art = self.preserve_embedded_art.get()
        is_live = self.run_mode.get() == "Live Update"

        threading.Thread(
            target=self._run_scrubbing,
            args=(
                preserve_list,
                preserve_lyrics,
                preserve_album_artist,
                preserve_embedded_art,
                is_live,
            ),
            daemon=True,
        ).start()

    @handle_audio_errors(reraise=False, context="metadata_scrubber_app_run")
    def _run_scrubbing(
        self,
        preserve_list: list[Any],
        preserve_lyrics: bool,
        preserve_album_artist: bool,
        preserve_embedded_art: bool,
        is_live: bool,
    ) -> None:
        dir_path = self.folder_path.get()
        is_dry_run = not is_live
        self._dir_path = dir_path
        self._log_path = os.path.join(
            dir_path,
            "metadata_dry_run_log.txt" if is_dry_run else "metadata_scrubbing_log.txt",
        )

        preserve_display = ", ".join(preserve_list) if preserve_list else "None"
        header = [
            "METADATA SCRUBBING REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Preserved Tags: {preserve_display}\n",
            f"Lyrics Preserved: {'Yes' if preserve_lyrics else 'No'}\n",
            f"Album Artist Preserved: {'Yes' if preserve_album_artist else 'No'}\n",
            f"Embedded Art Preserved: {'Yes' if preserve_embedded_art else 'No'}\n",
            "=" * 60 + "\n",
        ]

        self.progress["value"] = 0
        self.stats_label.config(text="Processed: 0 | Skipped: 0 | Errors: 0")

        with active_batch("metadata_scrubber", "tag_edit"):
            scrubber.run_scrubbing(
                dir_path=dir_path,
                is_dry_run=is_dry_run,
                preserve_list=preserve_list,
                preserve_lyrics=preserve_lyrics,
                preserve_album_artist=preserve_album_artist,
                preserve_embedded_art=preserve_embedded_art,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(
                    header=header, is_live=is_live, preserve_list=preserve_list, **kw
                ),
                on_error=self._on_error,
            )

    def _on_progress(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        self.progress["maximum"] = total
        self.progress["value"] = processed
        self.stats_label.config(
            text=f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}"
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

    def _on_complete(
        self,
        header: list[Any],
        is_live: bool,
        preserve_list: list[Any],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[Any],
    ) -> None:
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        succeeded = processed - skipped - errors

        summary = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"Successfully processed: {succeeded}\n",
            f"Skipped: {skipped}\n",
            f"Errors: {errors}\n",
            f"Time: {minutes:02d}:{seconds:02d}\n",
        ]
        all_entries = header + log_entries + summary

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(all_entries)
        except OSError as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Log write failed: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Error",
                f"Could not write log file:\n{user_message_for(mapped)}",
            )

        if is_live:
            tag_prefs.save_kept_tags(_PACKAGE_DIR, preserve_list)

        is_dry_run = not is_live
        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=f"Total: {total} files\n"
            f"Successfully processed: {succeeded}\n"
            f"Skipped: {skipped}\n"
            f"Errors: {errors}"
        )
        self.completion_label.config(
            text="Analysis Complete!" if is_dry_run else "Metadata Scrubbing Complete!"
        )
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

        if self.auto_end:
            all_entries.append("\n[Auto End enabled - closing in 2 seconds...]\n")
            try:
                with open(self._log_path, "w", encoding="utf-8") as f:
                    f.writelines(all_entries)
            except OSError as exc:
                logger.warning(
                    "Could not rewrite log for auto-end: %s", exc, exc_info=True
                )
            self.root.update_idletasks()
            self.root.after(2000, self.root.destroy)
