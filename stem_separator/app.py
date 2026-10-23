"""
app.py
StemSeparatorApp — thin orchestrator for the Stem Separator.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).

Changed in 2.1.0: the run mode is applied from the driver's argv before the
    missing-``folder_path`` early return.  A standalone utility launch hands
    over an empty positional slot, so ``--live`` was parsed and then dropped
    and the window opened in Dry Run.

Changed in 2.1.0: a live run whose Demucs install is missing no longer stops
    with an "install the ml extra" dialog.  The tool installs Demucs itself on
    first use (verified by an import in a fresh process) and continues, which
    is also the only thing that works when the window was started by an
    interpreter other than the one ``uv sync`` installed into.
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, cast

from audio_suite_shared import optional_deps, styles, suite_config, ui_common
from audio_suite_shared.app_bootstrap import BaseSuiteApp
from audio_suite_shared.exceptions import failure_reason
from audio_suite_shared.gpu_utils import resolve_device

from .core import demucs_engine
from .core.file_processor import MAX_WORKERS, run_stem_separation
from .core.models import (
    DEFAULT_MODEL,
    STEM_NAMES,
    StemSeparationParams,
    normalise_stems,
)
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "stem_separator"

#: Persisted between runs so a repeat separation reuses the same destination.
LAST_OUTPUT_KEY = "stem_separator_output_dir"


class StemSeparatorApp(BaseSuiteApp):
    """Stem Separator application GUI."""

    HELP_GUIDE = "Stem_Separator_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        super().__init__(
            root,
            "Stem Separator",
            "stem_separator_window",
            TOOL_ID,
            help_guide=self.HELP_GUIDE,
            num_workers=MAX_WORKERS,
        )

        self.folder_path: tk.StringVar = tk.StringVar()
        saved_output = suite_config.load_value(LAST_OUTPUT_KEY, "")
        self.output_dir: tk.StringVar = tk.StringVar(
            value=saved_output if isinstance(saved_output, str) else ""
        )
        self.model: tk.StringVar = tk.StringVar(value=DEFAULT_MODEL)
        self.stem_vars: dict[str, tk.BooleanVar] = {
            stem: tk.BooleanVar(value=True) for stem in STEM_NAMES
        }
        self.write_mix: tk.BooleanVar = tk.BooleanVar(value=False)
        self.device: tk.StringVar = tk.StringVar(value="auto")
        self.device_status: tk.StringVar = tk.StringVar()
        self.run_mode: tk.StringVar = tk.StringVar(value="Dry Run")

        self.auto_start_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.auto_end_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.clear_logs_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.parallel_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        self._log_entries: list[str] = []
        self._log_path: str = ""
        self._out_dir: str = ""

        self._build_ui()
        self._refresh_device_status()
        self._apply_cli_args()

        if not self.folder_path.get():
            last: str = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Construct the full application UI."""
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

        self.notebook: ttk.Notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        tab_setup = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_processing = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_results = tk.Frame(self.notebook, bg=styles.BG_LIGHT)

        self.notebook.add(tab_setup, text=" Setup ")
        self.notebook.add(tab_processing, text=" Processing ")
        self.notebook.add(tab_results, text=" Results ")

        setup_widgets = setup_tab.build(
            tab_setup,
            folder_path=self.folder_path,
            output_dir=self.output_dir,
            model=self.model,
            stem_vars=self.stem_vars,
            write_mix=self.write_mix,
            device=self.device,
            device_status=self.device_status,
            run_mode=self.run_mode,
            on_browse=self._browse_folder,
            on_browse_output=self._browse_output,
            on_refresh_device=self._refresh_device_status,
            on_start=self.start_processing,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            driver_locked=self._launched_from_driver,
        )
        self.start_btn: tk.Button = cast(tk.Button, setup_widgets["start_btn"])

        proc_widgets = processing_tab.build(tab_processing, self.slot_vars)
        self.overall_status: tk.StringVar = cast(
            tk.StringVar, proc_widgets["overall_status"]
        )
        self.progress: ttk.Progressbar = cast(ttk.Progressbar, proc_widgets["progress"])
        self.stats_label: tk.Label = cast(tk.Label, proc_widgets["stats_label"])
        self.file_listbox: tk.Listbox = cast(tk.Listbox, proc_widgets["file_listbox"])

        res_widgets = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
        )
        self.completion_label: tk.Label = cast(
            tk.Label, res_widgets["completion_label"]
        )
        self.time_label: tk.Label = cast(tk.Label, res_widgets["time_label"])
        self.summary_label: tk.Label = cast(tk.Label, res_widgets["summary_label"])

        self._tab_processing = tab_processing
        self._tab_results = tab_results

    def _apply_cli_args(self) -> None:
        """Parse and apply any command-line arguments."""
        parsed = cli_args.parse()
        if parsed.output_dir:
            self.output_dir.set(parsed.output_dir)
        if parsed.model:
            self.model.set(parsed.model)
        if parsed.stems:
            selected = set(parsed.stems)
            for stem, var in self.stem_vars.items():
                var.set(stem in selected)
        self.write_mix.set(parsed.mix)
        if parsed.device:
            self.device.set(parsed.device)

        # The run mode is a setting of its own, not part of the folder
        # handshake below: the Master Driver passes the mode picked in its
        # toolbar even when it hands over no source folder (a standalone
        # launch), and applying it only when ``folder_path`` arrived is how a
        # launched separator opened in Dry Run while the toolbar showed Live
        # Update.
        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")

        if not parsed.folder_path:
            return

        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        should_auto_start: bool = self.cli_handler.apply_cli_args(
            parsed,
            folder_var=self.folder_path,
        )

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    def _browse_folder(self) -> None:
        """Browse for a music directory."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _browse_output(self) -> None:
        """Browse for the directory the stems are written into."""
        self._browse_folder_standard(
            title="Select Stem Output Directory",
            path_variable=self.output_dir,
            save_last_dir=False,
        )
        selected = self.output_dir.get().strip()
        if selected:
            suite_config.save_value(LAST_OUTPUT_KEY, selected)

    def _refresh_device_status(self) -> None:
        """Re-read the device torch reports and show what it measured."""
        try:
            info = resolve_device(self.device.get())
        except ValueError as exc:
            self.device_status.set(str(exc))
            return
        self.device_status.set(f"{info.label()} — {info.reason}")

    # ── Run ───────────────────────────────────────────────────────────────

    def _selected_stems(self) -> tuple[str, ...]:
        """Return the stems ticked on the Setup tab."""
        return tuple(stem for stem in STEM_NAMES if self.stem_vars[stem].get())

    def _validate_start(self) -> str | None:
        """Return why the run cannot start, or None when it can."""
        folder = self.folder_path.get().strip()
        if not folder:
            return "Please select a music directory."
        if not os.path.exists(folder):
            return f"Directory not found:\n{folder}"
        if not os.path.isdir(folder):
            return f"Not a valid directory:\n{folder}"

        output = self.output_dir.get().strip()
        if not output:
            return "Choose an output directory for the separated stems."
        if os.path.exists(output) and not os.path.isdir(output):
            return f"The output path is a file, not a folder:\n{output}"

        # An empty tick-box set is *not* the same as "no selection made":
        # ``normalise_stems(())`` means all four for a headless default, so the
        # GUI has to refuse an explicit nothing-ticked itself.
        selected = self._selected_stems()
        if not selected:
            return "Select at least one stem to export."
        try:
            normalise_stems(selected)
        except ValueError:
            return "Select at least one stem to export."
        return None

    def start_processing(self) -> None:
        """Validate the run, provide Demucs when needed, then start it.

        A missing Demucs is no longer a refusal: the tool installs it (once)
        at the moment a live run first needs it, then continues on its own.
        """
        problem = self._validate_start()
        if problem:
            messagebox.showwarning("Cannot Start", problem)
            return

        if (
            self.run_mode.get() == "Live Update"
            and demucs_engine.missing_dependency_reason() is not None
        ):
            ui_common.install_optional_dependency(
                self.root,
                optional_deps.DEMUCS,
                on_ready=self._begin_run,
            )
            return

        self._begin_run()

    def _begin_run(self) -> None:
        """Start the separation thread for the settings already validated."""
        folder = self.folder_path.get().strip()
        output = self.output_dir.get().strip()
        suite_config.save_value(LAST_OUTPUT_KEY, output)

        params = StemSeparationParams(
            output_dir=output,
            stems=self._selected_stems(),
            model=self.model.get(),
            write_mix=self.write_mix.get(),
            device=self.device.get(),
            dry_run=self.run_mode.get() != "Live Update",
        )

        logger.info(
            "start_processing: folder=%s output=%s model=%s stems=%s "
            "mix=%s device=%s dry_run=%s",
            folder,
            output,
            params.model,
            params.resolved_stems(),
            params.write_mix,
            params.device,
            params.dry_run,
        )

        self.start_btn.config(state="disabled")
        self.notebook.select(self._tab_processing)
        self.overall_status.set("Separating stems...")

        threading.Thread(
            target=self._run_separation,
            args=(folder, params),
            daemon=True,
        ).start()

    def _run_separation(self, directory: str, params: StemSeparationParams) -> None:
        """Background thread: run the processor and route fatal errors to the UI.

        Per-file failures are already reported by the processor through
        ``on_progress``; only a fatal error (missing Demucs, unreadable
        directory) arrives here, and it must reach the dialog rather than
        dying silently in the thread.
        """
        self._out_dir = params.output_dir
        self._log_entries = []
        # The log path must exist before the first progress line is appended
        # from a worker thread; the completion render rewrites the file.
        self._log_path = os.path.join(params.output_dir, "stem_separation_log.txt")
        try:
            run_stem_separation(
                directory,
                params,
                self._safe_slot_vars(),
                self.slot_queue,
                on_progress=self._on_progress,
                on_complete=self._on_complete,
                on_error=self._on_error,
            )
        except Exception as exc:
            logger.error("Stem separation run failed", exc_info=True)
            self.root.after(0, self._on_error, failure_reason(exc))

    def _safe_slot_vars(self) -> list[Any]:
        """Return the slot variables the processing tab renders."""
        return cast(list[Any], self.slot_vars)

    # ── Callbacks ─────────────────────────────────────────────────────────

    def _reset_progress_ui(self) -> None:
        self.progress["value"] = 0
        self.stats_label.config(text="Processed: 0 | Separated: 0 | Errors: 0")
        self.file_listbox.delete(0, tk.END)

    def _on_progress(
        self,
        processed: int,
        total: int,
        separated: int,
        skipped: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
        """Thread-safe progress handler: log here, touch widgets on the Tk thread."""
        self._log_entries.append(display_text)
        if self._log_path:
            with open(self._log_path, "a", encoding="utf-8") as handle:
                handle.write(display_text + "\n")
        self.root.after(
            0,
            self._update_progress_ui,
            processed,
            total,
            separated,
            skipped,
            errors,
            display_text,
        )

    def _update_progress_ui(
        self,
        processed: int,
        total: int,
        separated: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        self.progress["maximum"] = max(total, 1)
        self.progress["value"] = processed
        self.stats_label.config(
            text=(
                f"Processed: {processed} | Separated: {separated} | "
                f"Skipped: {skipped} | Errors: {errors}"
            )
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

    def _on_complete(
        self,
        total: int,
        processed: int,
        separated: int,
        files_written: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        output_dir: str,
        device: str,
        **_extra: Any,
    ) -> None:
        """Completion seam: forward the published payload to the UI render."""
        self.root.after(
            0,
            self._update_ui_on_complete,
            total,
            processed,
            separated,
            files_written,
            skipped,
            errors,
            duration_secs,
            log_entries,
            output_dir,
            device,
        )

    def _update_ui_on_complete(
        self,
        total: int,
        processed: int,
        separated: int,
        files_written: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        output_dir: str,
        device: str,
    ) -> None:
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)

        # The processor's log lines are the report; the live handler appended
        # as the run went, so rewrite the file from the completion payload.
        log_path = os.path.join(output_dir, "stem_separation_log.txt")
        self._log_path = log_path
        try:
            os.makedirs(output_dir, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as handle:
                for line in log_entries:
                    handle.write(line if line.endswith("\n") else line + "\n")
        except OSError as exc:
            logger.error("Failed to write log '%s': %s", log_path, exc, exc_info=True)

        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=(
                f"Files examined: {total}\n"
                f"Separated: {separated}\n"
                f"Stem files written: {files_written}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}\n"
                f"Device: {device}\n"
                f"Output: {output_dir}"
            )
        )
        self.completion_label.config(text="Stem Separation Complete!")
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

        logger.info(
            "Stem separation complete — total=%d separated=%d files=%d "
            "skipped=%d errors=%d device=%s time=%02d:%02d",
            total,
            separated,
            files_written,
            skipped,
            errors,
            device,
            minutes,
            seconds,
        )

        if self.auto_end_var.get():
            self.root.after(2000, self.root.destroy)


def main() -> None:
    """Standalone entry point: create the Tk root, run the app."""
    root = tk.Tk()
    StemSeparatorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
