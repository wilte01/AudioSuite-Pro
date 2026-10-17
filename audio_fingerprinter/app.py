"""
app.py
FingerprinterApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.

Changed in 1.2.0: adds the MusicBrainz enrichment and ISRC tag-write
toggles to the Setup tab and passes them into ``FingerprintParams``, plus the
ISRC submission toggle with its encrypted token (Sprint 2 Item 2.3).
Changed in 1.2.0: shows the ISRC submission outcome on the Results tab and
records the same line as the run's note, so a refused or offline submission is
visible in the Master Driver batch report without opening the run log.
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import filedialog, messagebox, ttk
from typing import Any

from audio_suite_shared import styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.run_outcome import record_outcome
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core import file_processor
from .core.fingerprinter import DEFAULT_MAX_LENGTH, FPCALC_ENV_VAR, resolve_fpcalc
from .core.models import (
    FingerprintFileResult,
    FingerprintParams,
    isrc_submission_note,
    isrc_submission_problem,
    status_text,
)
from .ui import processing_tab, results_tab, setup_tab
from .utils import api_key as api_key_store
from .utils import cli_args
from .utils import musicbrainz_token as mb_token_store

logger = logging.getLogger(__name__)

TOOL_ID = "audio_fingerprinter"

#: The Master Driver keys a batch step by the *manifest* id, which is
#: ``"fingerprinter"`` (``audio_suite_shared.tool_plugin``) and deliberately
#: differs from ``TOOL_ID`` above (the bootstrap/window key).  The run note must
#: be recorded under the manifest id or the driver never finds it; a test locks
#: the two together so a rename fails loudly rather than silently.
DRIVER_TOOL_ID = "fingerprinter"
_DEFAULT_THRESHOLD = "0.5"


class FingerprinterApp(UIHelperMixin):
    """Audio Fingerprinter application GUI."""

    HELP_GUIDE = "Audio_Fingerprinter_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Audio Fingerprinter",
            "audio_fingerprinter_window",
            TOOL_ID,
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")
        self.lookup_enabled = tk.BooleanVar(value=True)
        self.write_tags = tk.BooleanVar(value=False)
        self.write_mbids = tk.BooleanVar(value=False)
        self.mbid_region = tk.StringVar(
            value=str(suite_config.load_value("mbid_region", ""))
        )
        self.musicbrainz = tk.BooleanVar(value=False)
        self.write_isrc = tk.BooleanVar(value=False)
        self.submit_isrc = tk.BooleanVar(value=False)
        self.album_mode = tk.BooleanVar(value=False)
        self.threshold = tk.StringVar(value=_DEFAULT_THRESHOLD)
        self.max_length = tk.StringVar(value=str(DEFAULT_MAX_LENGTH))
        self.fpcalc_path = tk.StringVar()
        self.api_key = tk.StringVar()
        self.api_key_status = tk.StringVar()
        self.mb_token = tk.StringVar()
        self.mb_token_status = tk.StringVar()

        # Driver-mirrored run controls (Clear Logs / Parallel are display-only)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # ── State ─────────────────────────────────────────────────────────────
        self._log_path: str = ""
        self._out_dir: str = ""
        self._cli_api_key: str = ""

        # ── Worker slot pool ──────────────────────────────────────────────────
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        # ── Build UI ──────────────────────────────────────────────────────────
        self._build_ui()

        # ── Apply CLI arguments ───────────────────────────────────────────────
        self._apply_cli_args()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

        self._refresh_api_key_status()
        self._refresh_mb_token_status()
        self._update_fpcalc_status()

    # ── UI construction ───────────────────────────────────────────────────────

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

        tab_setup = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_processing = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_results = tk.Frame(self.notebook, bg=styles.BG_LIGHT)

        self.notebook.add(tab_setup, text=" 1. Setup ")
        self.notebook.add(tab_processing, text=" 2. Processing ")
        self.notebook.add(tab_results, text=" 3. Results ")

        widgets = setup_tab.build(
            tab_setup,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            lookup_enabled=self.lookup_enabled,
            write_tags=self.write_tags,
            write_mbids=self.write_mbids,
            mbid_region=self.mbid_region,
            musicbrainz=self.musicbrainz,
            write_isrc=self.write_isrc,
            submit_isrc=self.submit_isrc,
            album_mode=self.album_mode,
            threshold=self.threshold,
            max_length=self.max_length,
            fpcalc_path=self.fpcalc_path,
            api_key=self.api_key,
            api_key_status=self.api_key_status,
            on_browse=self._browse_folder,
            on_browse_fpcalc=self._browse_fpcalc,
            on_save_api_key=self._save_api_key,
            on_clear_api_key=self._clear_api_key,
            mb_token=self.mb_token,
            mb_token_status=self.mb_token_status,
            on_save_mb_token=self._save_mb_token,
            on_clear_mb_token=self._clear_mb_token,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
        )
        self.start_btn = widgets["start_btn"]
        self._update_fpcalc_status_cb = widgets["update_fpcalc_status"]

        proc_widgets = processing_tab.build(tab_processing, self.slot_vars)
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]

        res_widgets = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]  # type: ignore[assignment]
        self.summary_label: tk.Label = res_widgets["summary_label"]  # type: ignore[assignment]
        self.time_label: tk.Label = res_widgets["time_label"]  # type: ignore[assignment]
        self.isrc_label: tk.Label = res_widgets["isrc_label"]  # type: ignore[assignment]

        self._tab_setup = tab_setup
        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # ── API-key state ─────────────────────────────────────────────────────────

    def _refresh_api_key_status(self) -> None:
        """Update the caption describing where the API key resolves from."""
        from_env = os.environ.get(api_key_store.ENV_VAR, "").strip()
        stored = api_key_store.load_api_key()
        if from_env:
            text = "API key: set via the ACOUSTID_API_KEY environment variable."
        elif stored:
            text = "API key: stored (encrypted) in the suite config."
        else:
            text = "No API key configured — lookup will be skipped."
        self.api_key_status.set(text)

    def _save_api_key(self) -> None:
        """Encrypt and persist the key typed into the entry, then clear it."""
        value = self.api_key.get().strip()
        if not value:
            messagebox.showwarning("Empty API Key", "Enter the key before saving it.")
            return
        try:
            api_key_store.save_api_key(value)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            messagebox.showerror(
                "Save Failed",
                f"Could not save the API key:\n{user_message_for(mapped)}",
            )
            return
        self.api_key.set("")
        self._refresh_api_key_status()

    def _clear_api_key(self) -> None:
        """Remove the stored key and clear the entry."""
        api_key_store.clear_api_key()
        self.api_key.set("")
        self._refresh_api_key_status()

    def _refresh_mb_token_status(self) -> None:
        """Update the caption describing where the MusicBrainz token resolves."""
        self.mb_token_status.set(mb_token_store.describe_source())

    def _save_mb_token(self) -> None:
        """Encrypt and persist the token typed into the entry, then clear it."""
        value = self.mb_token.get().strip()
        if not value:
            messagebox.showwarning(
                "Empty Token", "Enter the MusicBrainz token before saving it."
            )
            return
        try:
            mb_token_store.save_token(value)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            messagebox.showerror(
                "Save Failed",
                f"Could not save the MusicBrainz token:\n{user_message_for(mapped)}",
            )
            return
        self.mb_token.set("")
        self._refresh_mb_token_status()

    def _clear_mb_token(self) -> None:
        """Remove the stored MusicBrainz token and clear the entry."""
        mb_token_store.clear_token()
        self.mb_token.set("")
        self._refresh_mb_token_status()

    def _persist_mbid_region(self) -> None:
        """Remember the MBID region preference in the shared suite config."""
        region = self.mbid_region.get().strip().upper()
        if len(region) != 2 or not region.isalpha():
            # Not a usable country code: forget any stale value rather than
            # letting an invalid preference silently bias release selection.
            suite_config.save_value("mbid_region", "")
            return
        suite_config.save_value("mbid_region", region)

    def _resolve_run_api_key(self) -> str:
        """Return the effective key: per-run entry, CLI --api-key, then store."""
        entry_value = self.api_key.get().strip()
        if entry_value:
            return entry_value
        if self._cli_api_key:
            return self._cli_api_key
        return api_key_store.load_api_key()

    # ── fpcalc state ──────────────────────────────────────────────────────────

    def _update_fpcalc_status(self) -> None:
        """Show whether the fpcalc binary resolves, and where it was found."""
        try:
            path = resolve_fpcalc(self.fpcalc_path.get().strip() or None)
        except Exception as exc:
            message = f"fpcalc not found: {user_message_for(map_to_audio_error(exc))}"
            self._update_fpcalc_status_cb(message, False)
            return
        source = (
            "explicit path"
            if self.fpcalc_path.get().strip()
            else ("FPCALC env var" if os.environ.get(FPCALC_ENV_VAR) else "PATH")
        )
        self._update_fpcalc_status_cb(f"fpcalc found ({source}): {path}", True)

    def _browse_fpcalc(self) -> None:
        path = filedialog.askopenfilename(
            title="Select fpcalc Executable",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")],
        )
        if path:
            self.fpcalc_path.set(path)
            self._update_fpcalc_status()

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        parsed = cli_args.parse()
        if not parsed.folder_path:
            return

        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed,
            folder_var=self.folder_path,
        )

        self.lookup_enabled.set(parsed.lookup_enabled)
        self.write_tags.set(parsed.write_tags)
        self.write_mbids.set(parsed.write_mbids)
        self.musicbrainz.set(parsed.musicbrainz)
        self.write_isrc.set(parsed.write_isrc)
        self.submit_isrc.set(parsed.submit_isrc)
        if parsed.mbid_region:
            self.mbid_region.set(parsed.mbid_region)
        self.threshold.set(str(parsed.threshold))
        self.max_length.set(str(parsed.max_length))
        if parsed.fpcalc_path:
            self.fpcalc_path.set(parsed.fpcalc_path)
        if parsed.api_key:
            self._cli_api_key = parsed.api_key
        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_folder(self) -> None:
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _open_help(self) -> None:
        """Open the help guide for Audio Fingerprinter."""
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        self._open_log_standard()

    def _open_folder(self) -> None:
        self._open_folder_standard()

    def _reset_ui(self) -> None:
        self.notebook.select(self._tab_setup)
        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        for var in self.slot_vars:
            var.set("IDLE")

    # ── Processing entry point ────────────────────────────────────────────────

    def _parse_threshold(self) -> float:
        try:
            value = float(self.threshold.get().strip())
        except ValueError:
            value = float(_DEFAULT_THRESHOLD)
        return max(0.0, min(value, 1.0))

    def _parse_max_length(self) -> int:
        try:
            value = int(self.max_length.get().strip())
        except ValueError:
            value = DEFAULT_MAX_LENGTH
        return max(1, min(value, 600))

    def start_processing(self) -> None:
        """Start fingerprinting with validation and error handling."""
        try:
            input_folder = self.folder_path.get().strip()
            if not input_folder:
                messagebox.showerror(
                    "No Input Directory",
                    "Please select a music directory containing audio files.",
                )
                return
            if not os.path.exists(input_folder) or not os.path.isdir(input_folder):
                messagebox.showerror(
                    "Input Not Found",
                    f"The input directory does not exist:\n{input_folder}",
                )
                return

            try:
                resolve_fpcalc(self.fpcalc_path.get().strip() or None)
            except Exception as exc:
                messagebox.showerror(
                    "fpcalc Required",
                    "fpcalc is not available.\n\n"
                    f"{user_message_for(map_to_audio_error(exc))}\n\n"
                    "Install the Chromaprint fpcalc binary, set the FPCALC "
                    "environment variable, or choose it with Browse.",
                )
                return

            if self.lookup_enabled.get() and not self._resolve_run_api_key():
                messagebox.showerror(
                    "API Key Required",
                    "Lookup is enabled but no AcoustID API key is configured.\n\n"
                    "Enter your key on the Setup tab (Save Key) or set the "
                    "ACOUSTID_API_KEY environment variable.",
                )
                return

            if self.submit_isrc.get() and not self.musicbrainz.get():
                messagebox.showerror(
                    "MusicBrainz Lookup Required",
                    "ISRC submission needs the MusicBrainz lookup: the recording "
                    "lookup is what tells the run which ISRCs are already "
                    "registered, so only new ones are submitted.",
                )
                return

            token_problem = (
                mb_token_store.build_auth().problem
                if self.submit_isrc.get() and self.run_mode.get() != "Dry Run"
                else ""
            )
            if token_problem:
                messagebox.showerror(
                    "MusicBrainz Token Required",
                    f"{token_problem}\n\n"
                    "A Dry Run shows the exact payload without submitting; a "
                    "Live Update needs the token.",
                )
                return

            threshold = self._parse_threshold()
            max_length = self._parse_max_length()
            self._persist_mbid_region()

            self.start_btn.config(state="disabled")
            self.file_listbox.delete(0, tk.END)
            self.notebook.select(self._tab_processing)
            self.overall_status.set("Fingerprinting...")

            params = FingerprintParams(
                lookup_enabled=self.lookup_enabled.get(),
                write_tags=self.write_tags.get(),
                is_dry_run=self.run_mode.get() == "Dry Run",
                threshold=threshold,
                max_length=max_length,
                fpcalc_path=self.fpcalc_path.get().strip(),
                album_mode=self.album_mode.get(),
                write_mbids=self.write_mbids.get(),
                mbid_region=self.mbid_region.get().strip().upper(),
                musicbrainz=self.musicbrainz.get(),
                write_isrc=self.write_isrc.get(),
                submit_isrc=self.submit_isrc.get(),
            )
            threading.Thread(target=self._run, args=(params,), daemon=True).start()

        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Processing Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Processing Error",
                f"Failed to start processing:\n{user_message_for(mapped)}",
            )

    @handle_audio_errors(reraise=False, context="fingerprinter_app_run")
    def _run(self, params: FingerprintParams) -> None:
        input_dir = self.folder_path.get()
        api_key = self._resolve_run_api_key()
        is_dry_run = params.is_dry_run
        mode = "dry_run" if is_dry_run else "live"

        log_name = f"fingerprint_{mode}_log.txt"
        self._log_path = os.path.join(input_dir, log_name)
        self._out_dir = input_dir
        self.progress["value"] = 0

        header: list[str] = [
            "AUDIO FINGERPRINTING REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Lookup: {'ON' if params.lookup_enabled else 'OFF'}\n",
            f"Write Tags: {'ON' if params.write_tags else 'OFF'}\n",
            f"Write MBIDs: {'ON' if params.write_mbids else 'OFF'}\n",
            f"MBID Region: {params.mbid_region or '(none)'}\n",
            f"MusicBrainz Enrichment: {'ON' if params.musicbrainz else 'OFF'}\n",
            f"Write ISRCs: {'ON' if params.write_isrc else 'OFF'}\n",
            f"Submit ISRCs: {'ON' if params.submit_isrc else 'OFF'}\n",
            f"Album Match: {'ON' if params.album_mode else 'OFF'}\n",
            f"Min Score: {params.threshold}\n",
            f"Max Length: {params.max_length} sec\n",
            f"Input Directory: {input_dir}\n",
            "=" * 60 + "\n",
        ]

        with active_batch("audio_fingerprinter", "tag_edit"):
            file_processor.run_fingerprinting(
                dir_path=input_dir,
                api_key=api_key,
                params=params,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(header=header, **kw),
                on_error=self._on_error,
                on_slot_update=self._on_slot_update,
                mb_auth=(mb_token_store.build_auth() if params.submit_isrc else None),
            )

    def _on_slot_update(self, slot_idx: int, text: str) -> None:
        self.root.after(0, self.slot_vars[slot_idx].set, text)

    def _on_progress(
        self,
        processed: int,
        total: int,
        errors: int,
        display_text: str = "",
    ) -> None:
        def _update() -> None:
            self.progress["maximum"] = total
            self.progress["value"] = processed
            self.stats_label.config(
                text=f"Processed: {processed} | Total: {total} | Errors: {errors}"
            )
            if display_text:
                self.file_listbox.insert(tk.END, display_text)
                self.file_listbox.see(tk.END)

        self.root.after(0, _update)

    def _on_complete(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        results: list[FingerprintFileResult],
        counts: dict[str, int],
        isrc_submission: dict[str, Any] | None = None,
    ) -> None:
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)

        summary: list[str] = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"Identified: {counts['identified']}\n",
            f"No match: {counts['no_match']}\n",
            f"Tags written: {counts['tagged']}\n",
            f"Lookup skipped: {counts['lookup_skipped']}\n",
        ]
        if counts.get("album_ambiguous"):
            summary.append(f"Album ambiguous: {counts['album_ambiguous']}\n")
        if isrc_submission:
            summary.append(f"{isrc_submission_note(isrc_submission)}\n")
            if isrc_submission.get("reason"):
                summary.append(f"  {isrc_submission['reason']}\n")
        summary.extend(
            [
                f"Errors: {counts['errors']}\n",
                f"Time: {minutes:02d}:{seconds:02d}\n",
            ]
        )

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(header + log_entries + summary)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Error", f"Could not write log file:\n{user_message_for(mapped)}"
            )

        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        summary_text = (
            f"Total: {total} files\n"
            f"Identified: {counts['identified']}\n"
            f"No Match: {counts['no_match']}\n"
            f"Tags Written: {counts['tagged']}\n"
            f"Errors: {counts['errors']}"
        )
        if counts.get("album_ambiguous"):
            summary_text += f"\nAlbum Ambiguous: {counts['album_ambiguous']}"
        self.summary_label.config(text=summary_text)
        self.completion_label.config(text="Fingerprinting Complete!")
        self._surface_isrc_outcome(isrc_submission)

        self.file_listbox.delete(0, tk.END)
        for result in sorted(results, key=lambda r: r.file_path):
            self.file_listbox.insert(
                tk.END, f"[{status_text(result.status)}] {result.filename}"
            )

        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

    def _surface_isrc_outcome(self, submission: dict[str, Any] | None) -> None:
        """Show the submission outcome, and record it for the Master Driver.

        A refused submission still leaves every file untouched and the run
        successful, so this is not an error dialog: it is a standing line on
        the Results tab, coloured red when the codes never reached MusicBrainz
        and green when they did (or there was nothing to send).  The same text
        is recorded as the run's note so a driver-launched batch reports it on
        the step line instead of only in ``fingerprint_*_log.txt``.

        Args:
            submission: The run's ``isrc_submission`` record, or None when the
                run did not request a submission.
        """
        if not submission:
            self.isrc_label.config(text="", fg=styles.FG_MAIN)
            return

        note = isrc_submission_note(submission)
        reason = str(submission.get("reason") or "").strip()
        text = f"{note}\n{reason}" if reason else note
        self.isrc_label.config(
            text=text,
            fg=styles.COLOR_ERROR
            if isrc_submission_problem(submission)
            else styles.COLOR_SUCCESS,
        )

        try:
            record_outcome(
                DRIVER_TOOL_ID, f"{note} \u2014 {reason}" if reason else note
            )
        except (OSError, ValueError) as exc:
            # The note only feeds the batch report; the outcome is already on
            # screen and in the run log, so it must never fail a finished run.
            logger.debug("Could not record the ISRC outcome for the driver: %s", exc)

    def _on_error(self, message: str) -> None:
        messagebox.showerror("Error", message)
        self.start_btn.config(state="normal")
