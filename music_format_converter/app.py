"""
app.py
MusicFormatConverterApp — thin orchestrator.
Wires UI, core logic, and utilities together. No business logic here.
"""

import logging
import os
import threading
import tkinter as tk
from queue import Queue
from tkinter import messagebox, ttk
from typing import Any

from audio_suite_shared import styles, suite_config
from audio_suite_shared.app_bootstrap import bootstrap_tool_app
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.cli_helpers import UniversalCLIHandler
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.thread_safe_slot_var import make_safe_slot_vars
from audio_suite_shared.ui_helpers import UIHelperMixin

from .core import file_processor
from .core.formats import (
    ALL_FORMATS,
    LOSSY_FORMATS,
    detect_format,
    scan_input_directory,
)
from .ui import processing_tab, results_tab, setup_tab
from .utils import cli_args
from .utils.ffmpeg_check import check_ffmpeg

logger = logging.getLogger(__name__)

TOOL_ID = "music_format_converter"


class MusicFormatConverterApp(UIHelperMixin):
    """Music Format Converter application GUI."""

    HELP_GUIDE = "Music_Format_Converter_User_Guide.docx"

    def __init__(self, root: tk.Tk):
        self.root = root
        self.error_logger, self.style = bootstrap_tool_app(
            self.root,
            "Music Format Converter",
            "music_format_converter_window",
            TOOL_ID,
        )

        # ── Tk variables ──────────────────────────────────────────────────────
        self.folder_path = tk.StringVar()
        self.output_format = tk.StringVar(value="mp3")
        self.output_folder = tk.StringVar()
        self.quality_preset = tk.StringVar(value="highest")
        self.sample_rate = tk.StringVar(value="source")
        self.bit_depth = tk.StringVar(value="auto")
        self.delete_originals = tk.BooleanVar(value=False)
        self.normalize_mp3 = tk.BooleanVar(value=False)
        self.target_lufs = tk.DoubleVar(value=-16.0)
        self.run_mode = tk.StringVar(value="Live Update")

        # Driver-mirrored run controls (Clear Logs / Parallel are display-only)
        self.auto_start_var = tk.BooleanVar(value=False)
        self.auto_end_var = tk.BooleanVar(value=False)
        self.clear_logs_var = tk.BooleanVar(value=False)
        self.parallel_var = tk.BooleanVar(value=False)
        self._launched_from_driver = cli_args.was_launched_from_driver()

        # ── State ─────────────────────────────────────────────────────────────
        self._log_path: str = ""
        self._output_dir_final: str = ""
        self._out_dir: str = ""
        self._available_formats: list[Any] = list(ALL_FORMATS)
        self.ffmpeg_available: bool = check_ffmpeg()
        self._preset_combo: ttk.Combobox | None = None
        self._refresh_preset_list: Any = None

        # ── Worker slot pool ──────────────────────────────────────────────────
        self.slot_vars = [tk.StringVar(value="IDLE") for _ in range(4)]
        self._safe_slot_vars = make_safe_slot_vars(self.root, self.slot_vars)
        self.slot_queue: Queue[Any] = Queue()
        for i in range(4):
            self.slot_queue.put(i)

        # ── Build UI ──────────────────────────────────────────────────────────
        self._build_ui()

        # ── Apply CLI arguments ───────────────────────────────────────────────
        self._apply_cli_args()

        # ── Restore last-used directory (if not set by CLI) ───────────────────
        if not self.folder_path.get():
            last = suite_config.load_last_directory()
            if last:
                self.folder_path.set(last)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
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

        widgets = setup_tab.build(
            tab_setup,
            folder_path=self.folder_path,
            output_folder=self.output_folder,
            output_format=self.output_format,
            quality_preset=self.quality_preset,
            sample_rate=self.sample_rate,
            bit_depth=self.bit_depth,
            delete_originals=self.delete_originals,
            normalize_mp3=self.normalize_mp3,
            target_lufs=self.target_lufs,
            run_mode=self.run_mode,
            auto_start_var=self.auto_start_var,
            auto_end_var=self.auto_end_var,
            clear_logs_var=self.clear_logs_var,
            parallel_var=self.parallel_var,
            ffmpeg_available=self.ffmpeg_available,
            all_formats=ALL_FORMATS,
            on_browse_input=self._browse_input,
            on_browse_output=self._browse_output,
            on_start=self.start_processing,
            driver_locked=self._launched_from_driver,
            on_folder_change=self._on_folder_change,
            preset_names=suite_config.list_presets(TOOL_ID),
            on_save_preset=self._save_current_as_preset,
            on_delete_preset=self._delete_preset,
            on_preset_selected=self._on_preset_selected,
        )
        self.start_btn = widgets["start_btn"]
        self._update_detected_label = widgets["update_detected_label"]
        self._update_format_menu = widgets["update_format_menu"]
        self._update_format_info = widgets["update_format_info"]
        self._refresh_preset_list = widgets["refresh_preset_list"]
        self._preset_combo = widgets["preset_combo"]

        proc_widgets = processing_tab.build(tab_processing, self.slot_vars)
        self.overall_status: tk.StringVar = proc_widgets["overall_status"]
        self.progress: ttk.Progressbar = proc_widgets["progress"]
        self.stats_label: tk.Label = proc_widgets["stats_label"]
        self.file_listbox: tk.Listbox = proc_widgets["file_listbox"]

        res_widgets = results_tab.build(
            tab_results,
            on_open_log=self._open_log,
            on_open_folder=self._open_output_folder,
        )
        self.completion_label: tk.Label = res_widgets["completion_label"]
        self.summary_label: tk.Label = res_widgets["summary_label"]
        self.time_label: tk.Label = res_widgets["time_label"]

        self._tab_setup = tab_setup
        self._tab_processing = tab_processing
        self._tab_results = tab_results

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        return {
            "output_format": self.output_format.get(),
            "quality_preset": self.quality_preset.get(),
            "sample_rate": self.sample_rate.get(),
            "bit_depth": self.bit_depth.get(),
            "delete_originals": self.delete_originals.get(),
            "normalize_mp3": self.normalize_mp3.get(),
            "target_lufs": self.target_lufs.get(),
            "run_mode": self.run_mode.get(),
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "output_format" in settings:
            self.output_format.set(settings["output_format"])
        if "quality_preset" in settings:
            self.quality_preset.set(settings["quality_preset"])
        if "sample_rate" in settings:
            self.sample_rate.set(settings["sample_rate"])
        if "bit_depth" in settings:
            self.bit_depth.set(settings["bit_depth"])
        if "delete_originals" in settings:
            self.delete_originals.set(settings["delete_originals"])
        if "normalize_mp3" in settings:
            self.normalize_mp3.set(settings["normalize_mp3"])
        if "target_lufs" in settings:
            self.target_lufs.set(settings["target_lufs"])
        if "run_mode" in settings:
            self.run_mode.set(settings["run_mode"])

    def _on_preset_selected(self, name: str) -> None:
        settings = suite_config.load_preset(TOOL_ID, name)
        if settings:
            self._apply_preset(settings)

    def _save_current_as_preset(self, name: str) -> None:
        suite_config.save_preset(TOOL_ID, name, self._collect_settings())
        self._refresh_preset_list(suite_config.list_presets(TOOL_ID))

    def _delete_preset(self, name: str) -> None:
        suite_config.delete_preset(TOOL_ID, name)
        self._refresh_preset_list(suite_config.list_presets(TOOL_ID))

    # ── CLI handling ──────────────────────────────────────────────────────────

    def _apply_cli_args(self) -> None:
        parsed = cli_args.parse()
        if not parsed.folder_path:
            return

        # Mirror the driver's run controls onto the Setup tab panel.
        self.auto_start_var.set(parsed.auto_start)
        self.auto_end_var.set(parsed.auto_end)
        self.clear_logs_var.set(parsed.clear_logs)
        self.parallel_var.set(parsed.parallel_run)

        cli_handler = UniversalCLIHandler(self)
        should_auto_start = cli_handler.apply_cli_args(
            parsed,
            folder_var=self.folder_path,
        )

        if parsed.output_format:
            self.output_format.set(parsed.output_format)
        if parsed.live_mode is not None:
            self.run_mode.set("Live Update" if parsed.live_mode else "Dry Run")
        if parsed.quality:
            self.quality_preset.set(parsed.quality)
        if parsed.sample_rate:
            self.sample_rate.set(parsed.sample_rate)
        if parsed.bit_depth:
            self.bit_depth.set(parsed.bit_depth)
        if parsed.delete_originals:
            self.delete_originals.set(True)
        if parsed.normalize_mp3:
            self.normalize_mp3.set(True)
        if parsed.target_lufs != -16.0:
            self.target_lufs.set(parsed.target_lufs)
        if parsed.output_dir:
            self.output_folder.set(parsed.output_dir)

        if should_auto_start:
            self.root.after(500, self._on_folder_change)

        if should_auto_start:
            self.root.after(1500, self.start_processing)

    # ── Folder-change handler (scan + update UI) ──────────────────────────────

    def _on_folder_change(self) -> None:
        result = scan_input_directory(self.folder_path.get())
        self._available_formats = result.output_formats

        is_error = not result.ok and bool(result.mixed_formats or result.error_message)

        self._update_detected_label(result.status_text, is_error)

        if result.mixed_formats:
            messagebox.showerror(
                "Mixed Formats Detected",
                f"Error: Input folder contains multiple audio formats: "
                f"{', '.join(result.mixed_formats)}\n\n"
                f"Please ensure all input files are in the same format.",
            )

        current = self.output_format.get()
        if current in result.output_formats:
            selected = current
        elif "mp3" in result.output_formats:
            selected = "mp3"
        elif result.output_formats:
            selected = result.output_formats[0]
        else:
            selected = ""

        self._update_format_menu(result.output_formats, selected)

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse_input(self) -> None:
        self._browse_folder_standard(
            title="Select Input Music Directory",
            path_variable=self.folder_path,
            save_last_dir=True,
        )
        self._on_folder_change()

    def _browse_output(self) -> None:
        self._browse_folder_standard(
            title="Select Output Directory",
            path_variable=self.output_folder,
            save_last_dir=False,
        )

    def _open_log(self) -> None:
        self._open_log_standard()

    def _open_output_folder(self) -> None:
        self._open_folder_standard()

    def _reset_ui(self) -> None:
        self.notebook.select(self._tab_setup)
        self.file_listbox.delete(0, tk.END)
        self.progress["value"] = 0
        for var in self.slot_vars:
            var.set("IDLE")

    def start_processing(self) -> None:
        """Start processing with enhanced validation and error handling."""
        try:
            input_folder = self.folder_path.get().strip()

            if not input_folder:
                messagebox.showerror(
                    "No Input Directory",
                    "Please select an input music directory containing audio files.",
                )
                return

            if not os.path.exists(input_folder):
                messagebox.showerror(
                    "Input Not Found",
                    f"The input directory does not exist:\n{input_folder}",
                )
                return

            if not os.path.isdir(input_folder):
                messagebox.showerror(
                    "Invalid Input Directory",
                    f"The input path is not a valid directory:\n{input_folder}",
                )
                return

            try:
                has_audio = any(
                    detect_format(f) is not None for f in os.listdir(input_folder)
                )

                if not has_audio:
                    messagebox.showerror(
                        "No Audio Files",
                        f"No supported audio files found in:\n{input_folder}\n\n"
                        f"Supported formats: "
                        f"{', '.join(f.upper() for f in ALL_FORMATS)}",
                    )
                    return
            except PermissionError as exc:
                messagebox.showerror(
                    "Access Denied",
                    f"Cannot access input directory:\n{input_folder}\n\n{str(exc)}",
                )
                return

            if not self.ffmpeg_available:
                messagebox.showerror(
                    "FFmpeg Required",
                    "FFmpeg is not available. Please install FFmpeg first.",
                )
                return

            if not self._available_formats:
                messagebox.showerror(
                    "No Valid Formats",
                    "No valid output formats available. "
                    "Please check your input directory.",
                )
                return

            output_format = self.output_format.get()
            if not output_format:
                messagebox.showerror(
                    "No Output Format", "Please select an output format."
                )
                return

            output_folder = self.output_folder.get().strip()
            if output_folder:
                if not os.path.exists(output_folder):
                    messagebox.showerror(
                        "Output Not Found",
                        f"The output directory does not exist:\n{output_folder}",
                    )
                    return

                if not os.path.isdir(output_folder):
                    messagebox.showerror(
                        "Invalid Output Directory",
                        f"The output path is not a valid directory:\n{output_folder}",
                    )
                    return

            if self.delete_originals.get():
                if not messagebox.askyesno(
                    "Confirm Delete Originals",
                    "⚠ WARNING ⚠\n\n"
                    "You have chosen to DELETE ORIGINAL FILES after conversion.\n\n"
                    "This action is PERMANENT and cannot be undone!\n\n"
                    "Are you sure you want to continue?",
                    icon="warning",
                ):
                    return

            self.start_btn.config(state="disabled")
            self.file_listbox.delete(0, tk.END)
            self.notebook.select(self._tab_processing)
            self.overall_status.set(f"Converting to {output_format.upper()}...")

            threading.Thread(target=self._run, daemon=True).start()

        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Processing Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Processing Error",
                f"Failed to start processing:\n{user_message_for(mapped)}",
            )

    @handle_audio_errors(reraise=False, context="format_converter_app_run")
    def _run(self) -> None:
        input_dir = self.folder_path.get()
        output_dir = self.output_folder.get() or input_dir
        fmt = self.output_format.get()
        quality = self.quality_preset.get()
        sample_rate = self.sample_rate.get()
        bit_depth = self.bit_depth.get()
        delete = self.delete_originals.get()
        is_dry_run = self.run_mode.get() == "Dry Run"
        normalize_mp3 = self.normalize_mp3.get() and fmt == "mp3"
        target_lufs = self.target_lufs.get()

        log_name = f"conversion_{'dry_run' if is_dry_run else 'live'}_log_{fmt}.txt"
        self._log_path = os.path.join(output_dir, log_name)
        self.progress["value"] = 0

        header: list[str] = [
            "MUSIC FORMAT CONVERSION REPORT\n",
            f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
            f"Output Format: {fmt.upper()}\n",
            f"Quality Preset: {quality}\n",
            f"Sample Rate: {sample_rate}\n",
            f"Bit Depth: {bit_depth}\n",
            f"Input Directory: {input_dir}\n",
            f"Output Directory: {output_dir}\n",
            f"Delete Originals: {'YES' if delete else 'NO'}\n",
        ]
        if self.normalize_mp3.get() and fmt == "mp3":
            header.append(
                "Normalize MP3 (Lossless): YES\n"
                f"Target Loudness: {target_lufs:.1f} LUFS\n"
            )
        else:
            header.append("Normalize MP3 (Lossless): NO\n")
        header.append("=" * 60 + "\n")

        with active_batch("music_format_converter", "file_delete"):
            file_processor.run_conversion(
                input_dir=input_dir,
                output_dir=output_dir,
                output_format=fmt,
                quality=quality,
                delete_originals=delete,
                is_dry_run=is_dry_run,
                lossy_formats=LOSSY_FORMATS,
                slot_vars=self._safe_slot_vars,
                slot_queue=self.slot_queue,
                on_progress=self._on_progress,
                on_complete=lambda **kw: self._on_complete(
                    header=header, delete=delete, **kw
                ),
                on_error=self._on_error,
                sample_rate=sample_rate,
                bit_depth=bit_depth,
                normalize_mp3=normalize_mp3,
                target_lufs=target_lufs,
            )

    def _on_progress(
        self,
        processed: int,
        total: int,
        converted: int,
        skipped: int,
        errors: int,
        display_text: str,
    ) -> None:
        self.progress["maximum"] = total
        self.progress["value"] = processed
        self.stats_label.config(
            text=f"Converted: {converted} | Skipped: {skipped} | Errors: {errors}"
        )
        self.file_listbox.insert(tk.END, display_text)
        self.file_listbox.see(tk.END)

    def _on_complete(
        self,
        header: list[str],
        delete: bool,
        total: int,
        processed: int,
        converted: int,
        skipped: int,
        errors: int,
        duration_secs: float,
        log_entries: list[str],
        output_dir: str,
    ) -> None:
        minutes = int(duration_secs // 60)
        seconds = int(duration_secs % 60)
        self._output_dir_final = output_dir
        self._out_dir = output_dir

        summary: list[str] = [
            "\n" + "=" * 60 + "\n",
            "SUMMARY:\n",
            f"Total files: {total}\n",
            f"Converted: {converted}\n",
            f"Skipped: {skipped}\n",
            f"Errors: {errors}\n",
        ]
        if delete:
            summary.append(f"Originals deleted: {converted} (successful conversions)\n")
        summary.append(f"Time: {minutes:02d}:{seconds:02d}\n")

        try:
            with open(self._log_path, "w", encoding="utf-8") as f:
                f.writelines(header + log_entries + summary)
        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("Error: %s", mapped, exc_info=True)
            messagebox.showerror(
                "Error",
                f"Could not write log file:\n{user_message_for(mapped)}",
            )

        self.time_label.config(text=f"Total Time: {minutes:02d}:{seconds:02d}")
        summary_text = (
            f"Total: {total} files\n"
            f"Converted: {converted}\n"
            f"Skipped: {skipped}\n"
            f"Errors: {errors}"
        )
        if delete:
            summary_text += f"\nOriginals Deleted: {converted}"
        self.summary_label.config(text=summary_text)
        self.completion_label.config(text="Conversion Complete!")
        self.notebook.select(self._tab_results)
        self.start_btn.config(state="normal")

    def _on_error(self, message: str) -> None:
        messagebox.showerror("Error", message)
        self.start_btn.config(state="normal")

    def _open_help(self) -> None:
        """Open the help guide for Music Format Converter."""
        self._open_help_standard(self.HELP_GUIDE)
