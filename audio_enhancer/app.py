"""
app.py
AudioEnhancerApp — thin orchestrator.

Thread-safety
-------------
All worker callbacks (_on_progress, _on_complete, _on_error) are invoked
from daemon threads.  Every one of them marshals its UI mutations back
onto the Tkinter main thread using self.root.after(0, fn) so that no
widget is ever touched from a background thread.

Slot pool
---------
DEFAULT_MAX_WORKERS is imported from the shared constants module so that
the slot-pool size and the ThreadPoolExecutor max_workers are always
identical — changing the one constant updates both.
"""

from __future__ import annotations

import logging
import threading
import tkinter as tk
from dataclasses import replace
from pathlib import Path
from queue import Queue
from tkinter import filedialog, messagebox, ttk
from typing import Any, cast

from audio_suite_shared import styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.cli_helpers import (
    UniversalCLIHandler,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.dsp_models import (
    EnhancementParams as SharedEnhancementParams,
)
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_audition import AuditionMixin
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core.file_processor import run_enhancement
from .core.models import PRESETS, EnhancementParams, PresetName, ProcessingResult
from .ui import processing_tab, results_tab, setup_tab
from .utils.cli_args import parse as parse_cli

logger = logging.getLogger(__name__)

_TOOL_ID = "audio_enhancer"


class AudioEnhancerApp(UIHelperMixin, AuditionMixin):
    """Main application window for Audio Enhancer."""

    HELP_GUIDE = "Audio_Enhancer_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.update_idletasks()
        self.error_logger, _ = bootstrap_tool_app(
            self.root,
            "Audio Enhancer",
            "audio_enhancer_window",
            "audio_enhancer",
            width=880,
            height=980,
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.source_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.preset_name = tk.StringVar(value=PresetName.MODERATE.value)
        self.run_mode = tk.StringVar(value="Live Update")
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)

        # Shared mutable params object — sliders write into it directly via
        # trace callbacks built inside setup_tab.
        self.params = EnhancementParams(**vars(PRESETS[PresetName.MODERATE]))

        # ── State (set on main thread before processing starts) ───────────────
        self._log_path: str = ""
        self._out_dir: str = ""
        self._in_place: bool = False
        self._run_was_dry_run: bool = False
        self.auto_start: bool = False
        self.auto_end: bool = False
        self._driver_locked = was_launched_from_driver()

        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

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

        # ── CLI args override ─────────────────────────────────────────────────
        self._apply_cli_args()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.source_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.source_path.set(last)

    # ── Initialisation helpers ────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        args = parse_cli()

        # Universal CLI handling
        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            args,
            source_var=self.source_path,
            output_var=self.output_path,
            auto_start_func=self.start_processing,
        )

        # Apply Audio Enhancer-specific settings
        if args.preset:
            self.preset_name.set(args.preset)
        self.auto_end = args.auto_end
        if args.live_mode is not None:
            self.run_mode.set("Live Update" if args.live_mode else "Dry Run")
        self.auto_start_var.set(args.auto_start)
        self.auto_end_var.set(args.auto_end)

        # Mirror driver display-only vars
        self.clear_logs_var.set(args.clear_logs)
        self.parallel_var.set(args.parallel_run)

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    def _build_ui(self) -> None:
        # Help button bar
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

        # Notebook tabs
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both", padx=10, pady=10)

        tab_setup = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_processing = tk.Frame(self.notebook, bg=styles.BG_LIGHT)
        tab_results = tk.Frame(self.notebook, bg=styles.BG_LIGHT)

        self.notebook.add(tab_setup, text=" 1. Setup ")
        self.notebook.add(tab_processing, text=" 2. Processing ")
        self.notebook.add(tab_results, text=" 3. Results ")

        # Setup tab
        # NOTE: core.models.EnhancementParams and the UI's shared
        # dsp_models.EnhancementParams are field-identical duplicate classes;
        # the setup tab only reads attributes, so a cast is safe at this seam.
        self.start_btn, self._refresh_preset_list, self._param_values = setup_tab.build(
            tab_setup,
            source_path=self.source_path,
            output_path=self.output_path,
            preset_name=self.preset_name,
            params=cast("SharedEnhancementParams", self.params),
            on_browse_src=self._browse_source,
            on_browse_out=self._browse_output,
            on_start=self.start_processing,
            run_mode=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            driver_locked=self._driver_locked,
            preset_names=suite_config.list_presets(_TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
        )

        # Processing tab
        proc_widgets = processing_tab.build(tab_processing, self.slot_vars)
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]

        # Results tab
        res_widgets = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_folder,
            on_play_original=self._play_original,
            on_play_result=self._play_result,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]
        self.time_label: tk.Label = res_widgets["time_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]
        self.setup_audition(res_widgets)

        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # ── UI event handlers (always on main thread) ─────────────────────────────

    def _browse_source(self) -> None:
        # Allow selecting a single file or a directory
        path = filedialog.askdirectory(title="Select folder of audio files")
        if not path:
            # Fallback: single file
            path = filedialog.askopenfilename(
                title="Select audio file",
                filetypes=[
                    ("Audio files", "*.mp3 *.flac *.wav *.ogg *.m4a *.aiff *.aif"),
                    ("All files", "*.*"),
                ],
            )
        if path:
            self.source_path.set(path)
            suite_config.save_last_directory(str(Path(path).parent))

    def _browse_output(self) -> None:
        self._browse_folder_standard(
            title="Select output folder",
            path_variable=self.output_path,
            save_last_dir=False,
        )

    def _open_help(self) -> None:
        self._open_help_standard(self.HELP_GUIDE)

    def _open_log(self) -> None:
        self._open_log_standard()

    def _open_folder(self) -> None:
        self._open_folder_standard()

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        settings: dict[str, Any] = {
            "source_path": self.source_path.get(),
            "output_path": self.output_path.get(),
            "preset_name": self.preset_name.get(),
        }
        settings.update(self._param_values)
        return settings

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "source_path" in settings:
            self.source_path.set(settings["source_path"])
        if "output_path" in settings:
            self.output_path.set(settings["output_path"])
        if "preset_name" in settings:
            self.preset_name.set(settings["preset_name"])
        p = self.params
        overrides: dict[str, float] = {}
        for field_name in EnhancementParams.__dataclass_fields__:
            if field_name in settings:
                overrides[field_name] = settings[field_name]
        if overrides:
            self.params = replace(p, **overrides)

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
        """Start the audio enhancement process."""
        src = self.source_path.get().strip()
        if not src:
            messagebox.showwarning(
                "Warning", "Please select a source file or folder first."
            )
            return

        source_path = Path(src)
        if not source_path.exists():
            messagebox.showwarning("Warning", f"Path does not exist:\n{src}")
            return

        # Resolve output directory on the main thread before the worker starts,
        # eliminating any read/write race on _out_dir and _log_path.
        out_raw = self.output_path.get().strip()
        if out_raw:
            output_dir = Path(out_raw)
        else:
            # No output folder specified — in-place replacement.
            # Pop-up confirmation removed per request.
            base = source_path if source_path.is_dir() else source_path.parent
            output_dir = base

        self._out_dir = str(output_dir)
        self._log_path = str(output_dir / "enhancement_log.txt")

        # In-place runs overwrite the source files, so snapshot the first one
        # now to give the A/B buttons a "before" file to play later.
        base = source_path if source_path.is_dir() else source_path.parent
        self._in_place = output_dir.resolve() == base.resolve()
        if self._in_place:
            self.prepare_in_place_audition(base, SUPPORTED_EXTENSIONS)
        else:
            self.clear_audition()

        suite_config.save_last_directory(
            str(source_path if source_path.is_dir() else source_path.parent)
        )

        self._run_was_dry_run = self.run_mode.get() == "Dry Run"
        self.start_btn.config(state="disabled")
        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        self.notebook.select(self._tab_processing)
        self.overall_status.set("Enhancing audio files…")

        threading.Thread(
            target=self._run, args=(source_path, output_dir), daemon=True
        ).start()

    # ── Worker thread ─────────────────────────────────────────────────────────

    @handle_audio_errors(reraise=False, context="audio_enhancer_app_run")
    def _run(self, source_path: Path, output_dir: Path) -> None:
        """Runs entirely on the daemon worker thread."""
        is_dry_run = self.run_mode.get() == "Dry Run"
        run_enhancement(
            source_path=source_path,
            output_dir=output_dir,
            params=EnhancementParams(**self._param_values),
            is_dry_run=is_dry_run,
            slot_vars=self._safe_slot_vars,
            slot_queue=self.slot_queue,
            on_progress=self._on_progress,
            on_complete=self._on_complete,
            on_error=self._on_error,
        )

    # ── Worker callbacks — marshal to main thread via root.after() ────────────

    def _on_progress(
        self,
        processed: int,
        total: int,
        done: int,
        errors: int,
        result: ProcessingResult,
        display_text: str,
    ) -> None:
        def _update() -> None:
            self.progress["maximum"] = total
            self.progress["value"] = processed
            self.stats_label.config(
                text=(
                    f"Processed: {processed}/{total}  |  "
                    f"Enhanced: {done}  |  "
                    f"Errors: {errors}"
                )
            )
            self.file_listbox.insert(tk.END, display_text)
            self.file_listbox.see(tk.END)

        self.root.after(0, _update)

    def _on_complete(
        self,
        total: int,
        done: int,
        errors: int,
        duration_secs: float,
        results: list[ProcessingResult],
    ) -> None:
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)

        log_lines: list[str] = [
            "AUDIO ENHANCEMENT REPORT\n",
            "=" * 60 + "\n",
        ]
        for r in results:
            if r.status.value == "Done":
                log_lines.append(
                    f"[DONE]  {r.source.name}  "
                    f"{r.gain_db:+.1f} dB  tags:{r.tags_copied}\n"
                )
            else:
                # SKIPPED/FAILED results carry their own pre-built
                # display_text (e.g. "[SKIP] track.mp3: file not found")
                # since `source`/`error_message` are not populated on
                # these paths — see ProcessingResult docstring.
                log_lines.append(f"{r.display_text}\n")

        log_lines += [
            "\n" + "=" * 60 + "\n",
            "SUMMARY\n",
            f"Total files : {total}\n",
            f"Enhanced    : {done}\n",
            f"Errors      : {errors}\n",
            f"Duration    : {minutes:02d}:{seconds:02d}\n",
        ]

        def _update() -> None:
            try:
                Path(self._log_path).parent.mkdir(parents=True, exist_ok=True)
                with open(self._log_path, "w", encoding="utf-8") as fh:
                    fh.writelines(log_lines)
            except OSError as exc:
                messagebox.showerror(
                    "Error",
                    f"Could not write log file:\n"
                    f"{user_message_for(map_to_audio_error(exc))}",
                )

            self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
            self.summary_label.config(
                text=(f"Total: {total} files\nEnhanced: {done}\nErrors: {errors}")
            )
            self.completion_label.config(
                text="Enhancement Complete!"
                if not self._run_was_dry_run
                else "Enhancement Dry Run Complete!"
            )
            self.notebook.select(self._tab_results)
            self.start_btn.config(state="normal")

            # Expose the before/after audition pair (first successfully enhanced
            # file) once the run has finished.
            done_results = [r for r in results if r.status.value == "Done"]
            if self._run_was_dry_run:
                self.set_audition_state(
                    self._audition_original,
                    None,
                    "Dry Run — nothing written. Play Result is unavailable.",
                )
            elif self._in_place:
                if (
                    self._audition_original is not None
                    and self._audition_result is not None
                ):
                    name = Path(self._audition_result).name
                    self.set_audition_state(
                        self._audition_original,
                        self._audition_result,
                        f"Audition ready — {name} (original vs enhanced)",
                    )
                else:
                    self.set_audition_state(
                        None, None, "No supported audio file found for audition."
                    )
            elif done_results:
                first = done_results[0]
                self.set_audition_state(
                    first.source,
                    first.output,
                    f"Audition ready — {first.source.name} (original vs enhanced)",
                )

            if self.auto_end_var.get():
                self.root.after(500, self.root.destroy)

        self.root.after(0, _update)

    def _on_error(self, message: str) -> None:
        def _update() -> None:
            messagebox.showerror("Error", message)
            self.start_btn.config(state="normal")

        self.root.after(0, _update)


def main() -> None:
    """Main entry point for Audio Enhancer application."""
    root = tk.Tk()
    AudioEnhancerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
