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

Changed in 2.3.1: carries this window's change for its module (see
CHANGELOG.md and TECHNICAL_CHANGELOG.md).

Changed in 2.4.1: the local ``_ThreadSafeSlotVar`` clone is retired
behind ``audio_suite_shared.thread_safe_slot_var.make_safe_slot_vars``,
the helper four sibling tools already used (WP-3).
Changed in 2.9.0: the progress tick is the shared mixin helper (C1).
Changed in 2.9.0: the window composes ``SuiteApp`` (C1 stage 3).  The shell
builds the Help bar, the notebook and the Processing and Results tabs, so the
window supplies its settings panel, its own album table and its run; the three
callbacks queue their payload for the shell's poller instead of calling
``root.after`` from the worker thread, and the report gains the ``SUMMARY:``
marker the suite's report lock reads.
"""

from __future__ import annotations

import logging
import os
import tkinter as tk
from pathlib import Path
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any, Mapping, Sequence, cast

from audio_suite_shared import (
    audio_playback,
    optional_deps,
    suite_config,
    ui_common,
)
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_discovery import FileDiscoveryMixin
from audio_suite_shared.suite_app import SuiteApp
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from noise_reduction.core.models import BROADBAND_ENGINES, SPECTRAL_ENGINE
from noise_reduction.core.noise_reducer import analyse_noise

from .core.file_processor import run_pipeline
from .core.models import has_active_stage
from .core.registry import CompletionRegistry
from .ui import results_tab, setup_tab
from .utils import cli_args
from .utils.cli_args import parse as parse_cli
from .utils.settings import load as load_settings
from .utils.settings import save as save_settings

logger = logging.getLogger(__name__)

_TOOL_ID = "audio_refinery"

#: How many files the Best Audio preview measures.  A preview is a sample, and
#: one decode per file is the whole cost; the run itself measures every file.
_PREVIEW_FILE_CAP = 25


class AudioRefineryApp(SuiteApp, FileDiscoveryMixin):
    """Main application window for Audio Refinery."""

    title = "Audio Refinery"
    window_key = "audio_refinery_window"
    program_name = _TOOL_ID
    #: Kept for the guide registry scan; the shell reads guide_name.
    HELP_GUIDE = "Audio_Refinery_User_Guide.docx"
    guide_name = HELP_GUIDE
    completion_text = "Refinery Complete!"
    #: The window's own tab captions, unchanged by the migration.
    tab_labels = ("  1. Setup  ", "  2. Processing  ", "  3. Results  ")
    #: The shared Results tab carries the before/after audition row.
    audition_row = True

    def __init__(self, root: tk.Tk) -> None:
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

        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Worker slot pool ──────────────────────────────────────────────────
        # Built before super().__init__: the shell renders the grid from it.
        self.slot_vars: list[tk.StringVar] = [
            tk.StringVar(value="IDLE") for _ in range(DEFAULT_MAX_WORKERS)
        ]
        self._safe_slot_vars = make_safe_slot_vars(root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(DEFAULT_MAX_WORKERS):
            self.slot_queue.put(i)

        super().__init__(root)

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

    # ── Shell tabs ────────────────────────────────────────────────────────────

    def _build_setup_tab(self, parent: tk.Frame) -> None:
        """Emit the folders, the stage panels and the run controls."""
        setup_widgets = setup_tab.build(
            parent=parent,
            source_path=self.source_path,
            output_path=self.output_path,
            config=self.config,
            on_browse_src=self._browse_source,
            on_browse_out=self._browse_output,
            on_start=self.start_processing,
            on_reset=self._reset_registry,
            on_analyse_noise=self._analyse_noise,
            on_preview_best_audio=self._preview_best_audio,
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
        self.controls_panel = setup_widgets["controls_panel"]
        self._setup_state = setup_widgets
        self._refresh_preset_list = self._setup_state.get("refresh_preset_list")

    def _build_results_tab(self, parent: tk.Frame) -> None:
        """Build the shell's Results tab, then the album table under it.

        The album report is the Refinery's own - no other tool plans an album -
        so it is added to the tab the shell built instead of a second copy of
        the shared results layout.
        """
        super()._build_results_tab(parent)
        album = results_tab.build_album_table(parent)
        # Changed in 2.7.0: the album table the completion handler fills (F-S6).
        self._album_frame: tk.Frame = album["album_frame"]
        self._album_tree: ttk.Treeview = album["album_tree"]

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

    def _on_source_changed(self, *_: Any) -> None:
        src = self.source_path.get().strip()
        if src and src != self._last_source_dir:
            self._load_registry(src)

    def _analyse_noise(self) -> None:
        """Report what the detectors measure in the folder's first file.

        Read-only by construction: one decode, the batch's own ``detect_hum``
        and ``detect_noise_profile`` through :func:`analyse_noise`, and a line
        of text in the panel.  It starts no run, touches no registry and writes
        no file, so a user can measure before deciding to enable the stage.
        """
        widgets = (getattr(self, "_setup_state", None) or {}).get("noise_widgets")
        report = widgets.get("analyse_result") if widgets else None
        if report is None:  # pragma: no cover - the panel always provides it
            return
        source = self.source_path.get().strip()
        if not source or not Path(source).is_dir():
            report.set("Choose a source folder first.")
            return
        try:
            names = sorted(self.discover_audio_files(source, SUPPORTED_EXTENSIONS))
        # A folder that cannot be read is a report line, not a crash, and the
        # reason is what the user needs on screen.
        except Exception as exc:  # noqa: BLE001 - reported in the panel, not raised
            mapped = map_to_audio_error(exc)
            logger.warning("Noise analysis could not read %s: %s", source, mapped)
            report.set(f"Could not read that folder: {user_message_for(mapped)}")
            return
        if not names:
            report.set("No supported audio files in that folder.")
            return

        name = names[0]
        try:
            from pydub import AudioSegment

            audio = AudioSegment.from_file(str(Path(source) / name))
            analysis = analyse_noise(
                audio,
                hum_harmonics=self.config.noise_reduction_params.hum_harmonics,
                gate_threshold_db=(
                    self.config.noise_reduction_params.gate_threshold_db
                ),
            )
        # A file that will not decode is a report line, not a crash, and
        # nothing has been written at this point.
        except Exception as exc:  # noqa: BLE001 - reported in the panel, not raised
            mapped = map_to_audio_error(exc)
            logger.error(
                "Noise analysis failed for %s: %s", name, mapped, exc_info=True
            )
            report.set(f"Could not analyse {name}: {user_message_for(mapped)}")
            return
        report.set(analysis.describe(name))

    def _preview_best_audio(self) -> None:
        """Report what Best Audio would decide for the first files, writing nothing.

        Read-only by construction: one decode per file, the same
        :func:`audio_refinery.core.best_audio.decide` the run calls, and a few
        lines in the panel.  It starts no run, touches no registry and writes
        no audio and no report - the preview names the file and the time each
        measurement came from, so a value is never shown as if it were the
        run's own (contract rule A10).
        """
        state = getattr(self, "_setup_state", None) or {}
        report = state.get("auto_result")
        if report is None:  # pragma: no cover - the panel always provides it
            return
        if not self.config.auto_stages:
            report.set(
                "Tick Best Audio, or tick Auto on a stage, to preview what it "
                "would decide."
            )
            return
        source = self.source_path.get().strip()
        if not source or not Path(source).exists():
            report.set("Choose a source folder first.")
            return

        if Path(source).is_dir():
            try:
                names = sorted(self.discover_audio_files(source, SUPPORTED_EXTENSIONS))[
                    :_PREVIEW_FILE_CAP
                ]
            # A folder that cannot be read is a report line, not a crash.
            except Exception as exc:  # noqa: BLE001 - reported in the panel
                mapped = map_to_audio_error(exc)
                logger.warning("Preview could not read %s: %s", source, mapped)
                report.set(f"Could not read that folder: {user_message_for(mapped)}")
                return
            paths = [Path(source) / name for name in names]
        else:
            paths = [Path(source)]

        if not paths:
            report.set("No supported audio files to preview.")
            return

        from .core.best_audio import decide, decision_text

        lines: list[str] = []
        for path in paths:
            try:
                from pydub import AudioSegment

                audio = AudioSegment.from_file(str(path))
                plan = decide(audio, path, self.config)
            # A file that will not decode is a report line, not a crash; the
            # rest of the folder is still worth previewing.
            except Exception as exc:  # noqa: BLE001 - reported in the panel
                mapped = map_to_audio_error(exc)
                logger.error("Preview failed for %s: %s", path.name, mapped)
                lines.append(
                    f"{path.name}: could not measure ({user_message_for(mapped)})"
                )
                continue
            lines.append(
                f"{path.name} (measured {plan.source.measured_at}): "
                f"{decision_text(plan)}"
            )
        if len(paths) == _PREVIEW_FILE_CAP:
            lines.append(
                f"Previewed the first {_PREVIEW_FILE_CAP} files; "
                "the run measures every file."
            )
        report.set("\n".join(lines))

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
        from .utils.settings import (
            compressor_settings_to_dict,
            eq_settings_to_dict,
            limiter_settings_to_dict,
        )

        p = self.config
        return {
            "declick": p.declick,
            "trim": p.trim,
            "enhance": p.enhance,
            "normalise": p.normalise,
            # Changed in 2.7.0: the EQ stage's toggle and rack ride a preset (F-S1).
            "eq": p.eq,
            # Changed in 2.9.0: Best Audio's per-stage selection rides a preset
            # too, as the one list a run reads (D-02).
            "auto_stages": list(p.auto_stages),
            # Changed in 2.8.0: the noise stage's toggle and its neural settings
            # ride a preset with the rest of the run.
            "reduce_noise": p.reduce_noise,
            "broadband_engine": p.noise_reduction_params.broadband_engine,
            "neural_amount": p.noise_reduction_params.neural_amount,
            "allow_16bit_output": p.noise_reduction_params.allow_16bit_output,
            # Changed in 2.8.0: hum detection rides a preset as well, so a saved
            # auto setup comes back as auto and a manual one as its fixed cascade.
            "hum_auto": p.noise_reduction_params.hum_auto,
            "hum_frequency": p.noise_reduction_params.hum_frequency,
            # Changed in 2.8.0: the profile-window mode rides a preset too.
            "profile_auto": p.noise_reduction_params.profile_auto,
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
            "true_peak": p.normalise_params.true_peak,
            "lra": p.normalise_params.lra,
            "normalise_mode": p.normalise_params.mode,
            # Changed in 2.5.0: the exact trim range rides a preset too (F-E3).
            "trim_mode": p.trim_params.mode,
            "trim_start": p.trim_params.start_ms,
            "trim_end": p.trim_params.end_ms,
            "trim_duration": p.trim_params.duration_ms,
            "trim_copy": p.trim_params.copy_mode,
            # Changed in 2.5.0: album mode is persisted with the rest of the
            # normalise delivery set (F-E1).
            "album_mode": p.normalise_params.album_mode,
            # Changed in 2.6.0: the peak target rides a preset too (F-E2).
            "target_mode": p.normalise_params.target_mode,
            "target_peak_dbtp": p.normalise_params.target_peak_dbtp,
            "eq_params": eq_settings_to_dict(p.eq_params),
            # Changed in 2.7.0: the dynamics pair rides a preset too (F-S2).
            "dynamics": p.dynamics,
            "compressor_params": compressor_settings_to_dict(p.compressor_params),
            "limiter_params": limiter_settings_to_dict(p.limiter_params),
        }

    # Preset key -> the config attribute it writes. A preset stores only the
    # stages and parameters it actually carries, so an absent key must leave
    # the current value alone rather than resetting it to a default.
    # Changed in 2.4.3: SS3.3 complexity ceiling — the preset's flat key list is
    # split into five tables so `_apply_preset` is a four-line composition; the
    # key->attribute mapping and the editor sync are unchanged.
    _STAGE_PRESET_KEYS = {
        "declick": "declick",
        "trim": "trim",
        "enhance": "enhance",
        "normalise": "normalise",
        # Changed in 2.7.0: the EQ stage's toggle (F-S1).
        "eq": "eq",
        # Changed in 2.7.0: the dynamics stage's toggle (F-S2).
        "dynamics": "dynamics",
        # Changed in 2.8.0: the noise stage's toggle.
        "reduce_noise": "reduce_noise",
    }
    _DECLICK_PRESET_KEYS = {
        "sensitivity": "sensitivity",
        "max_width_ms": "max_width_ms",
    }
    _TRIM_PRESET_KEYS = {
        "threshold": "threshold",
        "apply_fade": "apply_fade",
        "fade_in_ms": "fade_in_ms",
        "fade_out_ms": "fade_out_ms",
        # Changed in 2.5.0: an exact range is part of the trim stage (F-E3).
        "trim_mode": "mode",
        "trim_start": "start_ms",
        "trim_end": "end_ms",
        "trim_duration": "duration_ms",
        "trim_copy": "copy_mode",
    }
    _ENHANCE_PRESET_KEYS = {
        "preset": "preset",
        "noise_gate_threshold_db": "noise_gate_threshold_db",
        "compressor_threshold_db": "compressor_threshold_db",
        "compressor_ratio": "compressor_ratio",
        "compressor_attack_ms": "compressor_attack_ms",
        "compressor_release_ms": "compressor_release_ms",
        "low_shelf_gain_db": "low_shelf_gain_db",
        "low_shelf_freq_hz": "low_shelf_freq_hz",
        "presence_gain_db": "presence_gain_db",
        "presence_freq_hz": "presence_freq_hz",
        "high_shelf_gain_db": "high_shelf_gain_db",
        "high_shelf_freq_hz": "high_shelf_freq_hz",
        "output_gain_db": "output_gain_db",
        "limiter_threshold_db": "limiter_threshold_db",
        "reverse": "reverse",
        "karaoke": "karaoke",
        "karaoke_strength": "karaoke_strength",
        "phaser": "phaser",
        "flanger": "flanger",
        "chorus": "chorus",
    }
    _NORMALISE_PRESET_KEYS = {
        "target_lufs": "target_lufs",
        "tolerance": "tolerance",
        "true_peak": "true_peak",
        "lra": "lra",
        "normalise_mode": "mode",
        # Changed in 2.5.0: a stored preset may carry album mode (F-E1).
        "album_mode": "album_mode",
        # Changed in 2.6.0: and the peak target (F-E2).
        "target_mode": "target_mode",
        "target_peak_dbtp": "target_peak_dbtp",
    }

    # Changed in 2.8.0: the broadband engine and its blend ride a preset too,
    # so a saved neural setup comes back as the run that was saved.
    _NOISE_PRESET_KEYS = {
        "broadband_engine": "broadband_engine",
        "neural_amount": "neural_amount",
        "allow_16bit_output": "allow_16bit_output",
        "hum_auto": "hum_auto",
        "hum_frequency": "hum_frequency",
        "profile_auto": "profile_auto",
    }

    @staticmethod
    def _apply_preset_keys(
        target: Any, settings: dict[str, Any], keys: dict[str, str]
    ) -> None:
        """Copy each preset key that is present onto its matching attribute."""
        for key, attribute in keys.items():
            if key in settings:
                setattr(target, attribute, settings[key])

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        """Apply a stored preset, leaving absent keys untouched."""
        p = self.config
        self._apply_preset_keys(p, settings, self._STAGE_PRESET_KEYS)
        # Changed in 2.9.0: a stored preset carries the Auto selection, and a
        # preset saved before 2.9.0 simply has no key - which reads as no Auto
        # stages, the pipeline it described.
        if "auto_stages" in settings:
            from .core.models import normalise_auto_stages

            p.auto_stages = normalise_auto_stages(settings["auto_stages"])
            self._sync_auto_panel()
        self._apply_preset_keys(p.declick_params, settings, self._DECLICK_PRESET_KEYS)
        self._apply_preset_keys(p.trim_params, settings, self._TRIM_PRESET_KEYS)
        self._apply_preset_keys(
            p.noise_reduction_params, settings, self._NOISE_PRESET_KEYS
        )
        self._apply_preset_keys(p.enhance_params, settings, self._ENHANCE_PRESET_KEYS)
        self._apply_preset_keys(
            p.normalise_params, settings, self._NORMALISE_PRESET_KEYS
        )
        # Changed in 2.7.0: the parametric rack rides a preset as one object
        # (F-S1), restored through the loader's own validator.
        if "eq_params" in settings:
            from .utils.settings import eq_settings_from_dict

            p.eq_params = eq_settings_from_dict(settings["eq_params"])
        # Changed in 2.7.0: the dynamics pair comes back through its own
        # validators, so a stored preset cannot inject a refused setting.
        if "compressor_params" in settings:
            from .utils.settings import compressor_settings_from_dict

            p.compressor_params = compressor_settings_from_dict(
                settings["compressor_params"]
            )
        if "limiter_params" in settings:
            from .utils.settings import limiter_settings_from_dict

            p.limiter_params = limiter_settings_from_dict(settings["limiter_params"])
        self._sync_preset_editor(p)
        self._sync_trim_panel()
        self._sync_eq_panel()
        self._sync_dynamics_panel()
        self._sync_noise_panel()

    def _sync_auto_panel(self) -> None:
        """Push ``config.auto_stages`` into the panel through the one function.

        Every programmatic route - a restored settings file, CLI flags, Driver
        argv and a loaded preset - ends here, so the checkboxes always show the
        selection the run will use (the pre-fill rule).
        """
        apply = (getattr(self, "_setup_state", None) or {}).get("apply_auto_stages")
        if apply is not None:
            apply(self.config.auto_stages)

    def _sync_preset_editor(self, p: Any) -> None:
        """Keep the Custom DSP editor in step with the loaded preset."""
        # The editor's values are the source for every later edit, so a stale
        # copy would rewrite this preset's values back into the config on the
        # next slider move; before the editor existed the same load left the
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

            # Validate pipeline stages through the one stage list (F-S1
            # follow-up: the private five-field copy refused an EQ-only run).
            if not has_active_stage(self.config):
                messagebox.showerror(
                    "No Stages Selected", "Please enable at least one refinery stage."
                )
                return

            # A neural run needs its model before the first file.  The prompt
            # installs it once and calls this method again, so the run that
            # starts is the run the panel shows (2.8.0).
            from noise_reduction.core.noise_reducer import neural_dependency_reason

            if neural_dependency_reason(self.config.noise_reduction_params):
                ui_common.install_optional_dependency(
                    self.root,
                    optional_deps.RNNOISE,
                    on_ready=self.start_processing,
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
            # Changed in 2.7.0: the mode reaches the pipeline through the
            # config it reads. It used to stop at _run_was_dry_run, so the
            # window wrote every file a Dry Run promised to preview (F-S2
            # follow-up).
            self._run_was_dry_run = self.run_mode.get() == "Dry Run"
            self.config.dry_run = self._run_was_dry_run
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
            self.file_listbox.delete(0, tk.END)
            self.progress["value"] = 0
            self.notebook.select(self.processing_frame)
            self.overall_status.set("Pipeline running…")

            self._start_worker(self._run, (source_dir, output_dir))

        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Processing Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Processing Error",
                f"Failed to start processing:\n{user_message_for(mapped)}",
            )

    @handle_audio_errors(reraise=False, context="audio_refinery_app_run")
    def _run(self, source_dir: Path, output_dir: Path) -> None:
        # start_processing loaded the registry for this source before the
        # shell started this thread; narrow the Optional for run_pipeline.
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

    # ── Callbacks (worker thread: queue only, no widget writes) ──────────────

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
        """Queue one progress tick for the shell's poller."""
        self._ui_updates.put(
            ("progress", processed, total, succeeded, skipped, errors, display_text)
        )

    def _on_complete(
        self,
        total: int,
        processed: int,
        succeeded: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        album_rows: Sequence[Mapping[str, str]],
        **_extra: Any,
    ) -> None:
        """Write the run's report, then queue the finished run.

        The report is serialised on the run's own thread; every widget write
        is the poller's.  A failed write is queued as a message rather than
        raised, because the audio work is already done.
        """
        logger.info(
            "_on_complete called: total=%s, processed=%s, succeeded=%s, "
            "skipped=%s, errors=%s",
            total,
            processed,
            succeeded,
            skipped,
            errors,
        )
        try:
            Path(self._log_path).parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "w", encoding="utf-8") as fh:
                fh.write("Audio Refinery — Processing Log\n")
                fh.write("=" * 50 + "\n")
                # Changed in 2.9.0: one line, only when Auto was asked for, so
                # a run without it writes exactly the report it always did.
                auto_stages = getattr(getattr(self, "config", None), "auto_stages", ())
                if auto_stages:
                    from .core.models import AUTO_STAGES

                    chosen = [s for s in AUTO_STAGES if s in auto_stages]
                    mode = "DRY RUN" if self._run_was_dry_run else "LIVE"
                    fh.write(
                        f"Mode: {mode} - BEST AUDIO: {len(chosen)} of "
                        f"{len(AUTO_STAGES)} stages ({', '.join(chosen)})\n"
                    )
                fh.writelines(log_entries)
                fh.write("=" * 50 + "\n")
                # Changed in 2.9.0: the marker every suite report carries, so
                # the run-report lock reads this file like its peers' (C1).
                fh.write("SUMMARY:\n")
                fh.write(
                    f"Total: {total}  Processed: {processed}  "
                    f"Succeeded: {succeeded}  Skipped: {skipped}  Errors: {errors}  "
                    f"Time: {duration_secs:.1f}s\n"
                )
        # BLE001 boundary: the audio work is done; the write is best effort.
        except Exception as exc:  # noqa: BLE001
            mapped = map_to_audio_error(exc, context={"log_path": self._log_path})
            logger.error("Could not write the run report: %s", mapped, exc_info=True)
            self._ui_updates.put(
                (
                    "report_error",
                    "The run finished, but its report could not be written:\n"
                    f"{self._log_path}\n\n{user_message_for(mapped)}",
                )
            )

        self._ui_updates.put(("complete", succeeded, album_rows, duration_secs))

    def _on_error(self, message: str) -> None:
        """Queue a fatal run error for the shell's poller."""
        self._ui_updates.put(("error", message))

    def _show_album_rows(self, rows: Sequence[Mapping[str, str]]) -> None:
        """Fill the album table, or hide it when the run planned no album.

        Args:
            rows: One mapping per track, keyed by the CSV's column names.  An
                empty sequence hides the panel: a run that was not in album
                mode has no album to report, and an empty table under a caption
                would read as a measurement that failed.
        """
        for item in self._album_tree.get_children():
            self._album_tree.delete(item)
        if not rows:
            self._album_frame.pack_forget()
            return
        for row in rows:
            self._album_tree.insert(
                "",
                tk.END,
                values=[
                    row.get(key, "") for key, _heading in results_tab.ALBUM_COLUMNS
                ],
            )
        self._album_frame.pack(side=tk.BOTTOM, fill=tk.X)

    # ── Rendering (Tk thread: one queued message at a time) ──────────────────

    def _dispatch_ui_message(self, message: tuple[Any, ...]) -> None:
        """Render one queued message on the Tk thread."""
        kind = message[0]
        if kind == "progress":
            _, processed, total, succeeded, skipped, errors, display_text = message
            self._render_progress_standard(processed, total, display_text)
            self.overall_status.set(
                f"Processing… {processed}/{total}  ✓{succeeded}  ⊘{skipped}  ✗{errors}"
            )
        elif kind == "complete":
            _, succeeded, album_rows, duration_secs = message
            self._render_complete(succeeded, album_rows, duration_secs)
        elif kind == "error":
            super()._on_error(message[1])
            self.overall_status.set("Error")
        elif kind == "report_error":
            messagebox.showerror("Report Not Written", message[1])

    def _render_complete(
        self,
        succeeded: int,
        album_rows: Sequence[Mapping[str, str]],
        duration_secs: float,
    ) -> None:
        """Show the finished run (Tk thread only)."""
        self._show_album_rows(album_rows)
        # Changed in 2.9.0: a run that measured its own parameters opens the
        # results with level matching ticked, because the difference a measured
        # run makes is mostly a level difference.  The shipped switch is
        # unchanged and the user can untick it.
        level_match = getattr(self, "_level_match_var", None)
        auto_stages = getattr(getattr(self, "config", None), "auto_stages", ())
        if auto_stages and level_match is not None:
            level_match.set(True)
        self.overall_status.set("Complete")
        self.completion_text = f"Refinery Complete — {succeeded} file(s) processed"
        self.render_completion(duration_secs=duration_secs, output_dir=self._out_dir)

        if self._run_was_dry_run:
            # Nothing was written - the captured original is what exists on
            # disk, so only Play Original is meaningful.
            self.set_audition_state(
                self._audition_original,
                None,
                "Dry Run — nothing written. Play Result is unavailable.",
            )
        elif self._audition_original is not None and self._audition_result is not None:
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

    # ── CLI integration ───────────────────────────────────────────────────────

    def _sync_trim_panel(self) -> None:
        """Show the applied trim settings on the Setup panel.

        The panel is built before the CLI arguments are applied (and before a
        preset is loaded), so without this a driver launch that names a range
        would display the stored mode and empty entries beside a run that cuts
        one.  Setting the widget variables routes through the same traces a
        user edit uses, so the panel and the run cannot disagree.
        """
        widgets = (getattr(self, "_setup_state", None) or {}).get("trim_widgets")
        if not widgets:
            return
        p = self.config.trim_params
        widgets["mode"].set(p.mode)
        widgets["start"].set("" if p.start_ms is None else str(p.start_ms))
        widgets["end"].set("" if p.end_ms is None else str(p.end_ms))
        widgets["duration"].set("" if p.duration_ms is None else str(p.duration_ms))
        widgets["copy"].set(bool(p.copy_mode))

    def _sync_eq_panel(self) -> None:
        """Show the applied EQ rack on the Setup panel.

        The panel is built before the CLI arguments are applied and before a
        preset is loaded, so without this a launch would run one rack while the
        table and curve showed another.  The refresh re-reads
        ``config.eq_params`` and redraws through the engine's own response.
        """
        refresh = (getattr(self, "_setup_state", None) or {}).get("eq_refresh")
        if callable(refresh):
            refresh()

    def _sync_dynamics_panel(self) -> None:
        """Show the dynamics pair the run will actually use (F-S2).

        A preset or a Driver launch assigns the settings objects directly, so
        without this the panel would keep showing the previous compressor and
        limiter while the run used the restored pair.
        """
        entries = (getattr(self, "_setup_state", None) or {}).get("dynamics_entries")
        if not entries:
            return
        p = self.config
        values = {
            "threshold_db": p.compressor_params.threshold_db,
            "ratio": p.compressor_params.ratio,
            "attack_ms": p.compressor_params.attack_ms,
            "release_ms": p.compressor_params.release_ms,
            "makeup_db": p.compressor_params.makeup_db,
            "ceiling_dbtp": p.limiter_params.ceiling_dbtp,
            "lookahead_ms": p.limiter_params.lookahead_ms,
            "limiter_release_ms": p.limiter_params.release_ms,
        }
        for name, value in values.items():
            var = entries.get(name)
            if var is not None:
                var.set(f"{value:g}")

    def _sync_noise_panel(self) -> None:
        """Show the noise engine the run will actually use (2.8.0).

        A preset, a restored settings file or a Driver launch assigns the params
        directly, so the panel is refreshed through the same variables a user
        edit uses - the traces on them are the one writer - and the panel cannot
        disagree with the stage.
        """
        widgets = (getattr(self, "_setup_state", None) or {}).get("noise_widgets")
        if not widgets:
            return
        p = self.config.noise_reduction_params
        # Changed in 2.8.0: both values are read before either is set.  The
        # panel's one update function (a trace on each of these variables)
        # writes ``broadband_engine`` *and* ``neural_amount`` from the widgets, so
        # setting one first feeds the other's stale on-screen value back into the
        # run: a Driver ``--denoise-amount 55`` showed and ran 100 %, and a
        # restored neural preset came back as the spectral engine.  Capture,
        # then set, and the second trace writes exactly the captured pair.
        engine = (
            p.broadband_engine
            if p.broadband_engine in BROADBAND_ENGINES
            else SPECTRAL_ENGINE
        )
        amount_percent = max(int(round(p.neural_amount * 100)), 1)
        # The hum mode is one variable too, so a restored preset or a Driver
        # launch shows Auto or its override rather than the last thing clicked.
        if "hum" in widgets:
            widgets["hum"].set("auto" if p.hum_auto else str(p.hum_frequency))
        # Changed in 2.8.0: the profile window mode is a variable as well, so a
        # restored preset shows Auto (detect) or its manual region.
        if "profile" in widgets:
            widgets["profile"].set(p.profile_auto)
        widgets["amount"].set(amount_percent)
        widgets["engine"].set(engine)
        # Changed in 2.8.0: the 16-bit opt-in is a variable too, so a preset or a
        # Driver launch shows the state the run will use rather than the panel's
        # construction-time default.
        widgets["allow_wide"].set(p.allow_16bit_output)

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
        # Changed in 2.9.0: --best-audio / --auto-stage resolve to one list in
        # the argument parser, and this is the only place the run reads it.
        self.config.auto_stages = args.auto_stages
        self._sync_auto_panel()
        # Changed in 2.7.0: --eq-band implies the EQ stage, so the flag cannot
        # configure bands for a stage the run would not execute (F-S1).
        self.config.eq = "eq" in active or bool(args.eq_bands)

        # Per-stage params from CLI
        self.config.declick_params.sensitivity = args.sensitivity
        self.config.declick_params.max_width_ms = args.width
        self.config.trim_params.threshold = args.threshold
        self.config.trim_params.apply_fade = args.fade
        self.config.trim_params.fade_in_ms = args.fade_in
        self.config.trim_params.fade_out_ms = args.fade_out
        # Changed in 2.5.0: the exact trim range and copy mode reach the run,
        # and the panel is re-synced so a driver launch shows them (F-E3).
        self.config.trim_params.mode = args.trim_mode
        self.config.trim_params.start_ms = args.trim_start
        self.config.trim_params.end_ms = args.trim_end
        self.config.trim_params.duration_ms = args.trim_duration
        self.config.trim_params.copy_mode = args.trim_copy
        self._sync_trim_panel()
        self.config.noise_reduction_params.reduce_hum = args.reduce_hum
        # Changed in 2.8.0: an explicit --hum-frequency on the command line is the
        # override; without it the file's own hum is detected.
        self.config.noise_reduction_params.hum_auto = args.hum_auto
        self.config.noise_reduction_params.hum_frequency = args.hum_frequency
        self.config.noise_reduction_params.hum_harmonics = args.hum_harmonics
        self.config.noise_reduction_params.hum_quality = args.hum_quality
        self.config.noise_reduction_params.reduce_broadband = args.reduce_broadband
        # Changed in 2.8.0: a typed region is the override; without one the gate
        # measures each file's quietest stretch.
        self.config.noise_reduction_params.profile_auto = args.profile_auto
        self.config.noise_reduction_params.noise_start_ms = args.noise_start_ms
        self.config.noise_reduction_params.noise_end_ms = args.noise_end_ms
        self.config.noise_reduction_params.gate_threshold_db = args.gate_threshold_db
        # Changed in 2.8.0: the engine and its blend reach the run, and the
        # panel shows them (the Driver can pass both).
        self.config.noise_reduction_params.broadband_engine = (
            args.broadband_engine
            if args.broadband_engine in BROADBAND_ENGINES
            else SPECTRAL_ENGINE
        )
        self.config.noise_reduction_params.neural_amount = args.denoise_amount / 100.0
        self.config.noise_reduction_params.allow_16bit_output = args.allow_16bit_output
        self._sync_noise_panel()
        self.config.enhance_params.preset = args.preset
        # Changed in 2.7.0: the Driver's --eq-band reaches the run (F-S1).
        if args.eq_bands:
            from audio_suite_shared.dsp_eq import EqSettings, parse_band

            self.config.eq_params = EqSettings(
                bands=tuple(parse_band(text) for text in args.eq_bands)
            )
            self._sync_eq_panel()
        # Changed in 2.7.0: the dynamics stage and its pair reach the run (F-S2).
        from audio_suite_shared.dsp_dynamics import (
            CompressorSettings,
            LimiterSettings,
        )

        self.config.dynamics = "dynamics" in active or bool(args.dynamics)
        self.config.compressor_params = CompressorSettings(
            threshold_db=args.comp_threshold,
            ratio=args.comp_ratio,
            attack_ms=args.comp_attack,
            release_ms=args.comp_release,
            makeup_db=args.comp_makeup,
        )
        self.config.limiter_params = LimiterSettings(
            ceiling_dbtp=args.limiter_ceiling,
            lookahead_ms=args.limiter_lookahead,
            release_ms=args.limiter_release,
        )
        self._sync_dynamics_panel()
        self.config.normalise_params.target_lufs = args.target_lufs
        self.config.normalise_params.tolerance = args.tolerance
        self.config.normalise_params.true_peak = args.true_peak
        self.config.normalise_params.lra = args.lra
        self.config.normalise_params.mode = args.normalise_mode
        # Changed in 2.5.0: the Driver's --album-mode reaches the run (F-E1).
        self.config.normalise_params.album_mode = args.album_mode
        # Changed in 2.6.0: so does the peak target (F-E2).
        self.config.normalise_params.target_mode = args.target_mode
        self.config.normalise_params.target_peak_dbtp = args.target_peak

        if should_auto_start:
            self.root.after(1500, self.start_processing)


def main() -> None:
    root = tk.Tk()
    AudioRefineryApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
