"""
Tkinter GUI for Tag-Based File Reorganizer.

Provides two pattern fields (Specific Artists / Various Artists),
source and destination directory selection, action radio buttons,
and a Preview/Execute workflow.  Styled to match AudioSuite-Pro
look and feel.

Changed in 1.0.1: accepts the driver's argv as kwargs and pre-fills the source,
destination, action and pattern widgets.
"""

from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from audio_suite_shared import styles, suite_config, ui_common
from audio_suite_shared.app_bootstrap import BaseSuiteApp
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.exceptions import AudioSuiteError, handle_audio_errors
from audio_suite_shared.launcher import parse_cli_args
from audio_suite_shared.ui_helpers import show_error_from_exception

from .core.defaults import DEFAULT_SPECIFIC, DEFAULT_VARIOUS
from .core.engine import FileReorganizer, ReorganizerStats
from .utils import cli_args
from .utils.config import load_settings, save_settings


class FileReorganizerApp(BaseSuiteApp):
    """Tkinter GUI application for Tag-Based File Reorganizer."""

    _TOOL_ID = "file_reorganizer"

    def __init__(
        self,
        root: tk.Tk,
        *,
        directory: str = "",
        output_dir: str = "",
        action: str = "",
        specific_pattern: str = "",
        various_pattern: str = "",
    ) -> None:
        super().__init__(
            root,
            "Tag-Based File Reorganizer",
            "file_reorganizer_window",
            "file_reorganizer",
        )

        self.source_dir = tk.StringVar()
        self.dest_dir = tk.StringVar()
        self.action = tk.StringVar(value="copy")
        self.dry_run = tk.BooleanVar(value=True)
        self.running = tk.BooleanVar(value=False)

        self._preset_combo: "ttk.Combobox | None" = None
        self._refresh_preset_list: "Callable[..., Any] | None" = None

        self.stats = ReorganizerStats()
        self.files_scanned = tk.IntVar(value=0)
        self.files_processed = tk.IntVar(value=0)
        self.files_skipped = tk.IntVar(value=0)
        self.errors = tk.IntVar(value=0)
        self.current_file = tk.StringVar()

        self.setup_ui()
        self._load_settings()
        self._seed_source_from_last_directory()
        self._apply_cli_args(
            directory=directory,
            output_dir=output_dir,
            action=action,
            specific_pattern=specific_pattern,
            various_pattern=various_pattern,
        )
        self._reorganizer: FileReorganizer | None = None
        self._thread: threading.Thread | None = None
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def setup_ui(self) -> None:
        frame = tk.Frame(self.root, padx=30, pady=30, bg=styles.BG_WHITE)
        frame.pack(expand=True, fill="both")

        tk.Label(
            frame,
            text="Tag-Based File Reorganizer",
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=(0, 20))

        # ── Presets ───────────────────────────────────────────────────────────────
        self._preset_combo = ttk.Combobox(
            frame,
            state="readonly",
            font=styles.FONT_BODY,
            width=28,
        )
        self._preset_combo["values"] = suite_config.list_presets(self._TOOL_ID) or []
        self._preset_combo.pack(anchor="w", pady=(0, 8))

        def _refresh_preset_list(names: list[str]) -> None:
            assert self._preset_combo is not None
            self._preset_combo["values"] = names

        self._refresh_preset_list = _refresh_preset_list

        def _on_preset_select(_event: tk.Event[ttk.Combobox] | None = None) -> None:
            assert self._preset_combo is not None
            name = self._preset_combo.get()
            if name:
                settings = suite_config.load_preset(self._TOOL_ID, name)
                if settings:
                    self._apply_preset(settings)

        self._preset_combo.bind("<<ComboboxSelected>>", _on_preset_select)

        btn_row_presets = tk.Frame(frame, bg=styles.BG_WHITE)
        btn_row_presets.pack(fill="x", pady=(0, 10), anchor="w")
        tk.Button(
            btn_row_presets,
            text="Save Preset",
            command=self._save_preset_dialog,
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BODY,
            padx=8,
        ).pack(side=tk.LEFT, padx=(0, 5))
        tk.Button(
            btn_row_presets,
            text="Delete Preset",
            command=self._delete_preset_action,
            bg="#cc5555",
            fg="white",
            font=styles.FONT_BODY,
            padx=8,
        ).pack(side=tk.LEFT)

        # ── Directories ──
        dir_frame = tk.Frame(frame, bg=styles.BG_WHITE)
        dir_frame.pack(fill="x", pady=5)

        ui_common.path_row(
            dir_frame, "Source Directory:", self.source_dir, self._browse_source
        )

        dest_frame = tk.Frame(frame, bg=styles.BG_WHITE)
        dest_frame.pack(fill="x", pady=5)
        ui_common.path_row(
            dest_frame, "Destination Directory:", self.dest_dir, self._browse_dest
        )

        # ── Action ──
        action_frame = tk.LabelFrame(
            frame,
            text=" Action ",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            padx=15,
            pady=10,
        )
        action_frame.pack(fill="x", pady=(15, 5))

        tk.Radiobutton(
            action_frame,
            text="Copy",
            variable=self.action,
            value="copy",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT, padx=(0, 15))

        tk.Radiobutton(
            action_frame,
            text="Move",
            variable=self.action,
            value="move",
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT, padx=(0, 15))

        tk.Checkbutton(
            action_frame,
            text="Dry Run (Preview only)",
            variable=self.dry_run,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(side=tk.LEFT)

        # ── Pattern notebook ──
        pattern_frame = tk.LabelFrame(
            frame,
            text=" Pattern Templates ",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            padx=15,
            pady=10,
        )
        pattern_frame.pack(fill="both", expand=True, pady=(10, 5))

        notebook = ttk.Notebook(pattern_frame)
        notebook.pack(fill="both", expand=True)

        specific_frame = tk.Frame(notebook, bg=styles.BG_WHITE)
        various_frame = tk.Frame(notebook, bg=styles.BG_WHITE)
        notebook.add(specific_frame, text="  Specific Artists  ")
        notebook.add(various_frame, text="  Various Artists  ")

        self.specific_text = tk.Text(
            specific_frame,
            height=10,
            width=90,
            wrap=tk.NONE,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
            highlightthickness=1,
            highlightcolor=styles.FG_SUB,
            relief=tk.SOLID,
            borderwidth=1,
        )
        self.specific_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.specific_text.insert("1.0", DEFAULT_SPECIFIC)

        self.various_text = tk.Text(
            various_frame,
            height=10,
            width=90,
            wrap=tk.NONE,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
            highlightthickness=1,
            highlightcolor=styles.FG_SUB,
            relief=tk.SOLID,
            borderwidth=1,
        )
        self.various_text.pack(fill="both", expand=True, padx=5, pady=5)
        self.various_text.insert("1.0", DEFAULT_VARIOUS)

        # ── Progress ──
        progress_frame = tk.LabelFrame(
            frame,
            text=" Progress ",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            padx=15,
            pady=10,
        )
        progress_frame.pack(fill="x", pady=(5, 5))

        cur_frame = tk.Frame(progress_frame, bg=styles.BG_WHITE)
        cur_frame.pack(fill="x")
        tk.Label(
            cur_frame,
            text="Current File:",
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
        ).pack(side=tk.LEFT)
        tk.Label(
            cur_frame,
            textvariable=self.current_file,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
        ).pack(side=tk.LEFT, padx=5)

        stats_row = tk.Frame(progress_frame, bg=styles.BG_WHITE)
        stats_row.pack(fill="x", pady=(5, 0))
        for label, var in [
            ("Scanned:", self.files_scanned),
            ("Processed:", self.files_processed),
            ("Skipped:", self.files_skipped),
            ("Errors:", self.errors),
        ]:
            tk.Label(
                stats_row,
                text=label,
                font=styles.FONT_CAPTION,
                bg=styles.BG_WHITE,
                fg=styles.FG_SUB,
            ).pack(side=tk.LEFT, padx=(0, 2))
            tk.Label(
                stats_row,
                textvariable=var,
                font=styles.FONT_CAPTION_B,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
                width=5,
                anchor="w",
            ).pack(side=tk.LEFT, padx=(0, 12))

        # ── Preview listbox ──
        preview_frame = tk.LabelFrame(
            frame,
            text=" Preview ",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            padx=15,
            pady=10,
        )
        preview_frame.pack(fill="both", expand=True, pady=(5, 10))

        scrollbar = tk.Scrollbar(preview_frame, orient=tk.VERTICAL)
        self.preview_list = tk.Listbox(
            preview_frame,
            height=6,
            yscrollcommand=scrollbar.set,
            font=styles.FONT_MONO,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            highlightthickness=0,
            borderwidth=1,
            relief=tk.SOLID,
        )
        scrollbar.config(command=self.preview_list.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.preview_list.pack(fill="both", expand=True)

        # ── Buttons ──
        btn_row = tk.Frame(frame, bg=styles.BG_WHITE)
        btn_row.pack(fill="x", pady=(0, 5))

        self.preview_btn = tk.Button(
            btn_row,
            text="Preview",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self._preview,
        )
        self.preview_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.execute_btn = tk.Button(
            btn_row,
            text="Execute",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self._execute,
            state=tk.DISABLED,
        )
        self.execute_btn.pack(side=tk.LEFT, padx=(0, 8))

        self.stop_btn = tk.Button(
            btn_row,
            text="Stop",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self._stop,
            state=tk.DISABLED,
        )
        self.stop_btn.pack(side=tk.LEFT)

        self.status_var = tk.StringVar(value="Ready")
        status_bar = tk.Label(
            self.root,
            textvariable=self.status_var,
            font=styles.FONT_CAPTION,
            bg=styles.BG_LIGHT,
            fg=styles.FG_SUB,
            anchor="w",
            padx=10,
        )
        status_bar.pack(fill="x", padx=30, pady=(0, 10))

    # ── Presets ───────────────────────────────────────────────────────────────

    def _collect_settings(self) -> dict[str, Any]:
        specific, various = self._sync_patterns()
        return {
            "source_dir": self.source_dir.get(),
            "dest_dir": self.dest_dir.get(),
            "action": self.action.get(),
            "dry_run": self.dry_run.get(),
            "specific_pattern": specific,
            "various_pattern": various,
        }

    def _apply_preset(self, settings: dict[str, Any]) -> None:
        if "source_dir" in settings:
            self.source_dir.set(settings["source_dir"])
        if "dest_dir" in settings:
            self.dest_dir.set(settings["dest_dir"])
        if "action" in settings:
            self.action.set(settings["action"])
        if "dry_run" in settings:
            self.dry_run.set(settings["dry_run"])
        if "specific_pattern" in settings:
            self.specific_text.delete("1.0", tk.END)
            self.specific_text.insert("1.0", settings["specific_pattern"])
        if "various_pattern" in settings:
            self.various_text.delete("1.0", tk.END)
            self.various_text.insert("1.0", settings["various_pattern"])

    def _save_preset_dialog(self) -> None:
        dialog = tk.Toplevel(self.root)
        dialog.title("Save Preset")
        dialog.geometry("350x150+400+300")
        dialog.transient()
        dialog.grab_set()
        tk.Label(dialog, text="Preset Name:", font=styles.FONT_BODY).pack(pady=(15, 5))
        name_var = tk.StringVar()
        entry = tk.Entry(dialog, textvariable=name_var, font=styles.FONT_BODY, width=40)
        entry.pack(padx=20, pady=5)
        entry.focus_set()

        def _do_save() -> None:
            name = name_var.get().strip()
            if name:
                suite_config.save_preset(self._TOOL_ID, name, self._collect_settings())
                assert self._preset_combo is not None
                self._preset_combo.set(name)
                if self._refresh_preset_list:
                    self._refresh_preset_list(suite_config.list_presets(self._TOOL_ID))
            dialog.destroy()

        entry.bind("<Return>", lambda e: _do_save())
        tk.Button(
            dialog,
            text="Save",
            command=_do_save,
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
        ).pack(pady=10)

    def _delete_preset_action(self) -> None:
        assert self._preset_combo is not None
        name = self._preset_combo.get()
        if name:
            if messagebox.askyesno("Delete Preset", f'Delete preset "{name}"?'):
                suite_config.delete_preset(self._TOOL_ID, name)
                self._preset_combo.set("")
                if self._refresh_preset_list:
                    self._refresh_preset_list(suite_config.list_presets(self._TOOL_ID))

    def _seed_source_from_last_directory(self) -> None:
        """Set the source directory from the suite-wide last-used folder.

        The source field always follows ``suite_config.load_last_directory``
        at launch: the Master Driver saves its selected folder there before
        launching standalone tools, and this tool updates it whenever a new
        source is picked.  It therefore wins over any locally persisted
        settings, matching sibling-tool behaviour.
        """
        last = suite_config.load_last_directory()
        if last:
            self.source_dir.set(last)

    def _apply_cli_args(
        self,
        *,
        directory: str,
        output_dir: str,
        action: str,
        specific_pattern: str,
        various_pattern: str,
    ) -> None:
        """Pre-fill widgets from the Master Driver / CLI arguments.

        The driver's source directory wins over the suite-wide last-used
        directory seeded just before this call, matching sibling-tool
        behaviour.

        Args:
            directory: Source music directory from argv[1].
            output_dir: Destination directory from ``--output-dir``.
            action: ``copy`` or ``move`` from ``--action``.
            specific_pattern: Pattern template from ``--specific-pattern``.
            various_pattern: Pattern template from ``--various-pattern``.
        """
        if directory:
            self.source_dir.set(directory)
        if output_dir:
            self.dest_dir.set(output_dir)
        if action in ("copy", "move"):
            self.action.set(action)
        if specific_pattern:
            self.specific_text.delete("1.0", tk.END)
            self.specific_text.insert("1.0", specific_pattern)
        if various_pattern:
            self.various_text.delete("1.0", tk.END)
            self.various_text.insert("1.0", various_pattern)

    def _browse_source(self) -> None:
        d = filedialog.askdirectory(title="Select Source Directory")
        if d:
            self.source_dir.set(d)
            suite_config.save_last_directory(d)

    def _browse_dest(self) -> None:
        d = filedialog.askdirectory(title="Select Destination Directory")
        if d:
            self.dest_dir.set(d)

    def _sync_patterns(self) -> tuple[str, str]:
        return self.specific_text.get("1.0", "end-1c"), self.various_text.get(
            "1.0", "end-1c"
        )

    @handle_audio_errors(reraise=False, context="file_reorganizer_save_settings")
    def _save_settings(self) -> None:
        save_settings(
            dest_dir=self.dest_dir.get(),
            action=self.action.get(),
            specific_pattern=self.specific_text.get("1.0", "end-1c"),
            various_pattern=self.various_text.get("1.0", "end-1c"),
        )

    @handle_audio_errors(reraise=False, context="file_reorganizer_load_settings")
    def _load_settings(self) -> None:
        settings = load_settings()
        self.dest_dir.set(settings["dest_dir"])
        self.action.set(settings["action"])
        specific = settings["specific_pattern"]
        various = settings["various_pattern"]
        self.specific_text.delete("1.0", tk.END)
        self.specific_text.insert("1.0", specific)
        self.various_text.delete("1.0", tk.END)
        self.various_text.insert("1.0", various)

    def _preview(self) -> None:
        src = self.source_dir.get().strip()
        dst = self.dest_dir.get().strip()
        if not src or not os.path.isdir(src):
            ui_common.show_message(
                self.root, "No Source", "Please select a valid source directory."
            )
            return
        if not dst:
            ui_common.show_message(
                self.root, "No Destination", "Please select a destination directory."
            )
            return

        specific_pat, various_pat = self._sync_patterns()
        self.preview_list.delete(0, tk.END)
        self.status_var.set("Previewing...")
        self.preview_btn.config(state=tk.DISABLED)
        self._save_settings()

        self._thread = threading.Thread(
            target=self._preview_thread, args=(src, dst, specific_pat, various_pat)
        )
        self._thread.daemon = True
        self._thread.start()

    def _preview_thread(
        self, src: str, dst: str, specific_pat: str, various_pat: str
    ) -> None:
        try:
            self._preview_run(src, dst, specific_pat, various_pat)
        except AudioSuiteError as exc:
            error = exc
            self.root.after(
                0,
                lambda: show_error_from_exception(error, title="Preview Error"),
            )
        finally:
            self.root.after(0, lambda: self.status_var.set("Preview complete"))
            self.root.after(0, lambda: self.execute_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: self.preview_btn.config(state=tk.NORMAL))
            self.root.after(0, lambda: setattr(self, "_thread", None))

    @handle_audio_errors(reraise=True, context="file_reorganizer_preview")
    def _preview_run(
        self, src: str, dst: str, specific_pat: str, various_pat: str
    ) -> None:
        reorganizer = FileReorganizer(
            specific_pat, various_pat, dst, action="copy", dry_run=True
        )
        self._reorganizer = reorganizer
        reorganizer.run(src, progress_callback=self._on_progress_preview)

    def _on_progress_preview(self, path_info: str, stats: ReorganizerStats) -> None:
        self.root.after(0, self._update_ui, path_info, stats)

    def _execute(self) -> None:
        src = self.source_dir.get().strip()
        dst = self.dest_dir.get().strip()
        if not src or not os.path.isdir(src):
            ui_common.show_message(
                self.root, "No Source", "Please select a valid source directory."
            )
            return
        if not dst:
            ui_common.show_message(
                self.root, "No Destination", "Please select a destination directory."
            )
            return

        specific_pat, various_pat = self._sync_patterns()
        self.running.set(True)
        self.preview_btn.config(state=tk.DISABLED)
        self.execute_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.preview_list.delete(0, tk.END)
        self.status_var.set("Executing...")
        self._save_settings()

        self._thread = threading.Thread(
            target=self._execute_thread, args=(src, dst, specific_pat, various_pat)
        )
        self._thread.daemon = True
        self._thread.start()

    def _execute_thread(
        self, src: str, dst: str, specific_pat: str, various_pat: str
    ) -> None:
        try:
            self._execute_run(src, dst, specific_pat, various_pat)
        except AudioSuiteError as exc:
            error = exc
            self.root.after(
                0,
                lambda: show_error_from_exception(error, title="Execute Error"),
            )
        finally:
            self.root.after(0, self._finish)

    @handle_audio_errors(reraise=True, context="file_reorganizer_execute")
    def _execute_run(
        self, src: str, dst: str, specific_pat: str, various_pat: str
    ) -> None:
        dry = self.dry_run.get()
        reorganizer = FileReorganizer(
            specific_pat, various_pat, dst, action=self.action.get(), dry_run=dry
        )
        self._reorganizer = reorganizer
        with active_batch("file_reorganizer", "file_reorg"):
            reorganizer.run(src, progress_callback=self._on_progress_execute)

    def _on_progress_execute(self, path_info: str, stats: ReorganizerStats) -> None:
        self.root.after(0, self._update_ui, path_info, stats)

    def _update_ui(self, path_info: str, stats: ReorganizerStats) -> None:
        self.current_file.set(os.path.basename(path_info))
        self.files_scanned.set(stats.files_scanned)
        self.files_processed.set(stats.files_processed)
        self.files_skipped.set(stats.files_skipped)
        self.errors.set(stats.errors)
        self.preview_list.insert(tk.END, path_info)
        self.preview_list.see(tk.END)

    def _stop(self) -> None:
        self.status_var.set("Stopping...")
        if self._reorganizer is not None:
            self._reorganizer.stop()

    def _on_close(self) -> None:
        self._save_settings()
        if self._reorganizer is not None:
            self._reorganizer.stop()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self.root.destroy()

    def _finish(self) -> None:
        self.running.set(False)
        self.preview_btn.config(state=tk.NORMAL)
        self.execute_btn.config(state=tk.NORMAL)
        self.stop_btn.config(state=tk.DISABLED)
        self.status_var.set("Complete")
        ui_common.show_message(
            self.root,
            "Complete",
            f"Scanned: {self.files_scanned.get()}\n"
            f"Processed: {self.files_processed.get()}\n"
            f"Skipped: {self.files_skipped.get()}\n"
            f"Errors: {self.errors.get()}",
        )

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    args = parse_cli_args(cli_args.parse)
    root = tk.Tk()
    app = FileReorganizerApp(
        root,
        directory=args.folder_path,
        output_dir=args.output_dir,
        action=args.action,
        specific_pattern=args.specific_pattern,
        various_pattern=args.various_pattern,
    )
    app.run()
