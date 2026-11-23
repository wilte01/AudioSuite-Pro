"""
tool_app_base.py — Shared GUI app scaffolds for the driver-launched tools.

One family remains, the analyse-and-tag scaffold:

* ``AnalysisTagToolApp`` — the analyse-and-tag tools, extracted in
  iteration-7 B4 (audit A3 family 4).

Each tool keeps its own Tk variables, its own start validation, its own
engine call and its own preset value sets; the plumbing around them — the
CLI handshake apply, the folder/help/log actions, the progress/complete/
error plumbing and the completion log write — lives here once.

Changed in 1.4.0: declares ``_launched_from_driver = False`` on
``AnalysisTagToolApp`` so a typed-worker cap call can log instead of showing a
modal warning on an unattended launch (D70).
Changed in 1.4.1: ``_summary_extras`` is a hook a tool overrides to add
``(label, value)`` rows to the run summary in both the log and the Results
panel, so BPM can report tempos that missed the configured band (D109).
Changed in 1.4.1: ``_on_progress`` accepts ``**_extra: Any`` like
``_on_complete``, so a progress field the processor adds cannot abort a running
batch (D112; locked by ``tests/test_callback_payload_contract.py``).
Changed in 2.8.0: the docstring no longer cites the denoiser as an example window.

Changed in 2.9.0: the run report's ``SUMMARY:`` footer is
``run_report.summary_lines``, the one implementation the shared shell
writes with too (D35).
Changed in 2.9.0: the source-folder opener is the shared mixin helper (A1).
Changed in 2.9.0: the progress-tick writes are the shared mixin helper (C1).
Changed in 2.9.0: the preset store is ``ui_presets.load_tool_preset`` /
``save_tool_preset`` / ``delete_tool_preset``, so a window that leaves this base
for ``SuiteApp`` keeps the same keys and the user's saved presets (C1 stage 2).

Changed in 2.9.0: ``NoisePopToolApp`` is deleted; its last subclass moved
to ``SuiteApp`` (D34), so only the analysis scaffold remains (D36).
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

from __future__ import annotations

import logging
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, Callable, ClassVar, cast

from audio_suite_shared.exceptions import map_to_audio_error
from audio_suite_shared.run_report import summary_lines
from audio_suite_shared.thread_safe_slot_var import (
    ThreadSafeSlotVar,
)
from audio_suite_shared.ui_helpers import UIHelperMixin
from audio_suite_shared.ui_presets import (
    delete_tool_preset,
    load_tool_preset,
    save_tool_preset,
)

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
    _preset_combo: ttk.Combobox | None
    _refresh_preset_list: "Callable[..., None] | None"
    #: Set from argv in each tool's ``__init__``.  The default keeps an
    #: ``object.__new__`` test shell on the interactive (modal-warning) path.
    _launched_from_driver: bool = False

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

    #: Config-key prefix for preset storage (``"bpm"`` / ``"lyrics"``).
    #: Subclasses set this so the shared preset methods build the correct
    #: ``suite_config`` keys (e.g. ``bpm_preset_MyPreset``).
    PRESET_KEY_PREFIX: ClassVar[str] = ""

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
        self._open_source_folder_standard()

    # ── Presets ─────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, int | bool | str]:
        """Hook: collect current UI settings into a serialisable dict.

        Used by ``_save_current_as_preset``.
        """
        raise NotImplementedError

    def _apply_preset(self, settings: dict[str, int | bool | str]) -> None:
        """Hook: apply a preset dict onto the tool's Tk variables."""
        raise NotImplementedError

    def _on_preset_selected(self, name: str) -> None:
        """Load a named preset and apply its settings."""
        settings = load_tool_preset(self.PRESET_KEY_PREFIX, name)
        if settings is not None:
            self._apply_preset(cast("dict[str, int | bool | str]", settings))

    def _save_current_as_preset(self, name: str) -> None:
        """Save the current settings as a named preset."""
        save_tool_preset(self.PRESET_KEY_PREFIX, name, self._collect_settings())
        if self._refresh_preset_list is not None:
            self._refresh_preset_list()

    def _delete_preset(self, name: str) -> None:
        """Delete a named preset."""
        delete_tool_preset(self.PRESET_KEY_PREFIX, name)
        if self._refresh_preset_list is not None:
            self._refresh_preset_list()

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
        **_extra: Any,
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
        self._render_progress_standard(processed, total, display_text)
        self.stats_label.config(
            text=f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}"
        )

    def _summary_extras(self) -> list[tuple[str, str]]:
        """Return ``(label, value)`` rows to add to this run's summary.

        Called by :meth:`_on_complete` once, after the run finishes, and again
        by :meth:`_update_ui_on_complete` when the panel is drawn, so both
        surfaces read the same rows.  A hook rather than a parameter: a tool
        that adds to the signature instead would break the ``on_complete``
        contract the shared base hands to every processor.  The default is no
        extra rows, which is exactly the old report.

        Returns:
            Extra summary rows, in display order.  Empty by default.
        """
        return []

    def _on_complete(
        self,
        header: list[str],
        total: int,
        processed: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        **_extra: Any,
    ) -> None:
        """Called on the background thread after all files finish.

        Tool-specific completion fields (for example BPM's ``skipped_files``
        and ``error_files``) are accepted and ignored: the CLI consumes them,
        while the GUI report needs only the shared counters and log.  Every
        tool's processor publishes them, so rejecting one here would abort the
        completion on the worker thread.
        """
        minutes: int = int(duration_secs // 60)
        seconds: int = int(duration_secs % 60)
        tagged: int = processed - skipped - errors
        extras: list[tuple[str, str]] = list(self._summary_extras())

        summary: list[str] = summary_lines(
            total=total,
            tagged=tagged,
            tagged_label=self.TAGGED_LABEL,
            skipped=skipped,
            errors=errors,
            duration_secs=duration_secs,
            rows=extras,
        )
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
            extras,
        )

    def _update_ui_on_complete(
        self,
        total: int,
        tagged: int,
        skipped: int,
        errors: int,
        minutes: int,
        seconds: int,
        summary_extras: list[tuple[str, str]] | None = None,
    ) -> None:
        """Update UI after analysis completes (must be called on main thread)."""
        is_dry_run: bool = self.run_mode.get() == "Dry Run"
        rows: list[tuple[str, str]] = (
            list(summary_extras)
            if summary_extras is not None
            else list(self._summary_extras())
        )
        text: str = (
            f"Total: {total} files\n"
            f"{self.TAGGED_LABEL}: {tagged}\n"
            f"Skipped: {skipped}\n"
            f"Errors: {errors}"
        )
        for label, value in rows:
            text += f"\n{label}: {value}"
        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(text=text)
        self.completion_label.config(
            text=self.DRY_COMPLETE_LABEL if is_dry_run else self.LIVE_COMPLETE_LABEL
        )
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

        logger.info(
            "Processing complete - total=%d tagged=%d skipped=%d "
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
