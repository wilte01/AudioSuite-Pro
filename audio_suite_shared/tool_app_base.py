"""
tool_app_base.py — Shared GUI app scaffolds for the driver-launched tools.

Two families share near-identical scaffolding:

* ``AnalysisTagToolApp`` — the analyse-and-tag tools (bpm_analyzer,
  lyrics_manager).  Extracted in iteration-7 B4 (audit A3 family 4).
* ``NoisePopToolApp`` — the DSP/undo tools (noise_reduction,
  pop_click_remover).  Extracted in iteration-8 E2 (audit M5).

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
Changed in 2.0.0: ``NoisePopToolApp``'s progress and completion handlers accept
``**_extra: Any`` too, so the ML Denoiser can bind them directly and be covered
by the callback-payload lock instead of hiding behind a local wrapper
(Sprint 6, Item 6.2).
"""

from __future__ import annotations

import json
import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, Callable, ClassVar, cast

from audio_suite_shared import platform_utils, styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import map_to_audio_error
from audio_suite_shared.thread_safe_slot_var import (
    ThreadSafeSlotVar,
    make_safe_slot_vars,
)
from audio_suite_shared.ui_audition import AuditionMixin
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
        folder_path: str = self.folder_path.get()
        if folder_path and os.path.exists(folder_path):
            platform_utils.open_path(folder_path)
        else:
            messagebox.showinfo("Folder", "Source folder not available.")

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
        data: str | None = cast(
            str | None,
            suite_config.load_value(f"{self.PRESET_KEY_PREFIX}_preset_{name}", None),
        )
        if data is not None:
            try:
                settings: dict[str, int | bool | str] = json.loads(data)
                self._apply_preset(settings)
            except (json.JSONDecodeError, TypeError, ValueError) as exc:
                logger.error("Failed to load preset '%s': %s", name, exc)

    def _save_current_as_preset(self, name: str) -> None:
        """Save the current settings as a named preset."""
        settings: dict[str, int | bool | str] = self._collect_settings()
        suite_config.save_value(
            f"{self.PRESET_KEY_PREFIX}_preset_{name}", json.dumps(settings)
        )
        names_json: str | None = cast(
            str | None,
            suite_config.load_value(f"{self.PRESET_KEY_PREFIX}_presets_list", None),
        )
        names: list[str] = json.loads(names_json) if names_json else []
        if name not in names:
            names.append(name)
        suite_config.save_value(
            f"{self.PRESET_KEY_PREFIX}_presets_list", json.dumps(names)
        )
        if self._refresh_preset_list is not None:
            self._refresh_preset_list()

    def _delete_preset(self, name: str) -> None:
        """Delete a named preset."""
        names_json: str | None = cast(
            str | None,
            suite_config.load_value(f"{self.PRESET_KEY_PREFIX}_presets_list", None),
        )
        names: list[str] = json.loads(names_json) if names_json else []
        if name in names:
            names.remove(name)
        suite_config.save_value(
            f"{self.PRESET_KEY_PREFIX}_presets_list", json.dumps(names)
        )
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
        self.progress["maximum"] = total
        self.progress["value"] = processed
        self.stats_label.config(
            text=f"Processed: {processed} | Skipped: {skipped} | Errors: {errors}"
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

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

        summary: list[str] = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"{self.TAGGED_LABEL}: {tagged}\n",
            f"Skipped: {skipped}\n",
            f"Errors: {errors}\n",
        ]
        summary.extend(f"{label}: {value}\n" for label, value in extras)
        summary.append(f"Time: {minutes:02d}:{seconds:02d}\n")
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


class NoisePopToolApp(UIHelperMixin, AuditionMixin):
    """Shared scaffold for the Noise Reduction and Pop & Click Remover tools.

    The progress/complete signatures (``succeeded`` count, undo-batch engine
    call) differ from the tagging family's ``AnalysisTagToolApp``, so this
    class inherits from ``UIHelperMixin`` directly rather than extending that
    scaffold.

    Subclass contract (class attributes):
        ``TOOL_ID``, ``TOOL_TITLE``, ``HELP_GUIDE``, ``RESULTS_LABEL``,
        ``COMPLETION_LABEL``.

    Subclass contract (instance attributes created in ``__init_subclass__``
        or before ``_build_ui`` runs): tool-specific Tk variables — e.g.
        ``self.sensitivity``, ``self.reduce_hum``, ``self.max_width`` — and
        the four driver-mirror Booleans (``auto_start_var``,
        ``auto_end_var``, ``clear_logs_var``, ``parallel_var``).

    Subclass hooks:
        ``_create_tool_variables(root)``
        ``_build_setup_controls(tab_setup)``
        ``_validate_start()``
        ``_run_engine_in_batch()``
        ``_apply_tool_cli_options(parsed)``
        ``_tool_cli_parse()``
    """

    # ── Class attributes (subclass overrides) ─────────────────────────────
    TOOL_ID: str = ""
    TOOL_TITLE: str = ""
    HELP_GUIDE: str = ""
    RESULTS_LABEL: str = "Processed"
    COMPLETION_LABEL: str = "Processing Complete!"

    # ── Instance attributes the subclasses create (mypy shape surface) ────
    root: tk.Tk
    run_mode: tk.StringVar
    folder_path: tk.StringVar
    auto_start_var: tk.BooleanVar
    auto_end_var: tk.BooleanVar
    clear_logs_var: tk.BooleanVar
    parallel_var: tk.BooleanVar
    _launched_from_driver: bool
    _log_path: str
    _run_was_dry_run: bool
    _preset_combo: ttk.Combobox | None
    _refresh_preset_list: "Callable[..., None] | None"
    progress: ttk.Progressbar
    stats_label: tk.Label
    file_listbox: tk.Listbox
    time_label: tk.Label
    summary_label: tk.Label
    completion_label: tk.Label
    start_btn: tk.Button
    notebook: ttk.Notebook
    _tab_results: tk.Frame
    _tab_processing: tk.Frame
    overall_status: tk.StringVar
    slot_queue: "Queue[Any]"
    _safe_slot_vars: "list[ThreadSafeSlotVar]"

    # ── Constructor ───────────────────────────────────────────────────────

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            self.TOOL_TITLE,
            f"{self.TOOL_ID}_window",
            self.TOOL_ID,
        )

        # ── Tk variables ─────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.run_mode = tk.StringVar(value="Dry Run")

        self._create_tool_variables()

        # Driver-mirrored
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self._launched_from_driver = self._tool_cli_was_launched_from_driver()

        # ── State ─────────────────────────────────────────────────────────
        self._log_path = ""
        self._run_was_dry_run = False
        self._preset_combo = None
        self._refresh_preset_list = None

        # ── Worker slot pool ──────────────────────────────────────────────
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        self._build_ui()
        self._apply_cli_args()

        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── Subclass hooks ────────────────────────────────────────────────────

    def _create_tool_variables(self) -> None:
        """Hook: create tool-specific Tk variables onto ``self``.

        Called after ``folder_path`` and ``run_mode`` are set, before the
        driver-mirrored variables.  Example::

            self.sensitivity = tk.DoubleVar(value=0.31)
            self.max_width = tk.IntVar(value=2)
        """

    def _build_setup_controls(self, tab_setup: tk.Frame) -> dict[str, Any]:
        """Hook: build tool-specific controls into the Setup tab.

        Args:
            tab_setup: The ``tk.Frame`` for the Setup tab.

        Returns:
            Widgets dict from ``setup_tab.build``.  Must include
            ``start_btn``, ``refresh_preset_list``, and ``preset_combo``.
        """
        raise NotImplementedError

    def _build_setup_shared_kwargs(self) -> dict[str, Any]:
        """Return the kwargs every tool passes to ``setup_tab.build``."""
        return {
            "folder_path": self.folder_path,
            "run_mode": self.run_mode,
            "on_browse": self._on_browse,
            "on_start": self._on_start,
            "preset_names": suite_config.list_presets(self.TOOL_ID),
            "on_save_preset": self._save_current_as_preset,
            "on_delete_preset": self._delete_preset,
            "on_preset_selected": self._on_preset_selected,
            "auto_start_var": self.auto_start_var,
            "auto_end_var": self.auto_end_var,
            "clear_logs_var": self.clear_logs_var,
            "parallel_var": self.parallel_var,
            "driver_locked": self._launched_from_driver,
        }

    def _build_processing_controls(self, tab_processing: tk.Frame) -> dict[str, Any]:
        """Hook: build the Processing tab widgets.

        Must return a dict with ``overall_status``, ``progress``,
        ``stats_label``, ``file_listbox``.
        """
        raise NotImplementedError

    def _build_results_controls(self, tab_results: tk.Frame) -> dict[str, Any]:
        """Hook: build the Results tab widgets.

        Must return a dict with ``completion_label``, ``summary_label``,
        ``time_label``, plus ``original_path`` and ``result_path`` keys
        consumed by ``setup_audition``.
        """
        raise NotImplementedError

    def _validate_start(self) -> str | None:
        """Hook: validate before starting.

        Returns:
            ``None`` if all checks pass, or an error message string to
            display in a warning dialog.
        """
        return None

    def _run_engine_in_batch(self, folder: str, is_dry_run: bool) -> None:
        """Hook: run the tool-specific engine inside an undo batch.

        Called on the background thread with ``active_batch`` already
        established.  Must invoke ``run_*`` with the tool's parameters
        and the shared progress/complete/fail callbacks.

        Example::

            with active_batch(self.TOOL_ID, \"tag_edit\"):
                run_noise_reduction(
                    folder, params, self._safe_slot_vars,
                    self.slot_queue, self._on_progress,
                    self._complete, self._fail,
                )
        """
        raise NotImplementedError

    def _apply_tool_cli_options(self, parsed: Any) -> None:
        """Hook: mirror tool-specific driver flags onto the Run Controls.

        Called after the shared CLI handler has applied the folder path
        and the shared mirror flags (``clear_logs_var``, ``parallel_var``).
        """

    def _tool_cli_parse(self) -> Any:
        """Hook: return the parsed per-tool CLI arguments.

        Returns:
            The ``argparse.Namespace`` from the tool's ``cli_args.parse()``.
        """
        raise NotImplementedError

    def _tool_cli_was_launched_from_driver(self) -> bool:
        """Hook: return whether the tool was launched by the Master Driver.

        Default reads ``was_launched_from_driver()`` from the tool's
        ``cli_args`` module.  Override if the tool has a different source.
        """
        from audio_suite_shared.cli_helpers import was_launched_from_driver

        return was_launched_from_driver()

    # ── UI ────────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        """Build the shared UI skeleton; subclasses add Setup controls."""
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

        # ── Setup tab (subclass builds tool-specific controls) ────────────
        setup_widgets = self._build_setup_controls(tab_setup)
        self.start_btn = cast(tk.Button, setup_widgets["start_btn"])
        self._refresh_preset_list = setup_widgets["refresh_preset_list"]
        self._preset_combo = cast(ttk.Combobox, setup_widgets["preset_combo"])

        # ── Processing tab ────────────────────────────────────────────────
        proc_widgets = self._build_processing_controls(tab_processing)
        self.overall_status = cast(tk.StringVar, proc_widgets["overall_status"])
        self.progress = cast(ttk.Progressbar, proc_widgets["progress"])
        self.stats_label = cast(tk.Label, proc_widgets["stats_label"])
        self.file_listbox = cast(tk.Listbox, proc_widgets["file_listbox"])

        # ── Results tab ───────────────────────────────────────────────────
        res_widgets = self._build_results_controls(tab_results)
        self.completion_label = cast(tk.Label, res_widgets["completion_label"])
        self.summary_label = cast(tk.Label, res_widgets["summary_label"])
        self.time_label = cast(tk.Label, res_widgets["time_label"])
        self.setup_audition(res_widgets)

        self._tab_setup = tab_setup
        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # ── Presets ───────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        """Hook: read the current settings into a serialisable dict.

        Used by ``_save_current_as_preset``.
        """
        raise NotImplementedError

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        """Hook: apply a preset dict onto the tool's Tk variables."""
        raise NotImplementedError

    def _on_preset_selected(self, name: str) -> None:
        """Load a named preset and apply its settings."""
        settings = suite_config.load_preset(self.TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        """Save the current settings as a named preset."""
        suite_config.save_preset(self.TOOL_ID, name, self._collect_settings())
        if self._refresh_preset_list is not None:
            self._refresh_preset_list(suite_config.list_presets(self.TOOL_ID))

    def _delete_preset(self, name: str) -> None:
        """Delete a named preset."""
        suite_config.delete_preset(self.TOOL_ID, name)
        if self._refresh_preset_list is not None:
            self._refresh_preset_list(suite_config.list_presets(self.TOOL_ID))

    # ── CLI handling ──────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        """Apply parsed CLI arguments onto the Run Controls panel.

        Mirrors the shared driver flags (``clear_logs``, ``parallel_run``),
        calls ``_apply_tool_cli_options`` for tool-specific flags, and
        schedules auto-start when the CLI handler requests it.
        """
        parsed = self._tool_cli_parse()
        if not parsed.folder_path:
            return

        cli_handler = UniversalCLIHandler(self)
        cli_handler.apply_cli_args(
            parsed,
            folder_var=self.folder_path,
        )

        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        self._apply_tool_cli_options(parsed)

        if parsed.auto_start:
            self.root.after(500, self._on_start)

    # ── User actions ──────────────────────────────────────────────────────

    def _on_browse(self) -> None:
        """Browse for a music directory."""
        self._browse_folder_standard(
            title="Select Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )

    def _on_start(self) -> None:
        """Validate inputs and launch the engine on a background thread."""
        folder = self.folder_path.get().strip()
        if not folder:
            messagebox.showwarning(
                self.TOOL_TITLE, "Please select a music folder first."
            )
            return
        if not os.path.isdir(folder):
            messagebox.showerror(self.TOOL_TITLE, "The selected folder does not exist.")
            return

        validation_error = self._validate_start()
        if validation_error:
            messagebox.showwarning(self.TOOL_TITLE, validation_error)
            return

        suite_config.save_last_directory(folder)

        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        self.overall_status.set("Running...")
        self.stats_label.config(
            text=f"Processed: 0 | {self.RESULTS_LABEL}: 0 | Skipped: 0 | Errors: 0"
        )

        self.start_btn.config(state="disabled")
        self.notebook.select(self._tab_processing)

        is_dry_run = self.run_mode.get() == "Dry Run"
        self._run_was_dry_run = is_dry_run
        self.prepare_in_place_audition(folder, SUPPORTED_EXTENSIONS)

        self._worker = threading.Thread(
            target=self._run_with_undo,
            args=(folder, is_dry_run),
            daemon=True,
        )
        self._worker.start()

    def _run_with_undo(self, folder: str, is_dry_run: bool) -> None:
        """Run the engine inside an undo batch on the background thread."""
        self._run_engine_in_batch(folder, is_dry_run)

    # ── Progress plumbing ─────────────────────────────────────────────────

    def _on_progress(
        self,
        processed: int,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        display_text: str,
        **_extra: Any,
    ) -> None:
        """Schedule a progress-bar update onto the main thread.

        ``**_extra`` absorbs any field a processor publishes that this render
        does not read, so a tool that adds one cannot turn a finished run into a
        ``TypeError`` inside the callback (AGENTS: GUI Callback Contract).
        """
        self.root.after(
            0,
            self._update_progress_ui,
            processed,
            total,
            succeeded,
            skipped,
            errors,
            display_text,
        )

    def _update_progress_ui(
        self,
        processed: int,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        """Update progress bar and file list (must be called on main thread)."""
        self.progress["maximum"] = total
        self.progress["value"] = processed
        self.stats_label.config(
            text=(
                f"Processed: {processed} | {self.RESULTS_LABEL}: {succeeded}"
                f" | Skipped: {skipped} | Errors: {errors}"
            )
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

    def _on_complete(
        self,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        **_extra: Any,
    ) -> None:
        """Update UI after all files finish (called on the background thread).

        ``**_extra`` absorbs a field a processor adds that this render does not
        read; the six declared fields stay required, so a payload that drops one
        still raises with its name rather than rendering a plausible zero.
        """
        self.progress["value"] = 100
        self.overall_status.set("Complete.")

        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        self.summary_label.config(
            text=(
                f"Total: {total} files\n"
                f"{self.RESULTS_LABEL}: {succeeded}\n"
                f"Skipped: {skipped}\n"
                f"Errors: {errors}"
            )
        )
        self.completion_label.config(text=self.COMPLETION_LABEL)
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

        self._update_audition_on_complete()
        self._update_auto_end()

    def _update_audition_on_complete(self) -> None:
        """Update the audition state after processing completes."""
        if self._run_was_dry_run:
            self.set_audition_state(
                self._audition_original,
                None,
                "Dry Run — nothing written. Play Result is unavailable.",
            )
        elif self._audition_original is not None and self._audition_result is not None:
            name = self._audition_result.name
            self.set_audition_state(
                self._audition_original,
                self._audition_result,
                f"Audition ready — {name} (original vs result)",
            )
        else:
            self.set_audition_state(
                None, None, "No supported audio file found for audition."
            )

    def _update_auto_end(self) -> None:
        """Schedule window destruction when auto-end is enabled."""
        if self.auto_end_var.get():
            self.root.after(2000, self.root.destroy)

    def _on_error(self, message: str) -> None:
        """Show a fatal error dialog and re-enable the start button."""
        messagebox.showerror(self.TOOL_TITLE, message)
        self.start_btn.config(state="normal")

    # ── Help / Log / Folder ───────────────────────────────────────────────

    def _open_help(self) -> None:
        """Open the tool user guide."""
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        """Open the most recent log file."""
        self._open_log_standard()

    def _open_folder(self) -> None:
        """Open the source folder in the system file manager."""
        self._open_folder_standard()
