"""
app.py
AudioRefineryApp — main window orchestrator.

Three-tab suite interface: Setup → Processing → Results.
Follows the identical conventions used by every other tool in the suite.

Changed in 1.1.0: collect/apply settings now carry the six Sprint 1
effect fields.

Changed in 1.4.1: ``_on_complete`` and ``_on_progress`` accept ``**_extra: Any``,
so a payload field the processor adds (D112) is ignored instead of aborting an
otherwise-finished run; ``tests/test_callback_payload_contract.py`` locks the
completion, progress and error seams.
"""

from __future__ import annotations

import logging
import os
import threading
import tkinter as tk
from pathlib import Path
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, cast

from audio_suite_shared import audio_playback, styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.ui_audition import AuditionMixin
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core.file_processor import run_pipeline
from .core.registry import CompletionRegistry
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args
from .utils.cli_args import parse as parse_cli
from .utils.settings import load as load_settings
from .utils.settings import save as save_settings

logger = logging.getLogger(__name__)

_TOOL_ID = "audio_refinery"


class _ThreadSafeSlotVar:
    """Wrap a tk.StringVar so that .set() is always scheduled on the main thread."""

    def __init__(self, root: tk.Tk, var: tk.StringVar) -> None:
        self._root = root
        self._var = var

    def set(self, value: str) -> None:
        self._root.after(0, self._var.set, value)

    def get(self) -> str:
        return self._var.get()


class AudioRefineryApp(UIHelperMixin, AuditionMixin):
    """Main application window for Audio Refinery."""

    HELP_GUIDE = "Audio_Refinery_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.update_idletasks()
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Audio Refinery",
            "audio_refinery_window",
            "audio_refinery",
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.source_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.run_mode: tk.StringVar = tk.StringVar(value="Dry Run")

        # Driver-mirrored run controls (Clear Logs / Parallel are display-only)
        self.auto_start_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.auto_end_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.clear_logs_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self.parallel_var: tk.BooleanVar = tk.BooleanVar(value=False)
        self._launched_from_driver: bool = cli_args.was_launched_from_driver()

        # Stage configuration — restored from last session, or defaults on first run
        self.config = load_settings()

        # Completion registry (loaded/swapped when source directory changes)
        self._registry: CompletionRegistry | None = None
        self._last_source_dir: str = ""

        # ── State set on main thread before processing ────────────────────────
        self._log_path: str = ""
        self._out_dir: str = ""
        self._in_place: bool = False
        self._run_was_dry_run: bool = False
        # overall_status is set after processing_tab.build() returns its dict

        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Worker slot pool ──────────────────────────────────────────────────
        self.slot_vars = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = [
            _ThreadSafeSlotVar(self.root, v) for v in self.slot_vars
        ]
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        # ── Build UI ──────────────────────────────────────────────────────────
        self._build_ui()

        # ── CLI args ──────────────────────────────────────────────────────────
        self._apply_cli_args()

        # ── Restore last directory ────────────────────────────────────────────
        if not self.source_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.source_path.set(last)
                self._load_registry(last)

        # Watch for source path changes to swap registry
        self.source_path.trace_add("write", self._on_source_changed)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        # Menu bar / help button row
        top = tk.Frame(self.root, bg=styles.BG_APP, pady=4)
        top.pack(fill="x", padx=12)
        tk.Button(
            top,
            text="? Help",
            bg=styles.BG_LIGHT,
            fg=styles.FG_SUB,
            font=styles.FONT_CAPTION,
            relief=tk.FLAT,
            command=self._open_help,
        ).pack(side=tk.RIGHT)

        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=8, pady=(0, 8))

        # ── Tab 1: Setup ──────────────────────────────────────────────────────
        tab_setup = tk.Frame(self.notebook, bg=styles.BG_WHITE)
        self.notebook.add(tab_setup, text="  1. Setup  ")

        setup_widgets = setup_tab.build(
            parent=tab_setup,
            source_path=self.source_path,
            output_path=self.output_path,
            config=self.config,
            on_browse_src=self._browse_source,
            on_browse_out=self._browse_output,
            on_start=self.start_processing,
            on_reset=self._reset_registry,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            driver_locked=self._launched_from_driver,
            preset_names=suite_config.list_presets(_TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
            mode_var=self.run_mode,
        )
        self.start_btn = cast(tk.Button, setup_widgets["start_btn"])
        self.reset_btn = cast(tk.Button, setup_widgets["reset_btn"])
        self._setup_state = setup_widgets
        self._refresh_preset_list = self._setup_state.get("refresh_preset_list")

        # ── Tab 2: Processing ─────────────────────────────────────────────────
        tab_proc = tk.Frame(self.notebook, bg=styles.BG_WHITE)
        self.notebook.add(tab_proc, text="  2. Processing  ")

        proc_widgets = processing_tab.build(
            parent=tab_proc,
            slot_vars=self.slot_vars,
        )
        self.overall_status = proc_widgets["overall_status"]
        self._progress_bar = proc_widgets["progress"]
        self._stats_label = proc_widgets["stats_label"]
        self._file_listbox = proc_widgets["file_listbox"]

        # ── Tab 3: Results ────────────────────────────────────────────────────
        tab_results = tk.Frame(self.notebook, bg=styles.BG_WHITE)
        self.notebook.add(tab_results, text="  3. Results  ")
        self._tab_results = tab_results

        results_widgets = results_tab.build(
            parent=tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
            on_play_original=self._play_original,
            on_play_result=self._play_result,
        )
        self._completion_label = results_widgets["completion_label"]
        self._time_label = results_widgets["time_label"]
        self._summary_label = results_widgets["summary_label"]
        self.setup_audition(results_widgets)

        self._tab_processing = tab_proc

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _browse_source(self) -> None:
        """Browse for source folder with enhanced error handling."""
        self._browse_folder_standard(
            title="Select Source Folder",
            path_variable=self.source_path,
            save_last_dir=False,
        )

    def _browse_output(self) -> None:
        """Browse for output folder with enhanced error handling."""
        self._browse_folder_standard(
            title="Select Output Folder",
            path_variable=self.output_path,
            save_last_dir=False,
        )

    def _open_help(self) -> None:
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        self._open_log_standard()

    def _open_folder(self) -> None:
        self._open_folder_standard()

    def _on_source_changed(self, *_: Any) -> None:
        src = self.source_path.get().strip()
        if src and src != self._last_source_dir:
            self._load_registry(src)

    def _load_registry(self, source: str) -> None:
        path = Path(source)
        if path.is_dir():
            self._registry = CompletionRegistry(path)
            self._last_source_dir = source
            count = self._registry.completed_count
            if count > 0 and hasattr(self, "overall_status"):
                self.overall_status.set(
                    f"Registry loaded — {count} file(s) already completed"
                )

    def _reset_registry(self) -> None:
        if self._registry is None:
            messagebox.showinfo("Reset Progress", "No source folder selected.")
            return
        confirmed = messagebox.askyesno(
            "Reset Progress",
            f"This will clear the completion record for:\n\n"
            f"{self._last_source_dir}\n\n"
            f"All files will be reprocessed on the next run.\n\n"
            f"Continue?",
            icon="warning",
        )
        if confirmed:
            self._registry.reset()
            self.overall_status.set("Progress reset — all files will be reprocessed")

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        p = self.config
        return {
            "declick": p.declick,
            "trim": p.trim,
            "enhance": p.enhance,
            "normalise": p.normalise,
            "sensitivity": p.declick_params.sensitivity,
            "max_width_ms": p.declick_params.max_width_ms,
            "threshold": p.trim_params.threshold,
            "apply_fade": p.trim_params.apply_fade,
            "fade_in_ms": p.trim_params.fade_in_ms,
            "fade_out_ms": p.trim_params.fade_out_ms,
            "preset": p.enhance_params.preset,
            "noise_gate_threshold_db": p.enhance_params.noise_gate_threshold_db,
            "compressor_threshold_db": p.enhance_params.compressor_threshold_db,
            "compressor_ratio": p.enhance_params.compressor_ratio,
            "compressor_attack_ms": p.enhance_params.compressor_attack_ms,
            "compressor_release_ms": p.enhance_params.compressor_release_ms,
            "low_shelf_gain_db": p.enhance_params.low_shelf_gain_db,
            "low_shelf_freq_hz": p.enhance_params.low_shelf_freq_hz,
            "presence_gain_db": p.enhance_params.presence_gain_db,
            "presence_freq_hz": p.enhance_params.presence_freq_hz,
            "high_shelf_gain_db": p.enhance_params.high_shelf_gain_db,
            "high_shelf_freq_hz": p.enhance_params.high_shelf_freq_hz,
            "output_gain_db": p.enhance_params.output_gain_db,
            "limiter_threshold_db": p.enhance_params.limiter_threshold_db,
            "reverse": p.enhance_params.reverse,
            "karaoke": p.enhance_params.karaoke,
            "karaoke_strength": p.enhance_params.karaoke_strength,
            "phaser": p.enhance_params.phaser,
            "flanger": p.enhance_params.flanger,
            "chorus": p.enhance_params.chorus,
            "target_lufs": p.normalise_params.target_lufs,
            "tolerance": p.normalise_params.tolerance,
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        p = self.config
        if "declick" in settings:
            p.declick = settings["declick"]
        if "trim" in settings:
            p.trim = settings["trim"]
        if "enhance" in settings:
            p.enhance = settings["enhance"]
        if "normalise" in settings:
            p.normalise = settings["normalise"]
        if "sensitivity" in settings:
            p.declick_params.sensitivity = settings["sensitivity"]
        if "max_width_ms" in settings:
            p.declick_params.max_width_ms = settings["max_width_ms"]
        if "threshold" in settings:
            p.trim_params.threshold = settings["threshold"]
        if "apply_fade" in settings:
            p.trim_params.apply_fade = settings["apply_fade"]
        if "fade_in_ms" in settings:
            p.trim_params.fade_in_ms = settings["fade_in_ms"]
        if "fade_out_ms" in settings:
            p.trim_params.fade_out_ms = settings["fade_out_ms"]
        if "preset" in settings:
            p.enhance_params.preset = settings["preset"]
        if "noise_gate_threshold_db" in settings:
            p.enhance_params.noise_gate_threshold_db = settings[
                "noise_gate_threshold_db"
            ]
        if "compressor_threshold_db" in settings:
            p.enhance_params.compressor_threshold_db = settings[
                "compressor_threshold_db"
            ]
        if "compressor_ratio" in settings:
            p.enhance_params.compressor_ratio = settings["compressor_ratio"]
        if "compressor_attack_ms" in settings:
            p.enhance_params.compressor_attack_ms = settings["compressor_attack_ms"]
        if "compressor_release_ms" in settings:
            p.enhance_params.compressor_release_ms = settings["compressor_release_ms"]
        if "low_shelf_gain_db" in settings:
            p.enhance_params.low_shelf_gain_db = settings["low_shelf_gain_db"]
        if "low_shelf_freq_hz" in settings:
            p.enhance_params.low_shelf_freq_hz = settings["low_shelf_freq_hz"]
        if "presence_gain_db" in settings:
            p.enhance_params.presence_gain_db = settings["presence_gain_db"]
        if "presence_freq_hz" in settings:
            p.enhance_params.presence_freq_hz = settings["presence_freq_hz"]
        if "high_shelf_gain_db" in settings:
            p.enhance_params.high_shelf_gain_db = settings["high_shelf_gain_db"]
        if "high_shelf_freq_hz" in settings:
            p.enhance_params.high_shelf_freq_hz = settings["high_shelf_freq_hz"]
        if "output_gain_db" in settings:
            p.enhance_params.output_gain_db = settings["output_gain_db"]
        if "limiter_threshold_db" in settings:
            p.enhance_params.limiter_threshold_db = settings["limiter_threshold_db"]
        if "reverse" in settings:
            p.enhance_params.reverse = settings["reverse"]
        if "karaoke" in settings:
            p.enhance_params.karaoke = settings["karaoke"]
        if "karaoke_strength" in settings:
            p.enhance_params.karaoke_strength = settings["karaoke_strength"]
        if "phaser" in settings:
            p.enhance_params.phaser = settings["phaser"]
        if "flanger" in settings:
            p.enhance_params.flanger = settings["flanger"]
        if "chorus" in settings:
            p.enhance_params.chorus = settings["chorus"]
        if "target_lufs" in settings:
            p.normalise_params.target_lufs = settings["target_lufs"]
        if "tolerance" in settings:
            p.normalise_params.tolerance = settings["tolerance"]

        # Keep the enhancer stage's Custom DSP editor in step with the loaded
        # preset. The editor's values are the source for every later edit, so a
        # stale copy would rewrite this preset's values back into the config on
        # the next slider move; before the editor existed the same load left the
        # inline sliders showing the previous values.
        setup_state = getattr(self, "_setup_state", None) or {}
        preset_var = setup_state.get("preset_var")
        panel = setup_state.get("dsp_panel")
        if preset_var is not None and preset_var.get() != p.enhance_params.preset:
            # Setting the selector runs the panel's preset trace; apply_values
            # below then restores the values this preset actually stored.
            preset_var.set(p.enhance_params.preset)
        if panel is not None:
            panel.apply_values(
                {
                    name: getattr(p.enhance_params, name)
                    for name in p.enhance_params.__dataclass_fields__
                }
            )

    def _on_preset_selected(self, name: str) -> None:
        settings = suite_config.load_preset(_TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        suite_config.save_preset(_TOOL_ID, name, self._collect_settings())
        if self._refresh_preset_list:
            self._refresh_preset_list(suite_config.list_presets(_TOOL_ID))

    def _delete_preset(self, name: str) -> None:
        suite_config.delete_preset(_TOOL_ID, name)
        if self._refresh_preset_list:
            self._refresh_preset_list(suite_config.list_presets(_TOOL_ID))

    # ── Processing launch ─────────────────────────────────────────────────────

    def start_processing(self) -> None:
        """Start processing with enhanced validation and error handling."""
        try:
            src = self.source_path.get().strip()

            # Enhanced validation with specific error types
            if not src:
                messagebox.showerror(
                    "No Source Folder",
                    "Please select a source folder containing audio files.",
                )
                return

            source_dir = Path(src)
            if not source_dir.exists():
                messagebox.showerror(
                    "Source Not Found", f"The source directory does not exist:\n{src}"
                )
                return

            if not source_dir.is_dir():
                messagebox.showerror(
                    "Invalid Source",
                    f"The source path is not a valid directory:\n{src}",
                )
                return

            # Check for audio files in source
            try:
                has_audio = any(
                    f.lower().endswith(ext)
                    for f in os.listdir(src)
                    for ext in [".mp3", ".flac", ".ogg", ".m4a", ".opus", ".wav"]
                )

                if not has_audio:
                    messagebox.showerror(
                        "No Audio Files",
                        f"No supported audio files found in:\n{src}\n\n"
                        "Supported formats: MP3, FLAC, OGG, M4A, Opus, WAV",
                    )
                    return
            except PermissionError as exc:
                messagebox.showerror(
                    "Access Denied",
                    f"Cannot access source directory:\n{src}\n\n{str(exc)}",
                )
                return

            # Validate pipeline stages
            if not any(
                [
                    self.config.declick,
                    self.config.trim,
                    self.config.enhance,
                    self.config.normalise,
                    self.config.reduce_noise,
                ]
            ):
                messagebox.showerror(
                    "No Stages Selected", "Please enable at least one refinery stage."
                )
                return

            # Resolve output directory
            out_raw = self.output_path.get().strip()
            if out_raw:
                output_dir = Path(out_raw)

                # Validate output directory
                if not output_dir.exists():
                    messagebox.showerror(
                        "Output Not Found",
                        f"The output directory does not exist:\n{out_raw}",
                    )
                    return

                if not output_dir.is_dir():
                    messagebox.showerror(
                        "Invalid Output",
                        f"The output path is not a valid directory:\n{out_raw}",
                    )
                    return
            else:
                output_dir = source_dir

            # Ensure registry is loaded for this source
            if self._registry is None or self._last_source_dir != src:
                self._load_registry(src)

            self._out_dir = str(output_dir)
            self._log_path = str(output_dir / "refinery_log.txt")

            # In-place runs overwrite the source files, so snapshot the first
            # one now to give the A/B buttons a "before" file to play later.
            # When writing to a separate output folder the result path is that
            # folder, so point Play Result there explicitly.
            self._in_place = output_dir.resolve() == source_dir.resolve()
            self._run_was_dry_run = self.run_mode.get() == "Dry Run"
            if self._in_place:
                self.prepare_in_place_audition(source_dir, SUPPORTED_EXTENSIONS)
            else:
                original = audio_playback.peek_first_audio(
                    source_dir, SUPPORTED_EXTENSIONS
                )
                if original is None:
                    self.clear_audition()
                else:
                    self.prepare_in_place_audition(
                        source_dir,
                        SUPPORTED_EXTENSIONS,
                        result_path=output_dir / original.name,
                    )

            suite_config.save_last_directory(str(source_dir))

            # Persist current settings so next launch restores them
            save_settings(self.config)

            self.start_btn.config(state="disabled")
            self._file_listbox.delete(0, tk.END)
            self._progress_bar["value"] = 0
            self.notebook.select(self._tab_processing)
            self.overall_status.set("Pipeline running…")

            threading.Thread(
                target=self._run,
                args=(source_dir, output_dir),
                daemon=True,
            ).start()

        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Processing Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Processing Error",
                f"Failed to start processing:\n{user_message_for(mapped)}",
            )

    @handle_audio_errors(reraise=False, context="audio_refinery_app_run")
    def _run(self, source_dir: Path, output_dir: Path) -> None:
        # _on_start loaded the registry for this source before spawning the
        # thread; narrow the Optional for run_pipeline's benefit.
        registry = self._registry
        assert registry is not None
        with active_batch("audio_refinery", "tag_edit"):
            run_pipeline(
                source_dir=source_dir,
                output_dir=output_dir,
                config=self.config,
                registry=registry,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=self._on_complete,
                on_error=self._on_error,
            )

    def _on_progress(
        self,
        processed: int,
        total: int,
        succeeded: int,
        skipped: int,
        errors: int,
        display_text: str,
        log_text: str,
        **_extra: Any,
    ) -> None:
        def _update() -> None:
            pct = (processed / total * 100) if total else 0
            self._progress_bar["value"] = pct
            self.overall_status.set(
                f"Processing… {processed}/{total}  ✓{succeeded}  ⊘{skipped}  ✗{errors}"
            )
            self._file_listbox.insert(tk.END, display_text)
            self._file_listbox.see(tk.END)

        self.root.after(0, _update)

    def _on_complete(
        self,
        total: int,
        processed: int,
        succeeded: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        **_extra: Any,
    ) -> None:
        logger.info(
            f"_on_complete called: total={total}, processed={processed}, "
            f"succeeded={succeeded}, skipped={skipped}, errors={errors}"
        )
        try:
            Path(self._log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "w", encoding="utf-8") as fh:
                fh.write("Audio Refinery — Processing Log\n")
                fh.write("=" * 50 + "\n")
                fh.writelines(log_entries)
                fh.write("=" * 50 + "\n")
                fh.write(
                    f"Total: {total}  Processed: {processed}  "
                    f"Succeeded: {succeeded}  Skipped: {skipped}  Errors: {errors}  "
                    f"Time: {duration_secs:.1f}s\n"
                )
        except PermissionError as exc:
            messagebox.showerror(
                "Permission Denied",
                f"Cannot write log file:\n{self._log_path}\n\n"
                f"Please check file permissions and try again.\n\n{str(exc)}",
            )
        except OSError as exc:
            messagebox.showerror(
                "Log Write Error",
                f"Failed to write log file:\n{self._log_path}\n\n{str(exc)}",
            )
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Unexpected Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Unexpected Error",
                f"An error occurred while saving log:\n{user_message_for(mapped)}",
            )

        def _update() -> None:
            mins, secs = divmod(int(duration_secs), 60)
            time_str = f"{mins}m {secs}s" if mins else f"{secs}s"

            self._completion_label.config(
                text=f"Refinery Complete — {succeeded} file(s) processed"
            )
            self._time_label.config(text=f"Total time: {time_str}")
            self.notebook.select(self._tab_results)
            self.start_btn.config(state="normal")
            self.overall_status.set("Complete")

            if self._run_was_dry_run:
                # Nothing was written — the captured original is what exists on
                # disk, so only Play Original is meaningful.
                self.set_audition_state(
                    self._audition_original,
                    None,
                    "Dry Run — nothing written. Play Result is unavailable.",
                )
            elif (
                self._audition_original is not None
                and self._audition_result is not None
            ):
                name = Path(self._audition_result).name
                self.set_audition_state(
                    self._audition_original,
                    self._audition_result,
                    f"Audition ready — {name} (original vs result)",
                )
            else:
                self.set_audition_state(
                    None, None, "No supported audio file found for audition."
                )

            if self.auto_end_var.get():
                self.root.after(1500, self.root.destroy)

        self.root.after(0, _update)

    def _on_error(self, message: str) -> None:
        def _update() -> None:
            messagebox.showerror("Pipeline Error", message)
            self.start_btn.config(state="normal")
            self.overall_status.set("Error")

        self.root.after(0, _update)

    # ── CLI integration ───────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        args = parse_cli()

        # Mirror the driver's run controls onto the Setup tab panel.
        self.auto_start_var.set(args.auto_start)
        self.auto_end_var.set(args.auto_end)
        self.clear_logs_var.set(args.clear_logs)
        self.parallel_var.set(args.parallel_run)

        # Universal CLI handling
        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            args,
            source_var=self.source_path,
            output_var=self.output_path,
            auto_start_func=self.start_processing,
        )

        if args.dry_run is not None:
            self.run_mode.set("Dry Run" if args.dry_run else "Live Update")

        # Load registry if source was set
        if args.source:
            self._load_registry(args.source)

        # Stage toggles from --stages
        active = {s.strip().lower() for s in args.stages.split(",")}
        self.config.declick = "declick" in active
        self.config.trim = "trim" in active
        self.config.enhance = "enhance" in active
        self.config.normalise = "normalise" in active
        self.config.reduce_noise = "reduce_noise" in active

        # Per-stage params from CLI
        self.config.declick_params.sensitivity = args.sensitivity
        self.config.declick_params.max_width_ms = args.width
        self.config.trim_params.threshold = args.threshold
        self.config.trim_params.apply_fade = args.fade
        self.config.trim_params.fade_in_ms = args.fade_in
        self.config.trim_params.fade_out_ms = args.fade_out
        self.config.noise_reduction_params.reduce_hum = args.reduce_hum
        self.config.noise_reduction_params.hum_frequency = args.hum_frequency
        self.config.noise_reduction_params.hum_harmonics = args.hum_harmonics
        self.config.noise_reduction_params.hum_quality = args.hum_quality
        self.config.noise_reduction_params.reduce_broadband = args.reduce_broadband
        self.config.noise_reduction_params.noise_start_ms = args.noise_start_ms
        self.config.noise_reduction_params.noise_end_ms = args.noise_end_ms
        self.config.noise_reduction_params.gate_threshold_db = args.gate_threshold_db
        self.config.enhance_params.preset = args.preset
        self.config.normalise_params.target_lufs = args.target_lufs
        self.config.normalise_params.tolerance = args.tolerance

        if should_auto_start:
            self.root.after(1500, self.start_processing)


def main() -> None:
    root = tk.Tk()
    AudioRefineryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
