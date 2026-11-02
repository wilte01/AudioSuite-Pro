# Changed in 2.4.0: duplicate dispositions and ASX stubs.
"""Tkinter window for the Duplicate Finder.

The window is an ``AnalysisTagToolApp`` on the suite's three standard tabs, with
a ``BaseSetupFrame`` Setup tab: the Run Controls strip supplies the source row,
the shared browse dialog and the Mode combobox, so a driven launch is locked and
the driver's Auto Start/Auto End are honoured.  The scan runs through
``core.file_processor.run_duplicate_scan`` — the ``run_*`` entry point taking
``on_progress`` / ``on_complete`` / ``on_error`` — and each run writes its report
into the folder it scanned, which is what the Results tab's View Log opens.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, ClassVar

from audio_suite_shared import styles
from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.run_outcome import record_caveats, shortfall
from audio_suite_shared.styles import bootstrap_theme
from audio_suite_shared.tool_app_base import AnalysisTagToolApp

from ..core.disposition import (
    DEFAULT_DISPOSITION,
    label_for,
    normalize,
    uses_trash,
)
from ..core.file_processor import (
    UNDO_OPERATION,
    default_quarantine_dir,
    run_duplicate_scan,
)
from ..core.models import DEFAULT_THRESHOLD, ScanSettings
from ..utils import cli_args
from . import processing_tab, results_tab, setup_tab

logger = logging.getLogger(__name__)

#: Manifest id the Master Driver keys this tool's batch step by; a note recorded
#: under any other string is never read (``tests/test_run_outcome_contract.py``).
DRIVER_TOOL_ID = "duplicate_finder"

#: The run reports the window writes into the folder it scanned, in the shape
#: every peer uses.  The literal lives here once: the user guide quotes the
#: names and ``tests/test_guide_claims.py`` requires a quoted name to exist in
#: the code that writes it.
RUN_REPORT_DRY_RUN = "duplicate_finder_dry_run_log.txt"
RUN_REPORT_LIVE = "duplicate_finder_sync_log.txt"

DRY_RUN = "Dry Run"
LIVE_UPDATE = "Live Update"
RUN_MODES = (DRY_RUN, LIVE_UPDATE)


class DuplicateFinderApp(AnalysisTagToolApp):
    """Tkinter window for the Duplicate Finder."""

    TOOL_ID: str = DRIVER_TOOL_ID
    HELP_GUIDE = "Duplicate_Finder_User_Guide.docx"

    #: Nothing is tagged or analysed here: every file is fingerprinted and then
    #: either grouped or kept, so the shared "processed" count is "files scanned".
    TAGGED_LABEL: str = "Files scanned"
    DRY_COMPLETE_LABEL: str = "Duplicate Scan Complete!"
    LIVE_COMPLETE_LABEL: str = "Duplicate Handling Complete!"

    #: Config-key prefix for the shared preset methods.  A ``ClassVar`` on the
    #: base, so it must stay one here: an instance annotation is an incompatible
    #: override and mypy rejects it.
    PRESET_KEY_PREFIX: ClassVar[str] = DRIVER_TOOL_ID

    #: Rows the finished run adds to the summary, replaced per completion so one
    #: run's rows cannot survive into the next.
    _summary_rows: tuple[tuple[str, str], ...] = ()

    def __init__(self, root: tk.Tk, *, apply_argv: bool = True) -> None:
        """Build the window, its variables and its run controls.

        Args:
            root: The Tk root the window is built in.
            apply_argv: Whether to apply the Master-Driver handshake from
                ``sys.argv``.  A direct caller passes False.
        """
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Duplicate Finder",
            "duplicate_finder_window",
            DRIVER_TOOL_ID,
        )

        self.folder_path: tk.StringVar = tk.StringVar()
        self.run_mode: tk.StringVar = tk.StringVar(value=DRY_RUN)
        self.threshold: tk.DoubleVar = tk.DoubleVar(value=DEFAULT_THRESHOLD)
        self.quarantine_dir: tk.StringVar = tk.StringVar()
        self.disposition: tk.StringVar = tk.StringVar(value=DEFAULT_DISPOSITION)

        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        #: Read by the shared completion handler, which closes the window when
        #: it is set.
        self.auto_end: bool = False

        #: Where the run's report goes; blank until a run starts, which makes
        #: View Log say so instead of opening the suite log.
        self._log_path: str = ""

        self._launched_from_driver = apply_argv and cli_args.looks_like_driver_argv()

        self._build_ui()
        if apply_argv:
            self._apply_driver_cli_args(cli_args.parse())

        self.root.update_idletasks()

        if not self.folder_path.get():
            last: str = _suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Window construction ───────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Build the Help bar, the three shared tabs and the Setup strip."""
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

        setup_widgets: dict[str, Any] = setup_tab.build(
            tab_setup,
            folder_path=self.folder_path,
            run_mode=self.run_mode,
            threshold=self.threshold,
            quarantine_dir=self.quarantine_dir,
            disposition=self.disposition,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            on_browse=self._browse_folder,
            on_browse_quarantine=self._browse_quarantine_folder,
            on_disposition_changed=self._set_disposition,
            on_start=self.start_processing,
            preset_names=_suite_config.list_presets(self.TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
            driver_locked=self._launched_from_driver,
        )
        self.start_btn: tk.Button = setup_widgets["start_btn"]
        self._preset_combo = setup_widgets.get("preset_combo")
        self._refresh_preset_list = setup_widgets.get("refresh_preset_list")
        self._setup_frame = setup_widgets.get("setup_frame")
        self._set_disposition(DEFAULT_DISPOSITION)

        proc_widgets: dict[str, Any] = processing_tab.build(tab_processing)
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.overall_status.set("Ready")

        res_widgets: dict[str, Any] = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]
        self.time_label: tk.Label = res_widgets["time_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]

        self._tab_processing = tab_processing
        self._tab_results = tab_results

    def _browse_quarantine_folder(self) -> None:
        """Browse for the quarantine folder, remembering the choice."""
        self._browse_folder_standard(
            title="Select Quarantine Folder",
            path_variable=self.quarantine_dir,
            save_last_dir=False,
        )

    def _set_disposition(self, value: str) -> None:
        """Apply a disposition everywhere the choice is reflected.

        Every route that writes the value — the combobox event, a preset load
        and the driver argv — calls this one function, so the variable and the
        dependent controls cannot disagree.

        Args:
            value: The selected disposition (raw or an alias).
        """
        canonical = normalize(value)
        self.disposition.set(canonical)
        frame = getattr(self, "_setup_frame", None)
        if frame is not None:
            frame.apply_disposition(canonical)

    def _apply_tool_cli_options(self, parsed: Any) -> None:
        """Mirror this tool's driver flags onto the Setup controls.

        Every route that writes a control has to reach the same widget the
        user's own edit would: a threshold or quarantine folder passed in argv
        and never applied here would leave the window showing the defaults
        while the run used the driver's values.

        Args:
            parsed: The per-tool ``cli_args.parse()`` dataclass.
        """
        if parsed.threshold:
            self.threshold.set(float(parsed.threshold))
        if parsed.quarantine_dir:
            self.quarantine_dir.set(parsed.quarantine_dir)
        self._set_disposition(str(getattr(parsed, "disposition", DEFAULT_DISPOSITION)))
        self.auto_end = bool(parsed.auto_end)

    # ── Run ───────────────────────────────────────────────────────────────

    def start_processing(self) -> None:
        """Validate the inputs, then launch the scan on a worker thread."""
        folder = self.folder_path.get().strip()
        if not folder:
            messagebox.showerror(
                "No Directory Selected",
                "Please select a music folder containing audio files.",
            )
            return
        if not os.path.isdir(folder):
            messagebox.showerror(
                "Directory Not Found",
                f"The selected folder does not exist:\n{folder}",
            )
            return

        threshold = float(self.threshold.get())
        if not 0.0 < threshold <= 1.0:
            messagebox.showerror(
                "Invalid Threshold",
                "The similarity threshold must be greater than 0 and at most 1.",
            )
            return

        dry_run = self.run_mode.get() == DRY_RUN
        disposition = normalize(self.disposition.get())
        quarantine = ""
        if disposition == DEFAULT_DISPOSITION:
            quarantine = self.quarantine_dir.get().strip() or default_quarantine_dir(
                folder
            )
            if not dry_run and os.path.normcase(os.path.abspath(quarantine)) == (
                os.path.normcase(os.path.abspath(folder))
            ):
                messagebox.showerror(
                    "Invalid Quarantine Folder",
                    "The quarantine folder cannot be the folder being scanned.",
                )
                return

        if not dry_run and uses_trash(disposition) and not self._launched_from_driver:
            if not messagebox.askyesno(
                "Remove duplicates?",
                f"{label_for(disposition)} sends every duplicate to the "
                "Recycle Bin. The kept copy is never modified. Continue?",
            ):
                return

        self._log_path = os.path.join(
            folder, RUN_REPORT_DRY_RUN if dry_run else RUN_REPORT_LIVE
        )
        self.start_btn.config(state="disabled")
        self.notebook.select(self._tab_processing)
        self.file_listbox.delete(0, tk.END)
        self._reset_progress_ui()
        self.overall_status.set("Scanning...")
        logger.info(
            "start_processing: folder=%s dry_run=%s threshold=%.2f",
            folder,
            dry_run,
            threshold,
        )

        threading.Thread(
            target=self._run_scan,
            args=(folder, dry_run, threshold, quarantine, disposition),
            daemon=True,
        ).start()

    @handle_audio_errors(reraise=False, context="duplicate_finder_app_run")
    def _run_scan(
        self,
        folder: str,
        is_dry_run: bool,
        threshold: float,
        quarantine: str,
        disposition: str,
    ) -> None:
        """Background thread: run the scan inside this run's undo batch.

        The report's header lines come from the processor's own payload rather
        than a second copy built here: two sources for one header drift, and
        the payload's version is the one the CLI prints.

        Args:
            folder: The directory to scan.
            is_dry_run: Whether the run may move files.
            threshold: Bit-error threshold for this run.
            quarantine: Destination folder for a live run; blank when the
                disposition does not use it.
            disposition: What the live run does with each duplicate.
        """
        settings = ScanSettings(
            threshold=threshold,
            quarantine_dir=quarantine,
            disposition=disposition,
        )
        with active_batch(self.TOOL_ID, UNDO_OPERATION):
            run_duplicate_scan(
                folder,
                is_dry_run,
                settings,
                on_progress=self._on_progress,
                on_complete=self._finish_run,
                on_error=self._on_error,
            )

    # ── Completion ────────────────────────────────────────────────────────

    def _finish_run(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        groups: int,
        duplicates: int,
        quarantined: int,
        deleted: int,
        stubbed: int,
        **_extra: Any,
    ) -> None:
        """Record this run's rows and note, then finish as every peer does.

        Wired as the ``on_complete`` handler itself rather than overriding
        ``_on_complete``: this tool's payload carries three counts the shared
        base never learns (``groups``, ``duplicates``, ``quarantined``), and a
        required field an override adds to the supertype's signature is a type
        error.  Declaring them required is the point — a default is how a
        dropped field becomes a plausible zero in the summary.

        Args:
            header: Report header lines for this run.
            total: Files the walk visited.
            processed: Files it finished visiting.
            skipped: Files it could not fingerprint.
            errors: Files it could not move.
            duration_secs: Wall-clock run time.
            log_entries: The per-file report lines.
            groups: Duplicate groups found.
            duplicates: Files identified as duplicates.
            quarantined: Files actually moved (always 0 in a dry run).
            deleted: Files moved to the Recycle Bin.
            stubbed: Files replaced by a verified ASX stub.
            **_extra: Other completion fields; ignored here rather than
                rejected, so a payload that grows cannot abort a finished run.
        """
        disposition = normalize(self.disposition.get())
        dry_run = self.run_mode.get() == DRY_RUN
        if disposition == DEFAULT_DISPOSITION:
            verb = "would quarantine" if dry_run else "quarantined"
            handled = quarantined
        elif disposition == "delete":
            verb = "would delete" if dry_run else "deleted"
            handled = deleted
        else:
            verb = "would stub" if dry_run else "stubbed"
            handled = stubbed
        self._summary_rows = (
            ("Duplicate groups", str(groups)),
            ("Duplicate files", str(duplicates)),
            (f"Files {verb}", str(handled)),
            ("Without a fingerprint", str(skipped)),
        )
        self._record_run_note(
            total=total, skipped=skipped, errors=errors, disposition=disposition
        )
        super()._on_complete(
            header=header,
            total=total,
            processed=processed,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            log_entries=log_entries,
            **_extra,
        )

    def _summary_extras(self) -> list[tuple[str, str]]:
        """Return this run's rows for the report and the Results panel."""
        return list(self._summary_rows)

    def _record_run_note(
        self, *, total: int, skipped: int, errors: int, disposition: str = ""
    ) -> None:
        """Record what this run could not fingerprint or move, for the driver.

        Args:
            total: Files the walk visited.
            skipped: Files without a fingerprint.
            errors: Files that could not be moved.
            disposition: The run's disposition, used in the caveat wording.
        """
        action = {
            "quarantine": "quarantined",
            "delete": "deleted",
            "asx-stub": "stubbed",
        }.get(normalize(disposition or self.disposition.get()), "handled")
        record_caveats(
            DRIVER_TOOL_ID,
            shortfall(errors, total, "file", f"could not be {action}")
            if errors
            else "",
            shortfall(skipped, total, "file", "had no readable fingerprint")
            if skipped
            else "",
        )

    # ── Presets ───────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        """Return the settings a preset stores."""
        return {
            "threshold": float(self.threshold.get()),
            "quarantine_dir": self.quarantine_dir.get(),
            "disposition": normalize(self.disposition.get()),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        """Apply a loaded preset onto this tool's variables."""
        if "threshold" in settings:
            self.threshold.set(float(settings["threshold"]))
        if "quarantine_dir" in settings:
            self.quarantine_dir.set(str(settings["quarantine_dir"]))
        self._set_disposition(str(settings.get("disposition", DEFAULT_DISPOSITION)))
        if "run_mode" in settings:
            self.run_mode.set(str(settings["run_mode"]))


def main() -> None:
    """Standalone entry point: create the Tk root and run the window."""
    root = tk.Tk()
    bootstrap_theme()
    apply_argv = cli_args.looks_like_driver_argv()
    app = DuplicateFinderApp(root, apply_argv=apply_argv)
    app.root.mainloop()
