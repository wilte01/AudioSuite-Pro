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
Changed in 1.4.0: the fpcalc status line names the checkout's bundled binary
instead of claiming it came from PATH.

Changed in 1.4.1: ``_on_complete`` and ``_on_progress`` accept ``**_extra: Any``,
so a payload field the processor adds (D112) is ignored instead of aborting an
otherwise-finished run; ``tests/test_callback_payload_contract.py`` locks the
completion, progress and error seams.
Changed in 2.9.0: the progress tick is the shared mixin helper (C1).

Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2, the ninth window of
D8's wave 2), so the shell owns the Help bar and the Processing and Results
tabs and this tool keeps its Setup panel.  The ISRC submission line is the
shell's ``isrc_label`` (``result_extra_labels``), and the completion renders
through ``render_completion``: the report is written on the worker thread, then
every widget write — the summary, the ISRC line, the sorted file list and the
completion — happens on the Tk thread, so a finished run no longer touches Tk
from the processor's thread.  View Log and Open Folder are the shell's.

Changed in 2.9.0: the worker slot lines are queued by the processor's threads
and written by a poller the Tk thread starts, so the pool never calls
``root.after``, and the completion builds its summary text and records the
ISRC note on the worker, leaving the Tk thread only widget writes (D22).

Changed in 2.9.0: the progress ticks, the completion and a run error ride that
same queue, so nothing the run's own thread publishes calls ``root.after`` or
touches a widget either (D23).
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from pathlib import Path
from queue import Empty, Queue, SimpleQueue
from tkinter import filedialog, messagebox
from typing import Any

from audio_suite_shared import styles, suite_config
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.run_outcome import record_outcome
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars

from .core import file_processor
from .core.fingerprinter import (
    DEFAULT_MAX_LENGTH,
    FPCALC_ENV_VAR,
    SHIPPED_FPCALC,
    resolve_fpcalc,
)
from .core.models import (
    FingerprintFileResult,
    FingerprintParams,
    isrc_submission_note,
    isrc_submission_problem,
    status_text,
)
from .ui import setup_tab
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

#: How often the Tk thread drains the messages the run's threads queue.
_UI_POLL_MS = 100


def _isrc_outcome_text(submission: dict[str, Any] | None) -> tuple[str, str]:
    """The submission's outcome note and its reason.

    Args:
        submission: The run's ``isrc_submission`` record, or None.

    Returns:
        ``(note, reason)``, both empty when the run did not submit.  The report
        and the Results tab show the same pair, so it is read once.
    """
    if not submission:
        return "", ""
    return isrc_submission_note(submission), str(submission.get("reason") or "").strip()


class FingerprinterApp(SuiteApp):
    """Audio Fingerprinter application GUI."""

    title = "Audio Fingerprinter"
    window_key = "audio_fingerprinter_window"
    program_name = TOOL_ID
    #: Kept for the guide registry's scan; the shell reads ``guide_name``.
    HELP_GUIDE = "Audio_Fingerprinter_User_Guide.docx"
    guide_name = HELP_GUIDE
    # The labels this window has always shown; the shell does not renumber.
    tab_labels = (" 1. Setup ", " 2. Processing ", " 3. Results ")
    #: The heading the Results tab shows when a run finishes.
    completion_text = "Fingerprinting Complete!"
    #: This window counts processed files, identified matches and errors.
    processing_stats_text = "Processed: 0 | Identified: 0 | Errors: 0"
    #: The ISRC submission outcome sits below the Results summary; the shell
    #: builds it and publishes it on this instance under that name.
    result_extra_labels = ("isrc_label",)

    #: Set from argv in ``__init__``.  The default keeps an ``object.__new__``
    #: test shell on the interactive (modal-warning) path.
    _launched_from_driver: bool = False
    #: Set by ``_apply_cli_args`` when the launcher passes ``--api-key``.
    _cli_api_key: str = ""
    #: Built by the shell from ``result_extra_labels``.
    isrc_label: tk.Label
    #: Messages the run's threads queue for the Tk poller; built per run.
    _ui_updates: SimpleQueue[tuple[Any, ...]]
    #: The run's thread; the slot poller stops when it ends.
    _run_thread: threading.Thread | None = None

    def __init__(self, root: tk.Tk) -> None:
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

        # ── Worker slot pool ──────────────────────────────────────────────────
        # Built before super().__init__: the shell renders the grid from it.
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        super().__init__(root)

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

    # ── Shell tabs ────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder, the run settings, the key/token fields and the start."""
        widgets: dict[str, Any] = setup_tab.build(
            parent,
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
        self.controls_panel = widgets["controls_panel"]

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
        # Changed in 2.4.1: BLE001 triage (WP-7 of
        # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
        except Exception as exc:  # noqa: BLE001 - a save failure is shown in a dialog
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
        except Exception as exc:  # noqa: BLE001 - a save failure is shown in a dialog
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
        # BLE001 boundary: the status line reports missing fpcalc
        except Exception as exc:  # noqa: BLE001
            message = f"fpcalc not found: {user_message_for(map_to_audio_error(exc))}"
            self._update_fpcalc_status_cb(message, False)
            return
        if self.fpcalc_path.get().strip():
            source = "explicit path"
        elif os.environ.get(FPCALC_ENV_VAR):
            source = "FPCALC env var"
        elif Path(path) == SHIPPED_FPCALC:
            source = "bundled with the suite"
        else:
            source = "PATH"
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
            # BLE001 boundary: the dialog names the missing binary
            except Exception as exc:  # noqa: BLE001
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
            self.progress["value"] = 0
            self.file_listbox.delete(0, tk.END)
            self.notebook.select(self.processing_frame)
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
            # A fresh queue per run: the poller drains it and stops with the
            # run's thread, so no message from an earlier run can reach a row.
            self._ui_updates = SimpleQueue()
            self._run_thread = threading.Thread(
                target=self._run, args=(params,), daemon=True
            )
            self._run_thread.start()
            self._poll_ui_updates()

        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Processing Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Processing Error",
                f"Failed to start processing:\n{user_message_for(mapped)}",
            )

    # ── Background thread ─────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="fingerprinter_app_run")
    def _run(self, params: FingerprintParams) -> None:
        input_dir = self.folder_path.get()
        api_key = self._resolve_run_api_key()
        is_dry_run = params.is_dry_run
        mode = "dry_run" if is_dry_run else "live"

        log_name = f"fingerprint_{mode}_log.txt"
        self._log_path = os.path.join(input_dir, log_name)
        self._out_dir = input_dir

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

        with active_batch(TOOL_ID, "tag_edit"):
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

    # ── Callbacks (queued from the run's threads — no widget writes) ─────────

    def _on_slot_update(self, slot_idx: int, text: str) -> None:
        """Hand one worker's slot line to the Tk thread's poller.

        Called from the processor's pool, so it must not touch Tk: the line
        goes on the queue ``_poll_ui_updates`` drains (AGENTS.md).

        Args:
            slot_idx: The worker row the line belongs to.
            text: The line the worker published.
        """
        self._ui_updates.put(("slot", slot_idx, text))

    def _on_progress(
        self,
        processed: int,
        total: int,
        errors: int,
        display_text: str = "",
        **_extra: Any,
    ) -> None:
        """Queue one progress tick for the Tk thread's poller.

        Called from the run's threads, so it only queues; the tick is written
        by ``_drain_ui_updates``.

        Args:
            processed: Files finished so far.
            total: Files the run will attempt.
            errors: Files that failed so far.
            display_text: The per-file line the processor published.
            **_extra: The other progress fields the processor publishes.
        """
        self._ui_updates.put(("progress", processed, total, errors, display_text))

    def _on_error(self, message: str) -> None:
        """Queue a fatal run error for the Tk thread's poller.

        The processor publishes this from the run's thread, and the shell's
        handler raises a dialog, so it must be called from the Tk thread only.

        Args:
            message: The user-facing message the processor published.
        """
        self._ui_updates.put(("error", message))

    def _poll_ui_updates(self) -> None:
        """Apply the run's queued messages while its thread is alive.

        Runs on the Tk thread and re-schedules itself; the drain after the last
        tick delivers whatever was queued as the run finished — its completion,
        or the error that ended it.
        """
        self._drain_ui_updates()
        worker = self._run_thread
        if worker is not None and worker.is_alive():
            self.root.after(_UI_POLL_MS, self._poll_ui_updates)
            return
        self._drain_ui_updates()

    def _drain_ui_updates(self) -> None:
        """Write every queued message to its widget (Tk thread)."""
        while True:
            try:
                message = self._ui_updates.get_nowait()
            except Empty:
                return
            kind = message[0]
            if kind == "slot":
                _, slot_idx, text = message
                self.slot_vars[slot_idx].set(text)
            elif kind == "progress":
                _, processed, total, errors, display_text = message
                self._render_progress_standard(processed, total, display_text or None)
                self.stats_label.config(
                    text=f"Processed: {processed} | Total: {total} | Errors: {errors}"
                )
            elif kind == "error":
                _, text = message
                super()._on_error(text)
            elif kind == "complete":
                (
                    _,
                    summary_text,
                    duration_secs,
                    results,
                    isrc_text,
                    isrc_fg,
                    log_error,
                ) = message
                self._render_complete(
                    summary_text, duration_secs, results, isrc_text, isrc_fg, log_error
                )

    # ── Completion ────────────────────────────────────────────────────────────

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
        **_extra: Any,
    ) -> None:
        """Write the run report, then queue the Results update.

        Runs on the run's own thread: the report is written here, and every
        widget write is queued for the Tk poller, so neither a damaged Tk nor
        an unwritable log can suppress the other.

        Args:
            header: Report header lines for this run.
            total: Files the run set out to fingerprint.
            processed: Files it finished attempting.
            skipped: Files it skipped.
            errors: Files that could not be fingerprinted or looked up.
            duration_secs: Wall-clock run time.
            log_entries: The per-file log lines.
            results: One result per file, for the Results tab's list.
            counts: The run's per-outcome counters.
            isrc_submission: The run's submission record, or None.
            **_extra: The other tool-specific completion fields the processor
                always publishes; they feed the CLI's ``--json`` output.
        """
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
        isrc_note, isrc_reason = _isrc_outcome_text(isrc_submission)
        if isrc_note:
            summary.append(f"{isrc_note}\n")
            if isrc_reason:
                summary.append(f"  {isrc_reason}\n")
        summary.extend(
            [
                f"Errors: {counts['errors']}\n",
                f"Time: {minutes:02d}:{seconds:02d}\n",
            ]
        )

        log_error = ""
        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(header + log_entries + summary)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Error: %s", mapped, exc_info=True)
            log_error = user_message_for(mapped)

        if isrc_note:
            self._record_isrc_note(isrc_note, isrc_reason)

        summary_text = (
            f"Total: {total} files\n"
            f"Identified: {counts['identified']}\n"
            f"No Match: {counts['no_match']}\n"
            f"Tags Written: {counts['tagged']}\n"
            f"Errors: {counts['errors']}"
        )
        if counts.get("album_ambiguous"):
            summary_text += f"\nAlbum Ambiguous: {counts['album_ambiguous']}"

        isrc_fg = styles.FG_MAIN
        if isrc_submission:
            isrc_fg = (
                styles.COLOR_ERROR
                if isrc_submission_problem(isrc_submission)
                else styles.COLOR_SUCCESS
            )

        self._ui_updates.put(
            (
                "complete",
                summary_text,
                duration_secs,
                results,
                f"{isrc_note}\n{isrc_reason}" if isrc_reason else isrc_note,
                isrc_fg,
                log_error,
            )
        )

    def _render_complete(
        self,
        summary_text: str,
        duration_secs: float,
        results: list[FingerprintFileResult],
        isrc_text: str,
        isrc_fg: str,
        log_error: str,
    ) -> None:
        """Render the finished run (must run on the main thread).

        Args:
            summary_text: The Results tab's counters block.
            duration_secs: Wall-clock run time.
            results: One result per file, for the list below the summary.
            isrc_text: The submission outcome, or empty when there was none.
            isrc_fg: Colour for that line: red for a refused submission, green
                for one that landed, and the normal foreground otherwise.
            log_error: Why the report could not be written, or empty.
        """
        if log_error:
            messagebox.showerror("Error", f"Could not write log file:\n{log_error}")

        self.summary_label.config(text=summary_text)
        self.isrc_label.config(text=isrc_text, fg=isrc_fg)

        self.file_listbox.delete(0, tk.END)
        for result in sorted(results, key=lambda r: r.file_path):
            self.file_listbox.insert(
                tk.END, f"[{status_text(result.status)}] {result.filename}"
            )

        self.render_completion(duration_secs=duration_secs, output_dir=self._out_dir)

    def _record_isrc_note(self, note: str, reason: str) -> None:
        """Record the submission outcome for the Master Driver (worker thread).

        A refused submission still leaves every file untouched and the run
        successful, so this is not an error dialog: the outcome is a standing
        line on the Results tab and the same text is recorded as the run's note,
        so a driver-launched batch reports it on the step line instead of only
        in ``fingerprint_*_log.txt``.

        Args:
            note: The outcome line, e.g. ``ISRC submission: rejected (...)``.
            reason: The submission's reason, or empty.
        """
        try:
            record_outcome(
                DRIVER_TOOL_ID, f"{note} \u2014 {reason}" if reason else note
            )
        except (OSError, ValueError) as exc:
            # The note only feeds the batch report; the outcome is already in
            # the run log, so it must never fail a finished run.
            logger.debug("Could not record the ISRC outcome for the driver: %s", exc)
