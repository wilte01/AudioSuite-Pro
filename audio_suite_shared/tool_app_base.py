"""
tool_app_base.py — Shared GUI app scaffold for the driver-launched
analyse-and-tag tools.

Extracted from the byte-near-identical app scaffolds in
``bpm_analyzer/app.py`` and ``lyrics_manager/app.py`` (iteration-7 B4,
audit A3 family 4). Each tool keeps its own Tk variables, its own start
validation, its own analysis call and its own preset value sets; the
plumbing around them — the CLI handshake apply, the folder/help/log
actions, the progress/complete/error plumbing and the completion log
write — lives here once.

Subclasses provide, before the shared methods run: ``root``,
``run_mode``, ``auto_start_var`` / ``auto_end_var`` / ``clear_logs_var``
/ ``parallel_var``, ``folder_path``, ``progress`` / ``stats_label`` /
``file_listbox`` (processing tab), ``time_label`` / ``summary_label`` /
``completion_label`` (results tab), ``start_btn``, ``notebook`` /
``_tab_results``, ``auto_end`` and ``_log_path``.  The class attributes
``TOOL_ID``, ``HELP_GUIDE``, ``TAGGED_LABEL``, ``DRY_COMPLETE_LABEL``
and ``LIVE_COMPLETE_LABEL`` carry the tool wording, and
``_apply_tool_cli_options`` hooks in the tool's own driver-provided
options.
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any

from audio_suite_shared import platform_utils
from audio_suite_shared.exceptions import map_to_audio_error
from audio_suite_shared.thread_safe_slot_var import ThreadSafeSlotVar
from audio_suite_shared.ui_helpers import UIHelperMixin

logger = logging.getLogger(f"audio_suite.{__name__}")


class AnalysisTagToolApp(UIHelperMixin):
    """Shared scaffold for the driver-launched analyse-and-tag GUI tools.

    See the module docstring for the expected instance attributes.
    """

    # ── Instance attributes the subclasses create (mypy shape surface) ───────
    root: tk.Tk
    run_mode: tk.StringVar
    auto_start_var: tk.BooleanVar
    auto_end_var: tk.BooleanVar
    clear_logs_var: tk.BooleanVar
    parallel_var: tk.BooleanVar
    folder_path: tk.StringVar
    progress: ttk.Progressbar
    stats_label: tk.Label
    file_listbox: tk.Listbox
    time_label: tk.Label
    summary_label: tk.Label
    completion_label: tk.Label
    start_btn: tk.Button
    notebook: ttk.Notebook
    _tab_results: tk.Frame
    _log_path: str
    auto_end: bool
    slot_queue: "Queue[int]"
    _safe_slot_vars: "list[ThreadSafeSlotVar]"

    def start_processing(self) -> None:
        """Subclass hook: validate inputs then launch the analysis thread."""
        raise NotImplementedError

    # ── Template attributes (subclass overrides) ─────────────────────────────
    TOOL_ID: str = ""
    HELP_GUIDE: str = ""

    #: Word used in the log/summary for the processed-but-neither-skipped-
    #: nor-erroring files ("Analyzed" for bpm, "Updated" for lyrics).
    TAGGED_LABEL: str = "Tagged/Analyzed"

    #: Results-tab completion captions.
    DRY_COMPLETE_LABEL: str = "Analysis Complete!"
    LIVE_COMPLETE_LABEL: str = "Tagging Complete!"

    def _apply_tool_cli_options(self, parsed: Any) -> None:
        """Hook: mirror tool-specific driver options before the early return.

        Args:
            parsed: The per-tool ``cli_args.parse()`` dataclass.
        """
        del parsed

    # ── Run Controls: CLI handshake ──────────────────────────────────────────

    def _apply_driver_cli_args(self, parsed: Any) -> None:
        """Apply a parsed Master-Driver handshake onto the tool's controls.

        Shared half of ``_apply_cli_args``: mirrors the driver display
        flags, runs the tool's ``_apply_tool_cli_options`` hook, then wires
        the folder path and the auto-start schedule. The per-tool
        ``parse()`` stays in the tool module so its tests keep patching
        ``cli_args.parse`` through that module.
        """

        # Mirror the inherited driver arguments onto the Run Controls
        # panel before any early return so the display always reflects
        # exactly what the Master Driver passed.
        self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        self._apply_tool_cli_options(parsed)

        if not parsed.folder_path:
            return

        cli_handler: Any = self._driver_cli_handler()(self)
        should_auto_start: bool = cli_handler.apply_cli_args(
            parsed,
            folder_var=self.folder_path,
            auto_start_func=self.start_processing,
        )

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    def _driver_cli_handler(self) -> Any:
        """Return the CLI handler class used by the shared apply block.

        Resolved from the subclass tool module first so a test that
        patched ``<tool>.app.UniversalCLIHandler`` keeps intercepting,
        then falls back to the shared implementation.
        """
        import sys

        tool_module = sys.modules.get(type(self).__module__)
        patched = getattr(tool_module, "UniversalCLIHandler", None)
        if patched is not None:
            return patched
        from audio_suite_shared.cli_helpers import UniversalCLIHandler

        return UniversalCLIHandler

    # ── User actions ─────────────────────────────────────────────────────────

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

    # ── Progress plumbing ────────────────────────────────────────────────────

    def _reset_progress_ui(self) -> None:
        """Reset UI progress indicators (must be called on main thread)."""
        self.progress["value"] = 0
        self.stats_label.config(text="Processed: 0 | Skipped: 0 | Errors: 0")

    def _on_progress(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        """Called from worker threads to update UI (scheduled on main thread)."""
        self.root.after(
            0, self._update_progress_ui, processed, total, skipped, errors, display_text
        )

    def _update_progress_ui(
        self,
        processed: int,
        total: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        """Update progress UI elements (must be called on main thread)."""
        self.progress["maximum"] = total
        self.progress["value"] = processed
        self.stats_label.config(
            text=f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}"
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

    def _on_complete(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
    ) -> None:
        """Called on the background thread after all files finish."""
        minutes: int = int(duration_secs // 60)
        seconds: int = int(duration_secs % 60)
        tagged: int = processed - skipped - errors

        summary: list[str] = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"{self.TAGGED_LABEL}: {tagged}\n",
            f"Skipped: {skipped}\n",
            f"Errors: {errors}\n",
            f"Time: {minutes:02d}:{seconds:02d}\n",
        ]
        all_entries: list[str] = header + log_entries + summary

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(all_entries)
            logger.info("Log written to '%s'", self._log_path)
        except PermissionError as exc:
            logger.error(
                "Permission denied writing log '%s': %s",
                self._log_path,
                exc,
                exc_info=True,
            )
        except OSError as exc:
            logger.error(
                "OSError writing log '%s': %s", self._log_path, exc, exc_info=True
            )
        except Exception as exc:
            mapped = map_to_audio_error(exc, context={"log_path": self._log_path})
            logger.error(
                "[%s] Unexpected error writing log: %s",
                type(mapped).__name__,
                mapped,
                exc_info=True,
            )

        self.root.after(
            0,
            self._update_ui_on_complete,
            total,
            tagged,
            skipped,
            errors,
            minutes,
            seconds,
        )

    def _update_ui_on_complete(
        self,
        total: int,
        tagged: int,
        skipped: int,
        errors: int,
        minutes: int,
        seconds: int,
    ) -> None:
        """Update UI after analysis completes (must be called on main thread)."""
        is_dry_run: bool = self.run_mode.get() == "Dry Run"
        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=(
                f"Total: {total} files\n"
                f"{self.TAGGED_LABEL}: {tagged}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        )
        self.completion_label.config(
            text=self.DRY_COMPLETE_LABEL if is_dry_run else self.LIVE_COMPLETE_LABEL
        )
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

        logger.info(
            "Processing complete — total=%d tagged=%d skipped=%d "
            "errors=%d time=%02d:%02d",
            total,
            tagged,
            skipped,
            errors,
            minutes,
            seconds,
        )

        if self.auto_end:
            self.root.after(2000, self.root.destroy)

    def _on_error(self, message: str) -> None:
        """Called when a fatal processing error occurs."""
        logger.error("Fatal processing error reported to UI: %s", message)
        self.root.after(0, self._show_error_dialog, message)

    def _show_error_dialog(self, message: str) -> None:
        """Show error dialog and re-enable start button (must be called on
        main thread)."""
        messagebox.showerror("Error", message)
        self.start_btn.config(state="normal")


#: Shared scaffold for Noise Reduction and Pop & Click Remover tools.
#: Inherits directly from UIHelperMixin (not AnalysisTagToolApp) because the
#: progress/complete signatures differ from the tagging family.
#: See noise_reduction/app.py and pop_click_remover/app.py for concrete subclasses.
#: Shared scaffold for Noise Reduction and Pop & Click Remover tools.
#: Inherits directly from UIHelperMixin (not AnalysisTagToolApp) because the
#: progress/complete signatures differ from the tagging family.
#: See noise_reduction/app.py and pop_click_remover/app.py for concrete subclasses.
