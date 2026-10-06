"""
app.py — AudioSuiteDriver orchestrator.

Tab layout:
  REFINE  — Audio Refinery pipeline (own source/output pickers)
  ENRICH  — Tag & metadata tools (uses shared directory bar)
  UTIL    — Utility tools + audio file tools
  SETTINGS — Settings
"""

import logging
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from typing import cast

from audio_suite_shared import platform_utils as _shared_platform_utils
from audio_suite_shared import secure_subprocess, styles, ui_common
from audio_suite_shared import suite_config as _suite_config
from audio_suite_shared.styles import set_active_palette as _set_palette
from audio_suite_shared.tool_plugin import get_registry
from audio_suite_shared.ui_helpers import UIHelperMixin

from .batch_orchestrator import DEPENDENCY_GRAPH, BatchProgress
from .runner.arg_builder import REFINERY_STAGES
from .state.app_state import AppState
from .tool_launcher import (
    _get_current_accent,
    launch_enrich,
    launch_refinery,
    launch_utility,
)
from .ui import enrich_tab, refinery_tab, settings_tab, utilities_window
from .ui_panels import build_control_strip, build_header, build_sidebar

logger = logging.getLogger(f"audio_suite.{__name__}")

_ACCENT_POLL_MS = 2000


class AudioSuiteDriver(UIHelperMixin):
    """Audio Suite Master Driver - orchestrates all tools."""

    HELP_GUIDE = "Master_Driver_User_Guide.docx"

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("Audio Suite Master Driver")
        _shared_platform_utils.setup_window(
            self.root, 1250, 950, _suite_config, "master_driver_window"
        )
        self.root.configure(bg=styles.BG_APP)

        self.state = AppState()
        self.state.dir_path.set(_suite_config.load_last_directory())

        palette_name = _suite_config.load_palette()
        theme_mode = _suite_config.load_theme_mode()
        font_family = _suite_config.load_font_family()
        font_sizes = _suite_config.load_font_sizes()

        self.state.palette_var.set(palette_name)
        self.state.theme_mode_var.set(theme_mode)
        self.state.font_family_var.set(font_family)
        for k, v in font_sizes.items():
            if k in self.state.font_sizes_vars:
                self.state.font_sizes_vars[k].set(v)

        _set_palette(palette_name)
        styles.set_theme_mode(theme_mode)
        styles.set_active_typography(font_family, font_sizes)

        self.style = ttk.Style()
        styles.apply_styles(self.style)
        self.style.configure("TCombobox", arrowcolor=styles.get_main())
        self.style.configure("TSpinbox", arrowcolor=styles.get_main())

        self._last_accent: str | None = (
            _get_current_accent() if palette_name == "Windows Accent" else None
        )

        self.root.configure(bg=styles.BG_APP)
        self._build_ui()
        self._setup_menu()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._start_accent_poll()

        self.state.palette_var.trace_add(
            "write", lambda *_: self._on_palette_var_changed()
        )

    # ── Windows Accent colour live-update ─────────────────────────────────────

    def _on_palette_var_changed(self) -> None:
        if self.state.palette_var.get() == "Windows Accent":
            self._last_accent = _get_current_accent()
            if not getattr(self, "_accent_poll_active", False):
                self._start_accent_poll()

    def _start_accent_poll(self) -> None:
        if self.state.palette_var.get() == "Windows Accent":
            self._accent_poll_active = True
            self.root.after(_ACCENT_POLL_MS, self._poll_accent)

    def _poll_accent(self) -> None:
        if not getattr(self, "_accent_poll_active", False):
            return
        if self.state.palette_var.get() != "Windows Accent":
            self._last_accent = None
            self._accent_poll_active = False
            return

        current = _get_current_accent()
        if current is not None and current != self._last_accent:
            self._last_accent = current
            self._apply_accent_refresh()

        self.root.after(_ACCENT_POLL_MS, self._poll_accent)

    def _apply_accent_refresh(self) -> None:
        _set_palette("Windows Accent")
        styles.apply_styles(self.style)
        self.style.configure("TCombobox", arrowcolor=styles.get_main())
        self.style.configure("TSpinbox", arrowcolor=styles.get_main())

        main_col = styles.get_main()

        self.root.configure(bg=styles.BG_APP)
        for widget in self.root.winfo_children():
            if isinstance(widget, tk.Frame):
                try:
                    if widget.cget("bg") not in (
                        styles.BG_APP,
                        styles.BG_WHITE,
                        styles.BG_LIGHT,
                        styles.BG_ITEM,
                        "#cccccc",
                    ):
                        widget.configure(bg=main_col)
                        for child in widget.winfo_children():
                            if isinstance(child, tk.Label):
                                child.configure(bg=main_col)
                except tk.TclError:
                    # Some widgets (e.g. ttk separators, themed frames) don't
                    # support background colour — log at DEBUG so the skip is
                    # visible when investigating theme issues, but never warn.
                    logger.debug(
                        "Widget %s does not support bg configuration",
                        type(widget).__name__,
                    )

        tab = self._active_tab
        self._btn_refine.config(
            bg=styles.tab_active() if tab == "refine" else styles.tab_inactive()
        )
        self._btn_enrich.config(
            bg=styles.tab_active() if tab == "enrich" else styles.tab_inactive()
        )
        self._btn_util.config(
            bg=styles.tab_active() if tab == "util" else styles.tab_inactive()
        )
        self._btn_settings.config(
            bg=(
                styles.SETTINGS_TAB_ACTIVE
                if tab == "settings"
                else styles.SETTINGS_TAB_INACTIVE
            )
        )

        for child in self._dir_frame.winfo_children():
            if isinstance(child, tk.Button):
                child.configure(bg=main_col)

    # ── App lifecycle ─────────────────────────────────────────────────────────

    def _on_close(self) -> None:
        _suite_config.save_app_state(self.state)
        self.root.destroy()

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        build_header(self.root, "AUDIO SUITE MASTER DRIVER")

        body = tk.Frame(self.root, bg=styles.BG_APP)
        body.pack(fill="both", expand=True)

        sidebar_btns = build_sidebar(body, self._switch_tab)
        self._btn_refine = sidebar_btns["refine"]
        self._btn_enrich = sidebar_btns["enrich"]
        self._btn_util = sidebar_btns["util"]
        self._btn_settings = sidebar_btns["settings"]

        right = tk.Frame(body, bg=styles.BG_APP)
        right.pack(side="left", fill="both", expand=True)

        self._dir_frame = tk.Frame(right, bg=styles.BG_WHITE, padx=20, pady=10)
        self._dir_frame.pack(fill="x")
        dir_entry = tk.Entry(
            self._dir_frame,
            textvariable=self.state.dir_path,
            font=styles.FONT_LABEL,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        )
        dir_entry.pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 10))
        tk.Button(
            self._dir_frame,
            text="Browse Folder",
            command=self._browse,
            font=styles.FONT_BUTTON,
            bg=styles.get_main(),
            fg="white",
        ).pack(side=tk.RIGHT)

        dir_entry.bind(
            "<FocusOut>",
            lambda e: (
                utilities_window.update_format_detection(self.state)
                if self.state.converter_toggle.get()
                else None
            ),
        )
        dir_entry.bind(
            "<Return>",
            lambda e: (
                utilities_window.update_format_detection(self.state)
                if self.state.converter_toggle.get()
                else None
            ),
        )

        self._ctrl_frame = tk.Frame(right, bg=styles.BG_APP, padx=20, pady=5)
        self._ctrl_frame.pack(fill="x")
        ctrl_widgets = build_control_strip(self._ctrl_frame, self.state)
        self._select_all_btn = cast(tk.Checkbutton, ctrl_widgets["select_all"])
        self._mode_combo = cast(ttk.Combobox, ctrl_widgets["mode_combo"])
        self._auto_start_btn = cast(tk.Checkbutton, ctrl_widgets["auto_start"])
        self._auto_end_btn = cast(tk.Checkbutton, ctrl_widgets["auto_end"])
        self._clear_logs_btn = cast(tk.Checkbutton, ctrl_widgets["clear_logs"])
        self._parallel_btn = cast(tk.Checkbutton, ctrl_widgets["parallel"])
        self._batch_status_text = cast(tk.Text, ctrl_widgets["batch_status_text"])
        self._batch_eta_label = cast(tk.Label, ctrl_widgets["batch_eta_label"])
        self._batch_progress_bar = cast(
            ttk.Progressbar, ctrl_widgets["batch_progress_bar"]
        )

        self._ctrl_rule = tk.Frame(right, bg="#cccccc", height=1)
        self._ctrl_rule.pack(fill="x", padx=20)

        self._frame_refine = tk.Frame(right, bg=styles.BG_APP)
        self._frame_enrich = tk.Frame(right, bg=styles.BG_APP)
        self._frame_util = tk.Frame(right, bg=styles.BG_APP)
        self._frame_settings = tk.Frame(right, bg=styles.BG_LIGHT)

        self.refine_btn, self._refinery_config, self._refinery_setup_state = (
            refinery_tab.build(
                self._frame_refine,
                self.state,
                on_run=self._start_refinery_thread,
                on_open_refinery=self._open_refinery_ui,
            )
        )
        self.run_btn = enrich_tab.build(
            self._frame_enrich, self.state, on_run=self._start_enrich_thread
        )
        self.util_run_btn = utilities_window.build(
            self._frame_util,
            self.state,
            on_run=self._start_utility_thread,
            on_open_undo=self._open_undo_ui,
        )
        settings_tab.build(self._frame_settings, self.state)

        self._active_tab: str | None = None
        self._switch_tab("refine")

    # ── Tab switching ─────────────────────────────────────────────────────────

    def _switch_tab(self, tab: str) -> None:
        if tab == self._active_tab:
            return

        if self._active_tab == "refine":
            src = self.state.refinery_source.get().strip()
            if src:
                self.state.dir_path.set(src)
        if tab == "refine":
            main_dir = self.state.dir_path.get().strip()
            if main_dir:
                self.state.refinery_source.set(main_dir)

        self._active_tab = tab

        for frame in (
            self._frame_refine,
            self._frame_enrich,
            self._frame_util,
            self._frame_settings,
        ):
            frame.pack_forget()
        self._dir_frame.pack_forget()
        self._ctrl_frame.pack_forget()
        self._ctrl_rule.pack_forget()

        show_shared = tab in ("enrich", "util", "refine")
        if show_shared:
            if tab in ("enrich", "util"):
                self._dir_frame.pack(fill="x")
                self._ctrl_frame.pack(fill="x")
                self._ctrl_rule.pack(fill="x", padx=20)

        if tab == "refine":
            self._frame_refine.pack(fill="both", expand=True)
        elif tab == "enrich":
            self._frame_enrich.pack(fill="both", expand=True)
        elif tab == "util":
            self._frame_util.pack(fill="both", expand=True)
        else:
            self._frame_settings.pack(fill="both", expand=True)

        self._btn_refine.config(
            bg=styles.tab_active() if tab == "refine" else styles.tab_inactive()
        )
        self._btn_enrich.config(
            bg=styles.tab_active() if tab == "enrich" else styles.tab_inactive()
        )
        self._btn_util.config(
            bg=styles.tab_active() if tab == "util" else styles.tab_inactive()
        )
        self._btn_settings.config(
            bg=(
                styles.SETTINGS_TAB_ACTIVE
                if tab == "settings"
                else styles.SETTINGS_TAB_INACTIVE
            )
        )

        select_var = mode_var = start_var = end_var = logs_var = parallel_var = None
        _toggle_all = None

        if tab == "enrich":
            select_var = self.state.select_all_var
            mode_var = self.state.global_mode
            start_var = self.state.auto_start
            end_var = self.state.auto_end
            logs_var = self.state.clear_logs_var
            parallel_var = self.state.parallel_var

            def _toggle_all() -> None:
                v = self.state.select_all_var.get()
                for var in self.state.module_toggles.values():
                    if var.get() != v:
                        var.set(v)

        elif tab == "refine":
            select_var = self.state.refinery_select_all_var
            mode_var = self.state.global_mode
            start_var = self.state.refinery_auto_start
            end_var = self.state.refinery_auto_end
            logs_var = self.state.clear_logs_var

            def _toggle_all() -> None:
                v = self.state.refinery_select_all_var.get()
                if (
                    hasattr(self, "_refinery_setup_state")
                    and self._refinery_setup_state
                ):
                    stage_vars = self._refinery_setup_state.get("stage_vars", {})
                    # Same source the arg builder emits (audit M12a), so
                    # select-all can never omit a stage the pipeline runs.
                    for _field, stage_name in REFINERY_STAGES:
                        if stage_name in stage_vars:
                            if stage_vars[stage_name].get() != v:
                                stage_vars[stage_name].set(v)

        elif tab == "util":
            select_var = self.state.util_select_all_var
            mode_var = self.state.util_global_mode
            start_var = self.state.util_auto_start
            end_var = self.state.util_auto_end
            logs_var = self.state.util_clear_logs_var

            def _toggle_all() -> None:
                self._apply_util_select_all(self.state.util_select_all_var.get())

        if show_shared:
            self._select_all_btn.config(
                variable=cast(tk.Variable, select_var), command=_toggle_all
            )
            self._mode_combo.grid()
            self._mode_combo.config(textvariable=cast(tk.StringVar, mode_var))
            self._auto_start_btn.config(variable=cast(tk.Variable, start_var))
            self._auto_end_btn.config(variable=cast(tk.Variable, end_var))
            self._clear_logs_btn.config(variable=cast(tk.Variable, logs_var))
            if parallel_var is not None:
                self._parallel_btn.config(variable=parallel_var)
                self._parallel_btn.grid()
            else:
                self._parallel_btn.grid_remove()

    # ── Select-all helper ────────────────────────────────────────────────────

    def _apply_util_select_all(self, v: bool) -> None:
        """Toggle every batch-togglable utility module checkbox to *v*.

        The utility list is derived from the ToolRegistry (single source of
        truth) so a newly registered utility tool is picked up automatically.
        ``undo_tag_edits`` is excluded — its card has no module checkbox, it
        is opened on demand and never part of a batch run.

        Args:
            v: The value to assign to each utility module toggle.
        """
        for manifest in get_registry().by_category("utility"):
            if manifest.id == "undo_tag_edits":
                continue
            toggle = self.state.module_toggles[manifest.id]
            if toggle.get() != v:
                toggle.set(v)
        if v:
            utilities_window.update_format_detection(self.state)

    # ── Menu ──────────────────────────────────────────────────────────────────

    def _setup_menu(self) -> None:
        menubar = tk.Menu(self.root, font=styles.FONT_BODY)
        self.root.config(menu=menubar)
        help_menu = tk.Menu(menubar, tearoff=0, font=styles.FONT_BODY)
        menubar.add_cascade(label="Help", menu=help_menu)
        help_menu.add_command(label="User Guide", command=self._open_help)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self._show_about)

    # ── User actions ──────────────────────────────────────────────────────────

    def _browse(self) -> None:
        from audio_suite_shared.security.input_validator import InputValidator

        folder = filedialog.askdirectory(initialdir=self.state.dir_path.get() or "")
        if folder and InputValidator.validate_directory_path(folder):
            self.state.dir_path.set(folder)
            _suite_config.save_last_directory(folder)
            if self.state.converter_toggle.get():
                utilities_window.update_format_detection(self.state)
        elif folder:
            messagebox.showwarning(
                "Invalid Path", "Selected folder path is invalid or potentially unsafe."
            )

    def _open_help(self) -> None:
        self._open_help_standard(self.HELP_GUIDE)

    def _open_refinery_ui(self) -> None:

        root_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        script = os.path.join(root_dir, "Audio_Refinery.pyw")
        if os.path.exists(script):
            secure_subprocess.start_python_script(script, [])
        else:
            messagebox.showwarning(
                "Not Found", f"Audio_Refinery.pyw not found at:\n{script}"
            )

    def _open_undo_ui(self) -> None:
        """Open the Undo Tag Edits window (non-blocking standalone tool)."""
        root_dir = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
        script = os.path.join(root_dir, "Undo_Tag_Edits.pyw")
        if os.path.exists(script):
            secure_subprocess.start_python_script(script, [])
        else:
            messagebox.showwarning(
                "Not Found", f"Undo_Tag_Edits.pyw not found at:\n{script}"
            )

    def _show_about(self) -> None:
        ui_common.show_message(
            self.root,
            "About",
            "Audio Suite Master Driver\n"
            "Enhanced with Album Genre Tools\n\n"
            "Streamlined workflow automation for audio processing",
        )

    # ── Batch progress UI update ──────────────────────────────────────────────

    def _update_batch_progress(self, progress: BatchProgress) -> None:
        """Update the per-step status text, overall summary, and progress bar."""

        def _update() -> None:
            if progress.total_steps == 0:
                self._batch_status_text.grid_remove()
                self._batch_eta_label.grid_remove()
                self._batch_progress_bar.grid_remove()
                return

            total = progress.total_steps
            completed = progress.completed_steps
            elapsed_str = str(progress.elapsed).split(".")[0]
            eta_str = str(progress.estimated_remaining).split(".")[0]

            # ── Build per-step status lines ──────────────────────────────────
            status_chars = {
                "completed": "\u2713",  # ✓
                "running": "\u25b6",  # ▶
                "failed": "\u2717",  # ✗
                "pending": "\u23f3",  # ⏳
                "waiting": "\u23f3",  # ⏳
                "skipped": "\u2014",  # —
            }
            lines: list[str] = []
            running_count = 0
            for i, (tid, name, st) in enumerate(progress.steps):
                icon = status_chars.get(st, "?")
                if st == "running":
                    running_count += 1
                    lines.append(
                        f"[{i + 1}/{total}] {name:<25s} {icon} running  ({elapsed_str})"
                    )
                elif st == "completed":
                    lines.append(f"[{i + 1}/{total}] {name:<25s} {icon} completed")
                elif st == "failed":
                    lines.append(f"[{i + 1}/{total}] {name:<25s} {icon} FAILED")
                elif st == "waiting":
                    deps = DEPENDENCY_GRAPH.get(tid, [])
                    dep_str = ", ".join(deps) if deps else "dependencies"
                    lines.append(
                        f"[{i + 1}/{total}] {name:<25s} {icon} waiting for {dep_str}"
                    )
                elif st == "skipped":
                    lines.append(f"[{i + 1}/{total}] {name:<25s} {icon} skipped")
                else:
                    lines.append(f"[PENDING] {name:<25s} {icon} pending")

            # ── Overall summary ──────────────────────────────────────────────
            failed_count = len(progress.failed_steps)
            running_str = f" · {running_count} running" if running_count > 0 else ""
            summary = f"Overall: {completed}/{total} completed{running_str}"
            if failed_count:
                summary += f" · {failed_count} failed"
            summary += f" · Elapsed: {elapsed_str} · ETA: {eta_str}"

            # ── Update widgets ───────────────────────────────────────────────
            self._batch_status_text.config(state="normal")
            self._batch_status_text.delete("1.0", "end")
            self._batch_status_text.insert("1.0", "\n".join(lines) + "\n")
            self._batch_status_text.config(state="disabled")
            self._batch_status_text.grid()

            self._batch_eta_label.config(text=summary)
            self._batch_eta_label.grid()

            pct = int(progress.current_progress * 100)
            self._batch_progress_bar.config(value=pct)
            self._batch_progress_bar.grid()

        self.root.after(0, _update)

    def _hide_batch_progress(self) -> None:
        """Hide batch progress widgets after completion."""

        def _hide() -> None:
            self._batch_status_text.grid_remove()
            self._batch_eta_label.grid_remove()
            self._batch_progress_bar.grid_remove()

        self.root.after(500, _hide)

    # ── Processing entry points (delegate to tool_launcher) ───────────────────

    def _start_refinery_thread(self) -> None:
        launch_refinery(self.state, self._refinery_config, self.refine_btn, self.root)

    def _start_enrich_thread(self) -> None:
        launch_enrich(
            self.state,
            self.run_btn,
            self.root,
            progress_callback=self._update_batch_progress,
            on_batch_done=self._hide_batch_progress,
        )

    def _start_utility_thread(self) -> None:
        launch_utility(
            self.state,
            self.util_run_btn,
            self.root,
            progress_callback=self._update_batch_progress,
            on_batch_done=self._hide_batch_progress,
        )
