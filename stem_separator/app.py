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
Changed in 2.9.0: the progress tick is the shared mixin helper (C1).
Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2), so the shell
owns the Help bar and the Processing and Results tabs; the report now ends
with the SUMMARY block the shell's contract reads.
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox
from typing import Any, cast

from audio_suite_shared import optional_deps, suite_config, ui_common
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import failure_reason
from audio_suite_shared.gpu_utils import resolve_device
from audio_suite_shared.suite_app import SuiteApp

from .core import demucs_engine
from .core.file_processor import run_stem_separation
from .core.models import (
    DEFAULT_MODEL,
    STEM_NAMES,
    StemSeparationParams,
    normalise_stems,
)
from .ui import setup_tab
from .utils import cli_args

logger = logging.getLogger(__name__)

TOOL_ID = "stem_separator"

#: Persisted between runs so a repeat separation reuses the same destination.
LAST_OUTPUT_KEY = "stem_separator_output_dir"


class StemSeparatorApp(SuiteApp):
    """Stem Separator application GUI."""

    title = "Stem Separator"
    window_key = "stem_separator_window"
    program_name = TOOL_ID
    guide_name = "Stem_Separator_User_Guide.docx"
    completion_text = "Stem Separation Complete!"
    # The labels this window has always shown; the shell does not renumber them.
    tab_labels = (" Setup ", " Processing ", " Results ")

    def __init__(self, root: tk.Tk) -> None:
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

        # The shell renders the worker grid from these before the tabs exist,
        # so the pool has to be ready before ``SuiteApp.__init__`` runs.
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self.slot_queue: Queue[int] = Queue()
        for index in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(index)
        self.cli_handler = UniversalCLIHandler(self)

        self._log_entries: list[str] = []

        super().__init__(root)
        self._refresh_device_status()
        self._apply_cli_args()

        if not self.folder_path.get():
            last: str = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Setup tab ─────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folder, output, stem and device controls into *parent*."""
        widgets = setup_tab.build(
            parent,
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
        self.start_btn: tk.Button = cast(tk.Button, widgets["start_btn"])
        self.controls_panel: Any = widgets.get("controls_panel")

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
        self.notebook.select(self.processing_frame)
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
        self._render_progress_standard(processed, max(total, 1), display_text)
        self.stats_label.config(
            text=(
                f"Processed: {processed} | Separated: {separated} | "
                f"Skipped: {skipped} | Errors: {errors}"
            )
        )

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
        """Completion seam: write the report here, render it on the Tk thread."""
        self._write_run_report(
            output_dir=output_dir,
            log_entries=log_entries,
            total=total,
            separated=separated,
            files_written=files_written,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            device=device,
        )
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

    def _write_run_report(
        self,
        *,
        output_dir: str,
        log_entries: list[str],
        total: int,
        separated: int,
        files_written: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        device: str,
    ) -> None:
        """Serialise the run report View Log opens; a failed write is logged."""
        log_path = os.path.join(output_dir, "stem_separation_log.txt")
        self._log_path = log_path
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        summary = [
            "",
            "=" * 60,
            "SUMMARY:",
            f"Files examined: {total}",
            f"Separated: {separated}",
            f"Stem files written: {files_written}",
            f"Skipped: {skipped}",
            f"Errors: {errors}",
            f"Device: {device}",
            f"Output: {output_dir}",
            f"Time: {minutes:02d}:{seconds:02d}",
        ]
        try:
            os.makedirs(output_dir, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as handle:
                for line in [*log_entries, *summary]:
                    handle.write(line if line.endswith("\n") else line + "\n")
        except OSError as exc:
            logger.error("Failed to write log '%s': %s", log_path, exc, exc_info=True)

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
        """Render the finished run (must run on the main thread)."""
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
        self.render_completion(duration_secs=duration_secs, output_dir=output_dir)

        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        logger.info(
            "Stem separation complete - total=%d separated=%d files=%d "
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
