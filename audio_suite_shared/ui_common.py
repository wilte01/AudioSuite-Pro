"""
ui_common.py — Shared tab builders for Audio Suite tools.

Provides the standard Results, Processing, and Setup tab layouts used
across most tools, plus shared preset-management helpers. Tools with unique
requirements (ASX Extractor, ReplayGain, Album Art Sync) keep their own tab
implementations.

Usage in a tool's results_tab.py:
    from audio_suite_shared.ui_common import build_results_tab

    def build(parent, on_open_log, on_open_folder):
        return build_results_tab(
            parent, "BPM Analysis Complete!", on_open_log, on_open_folder)

Usage in a tool's processing_tab.py:
    from audio_suite_shared.ui_common import build_processing_tab

    def build(parent, slot_vars):
        return build_processing_tab(parent, slot_vars)
"""

import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, Optional, cast

from . import styles
from .exceptions import AudioConfigurationError
from .secure_subprocess import SubprocessSecurityError, run_secure_subprocess
from .ui_audition import add_audition_buttons
from .ui_driver_controls import DriverControlsPanel

_log = logging.getLogger(f"audio_suite.{__name__}")


def _default_open_log() -> None:
    """Default handler to open the latest suite log file."""
    try:
        suite_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        log_file = os.path.join(suite_root, "logs", "audio_suite.log")
        if os.path.exists(log_file):
            if sys.platform == "win32":
                os.startfile(log_file)
            elif sys.platform == "darwin":
                run_secure_subprocess(
                    "open", [log_file], capture_output=True, check=False
                )
            else:
                run_secure_subprocess(
                    "xdg-open", [log_file], capture_output=True, check=False
                )
    except (OSError, SubprocessSecurityError, tk.TclError) as _exc:
        _log.warning("Swallowed exception: %s", _exc, exc_info=True)


def build_results_tab(
    parent: tk.Frame,
    completion_text: str,
    on_open_log: Optional[Callable[[], None]] = None,
    on_open_folder: Optional[Callable[[], None]] = None,
    log_btn_text: str = "View Log",
    extra_labels: list[str] | None = None,
    on_play_original: Optional[Callable[[], None]] = None,
    on_play_result: Optional[Callable[[], None]] = None,
) -> dict[str, Any]:
    """
    Build the standard Results tab layout.

    Args:
        parent:          The notebook tab frame.
        completion_text: Bold heading shown on completion.
        on_open_log:     Callback for the View Log button
                         (defaults to opening suite log).
        on_open_folder:  Callback for the Open Folder button.
        log_btn_text:    Override the log button label (default "View Log").
        extra_labels:    Optional list of extra tk.Label keys to create,
                         pack below summary_label, and return in the dict.
                         e.g. ['genre_label']
        on_play_original: Optional callback for the "Play Original" audition
                         button.  When provided (along with on_play_result) a
                         before/after audition row is added to the results tab.
        on_play_result:   Optional callback for the "Play Result" audition
                         button.  Only wired if on_play_original is also set.

    Returns:
        {
            'completion_label': tk.Label,
            'time_label':       tk.Label,
            'summary_label':    tk.Label,
            <extra keys>:       tk.Label,  # if requested
            'play_original_btn': tk.Button,   # if on_play_original set
            'play_result_btn':   tk.Button,   # if on_play_original set
            'audition_caption_var': tk.StringVar,
        }
    """
    if on_open_log is None:
        on_open_log = _default_open_log

    if on_open_folder is None:
        on_open_folder = _default_open_log

    frame = tk.Frame(parent, padx=40, pady=40, bg=styles.BG_WHITE)
    frame.pack(expand=True, fill="both")

    completion_label = tk.Label(
        frame,
        text=completion_text,
        font=styles.FONT_HEADER,
        fg=styles.get_main(),
        bg=styles.BG_WHITE,
    )
    completion_label.pack()

    time_label = tk.Label(
        frame,
        text="Total Time: 00:00",
        font=styles.FONT_LABEL,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    )
    time_label.pack(pady=10)

    summary_label = tk.Label(
        frame,
        text="",
        font=styles.FONT_LABEL,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        justify=tk.LEFT,
    )
    summary_label.pack(pady=10)

    tk.Button(
        frame,
        text=log_btn_text,
        width=30,
        bg=styles.get_main(),
        fg="white",
        pady=10,
        command=on_open_log,
        font=styles.FONT_BUTTON,
    ).pack(pady=10)

    tk.Button(
        frame,
        text="Open Folder",
        width=30,
        bg=styles.get_main(),
        fg="white",
        pady=10,
        command=on_open_folder,
        font=styles.FONT_BUTTON,
    ).pack(pady=10)

    result = {
        "completion_label": completion_label,
        "time_label": time_label,
        "summary_label": summary_label,
    }

    # Extra labels (e.g. genre_label for Album Genre Tagger)
    for key in extra_labels or []:
        extra_label = tk.Label(
            frame, text="", bg=styles.BG_WHITE, fg=styles.FG_MAIN, font=styles.FONT_BODY
        )
        extra_label.pack(pady=(0, 10))
        result[key] = extra_label

    # Optional before/after audition row
    if on_play_original is not None:
        audition = add_audition_buttons(
            frame,
            on_play_original=on_play_original,
            on_play_result=(
                on_play_result if on_play_result is not None else on_play_original
            ),
        )
        result["play_original_btn"] = audition["play_original_btn"]
        result["play_result_btn"] = audition["play_result_btn"]
        result["audition_caption_var"] = audition["caption_var"]

    return result


# ── Common UI Helpers ─────────────────────────────────────────────────────────


def path_row(
    parent: tk.Frame, label: str, var: tk.StringVar, on_browse: Callable[[], None]
) -> None:
    """Standard label + entry + browse button row."""
    tk.Label(
        parent,
        text=label,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(anchor="w", pady=(6, 0))

    row = tk.Frame(parent, bg=styles.BG_WHITE)
    row.pack(fill="x", pady=3)

    tk.Entry(
        row,
        textvariable=var,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        insertbackground=styles.FG_MAIN,
    ).pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 5))

    tk.Button(
        row,
        text="Browse",
        bg=styles.get_main(),
        fg="white",
        font=styles.FONT_BUTTON,
        command=on_browse,
    ).pack(side=tk.RIGHT)


def slider_row(
    parent: tk.Misc,
    label: str,
    var: tk.Variable,
    from_: float,
    to: float,
    resolution: float,
    label_width: int = 28,
) -> None:
    """Standard label + slider + value readout row."""
    row = tk.Frame(parent, bg=styles.BG_WHITE)
    row.pack(fill="x", pady=1)

    tk.Label(
        row,
        text=f"{label}:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=label_width,
        anchor="w",
    ).pack(side=tk.LEFT)

    tk.Scale(
        row,
        from_=from_,
        to=to,
        resolution=resolution,
        orient=tk.HORIZONTAL,
        variable=cast("tk.DoubleVar", var),
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        troughcolor=styles.BG_LIGHT,
        highlightthickness=0,
        font=styles.FONT_CAPTION,
        length=220,
    ).pack(side=tk.LEFT, padx=6)

    tk.Label(
        row,
        textvariable=var,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        width=6,
    ).pack(side=tk.LEFT)


def discrete_slider_row(
    parent: tk.Frame,
    label: str,
    var: tk.StringVar,
    values: list[float],
    label_width: int = 28,
    value_format: str = "{:.1f}",
) -> None:
    """Standard label + discrete-stop slider + value readout row.

    Unlike slider_row(), which sweeps a continuous range at a fixed
    resolution, this snaps to an explicit list of allowed values that
    need not be evenly spaced (e.g. LUFS presets: -12, -14, -16, -18,
    -23). The underlying tk.Scale operates on stop indices
    (0..len(values) - 1); var is kept in sync with the formatted value
    string at the selected stop, so callers that already read var as a
    plain numeric string (e.g. float(var.get())) require no changes.

    Args:
        parent: Container frame.
        label: Row label text (colon appended automatically). Pass ""
            to omit the row label entirely, e.g. when the caller
            already renders its own heading above the row.
        var: StringVar holding the formatted value string (e.g.
            "-16.0"). Read once on build to select the initial stop —
            matched numerically against values, not by exact string,
            since Tcl's float-to-string conversion when var is set
            programmatically (e.g. from a CLI arg) is not guaranteed
            to match value_format's output. Updated on every drag.
        values: Non-empty list of allowed numeric values, in the order
            they should appear along the slider.
        label_width: Character width reserved for the label.
        value_format: Format spec applied to each value, both for
            display and for the string written back into var.

    Raises:
        AudioConfigurationError: If values is empty.
    """
    if not values:
        raise AudioConfigurationError("discrete_slider_row: values must not be empty")

    formatted = [value_format.format(v) for v in values]

    initial_index = 0
    try:
        current = float(var.get())
        initial_index = min(range(len(values)), key=lambda i: abs(values[i] - current))
    except (TypeError, ValueError):
        pass
    var.set(formatted[initial_index])

    index_var = tk.IntVar(value=initial_index)

    def _sync_index_from_var(*_: object) -> None:
        """Re-sync the Scale position when var is set externally.

        var can be changed after this row is built — e.g. CLI arguments
        applied post-UI-build via UniversalCLIHandler — and the Scale
        must follow, not just the text readout bound to var directly.
        This also fires (harmlessly, to the same index) when _on_move
        writes var in response to a drag.
        """
        try:
            current = float(var.get())
        except (TypeError, ValueError):
            return
        idx = min(range(len(values)), key=lambda i: abs(values[i] - current))
        if idx != index_var.get():
            index_var.set(idx)

    var.trace_add("write", _sync_index_from_var)

    row = tk.Frame(parent, bg=styles.BG_WHITE)
    row.pack(fill="x", pady=1)

    if label:
        tk.Label(
            row,
            text=f"{label}:",
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            width=label_width,
            anchor="w",
        ).pack(side=tk.LEFT)

    def _on_move(raw_index: str) -> None:
        idx = int(round(float(raw_index)))
        idx = max(0, min(idx, len(formatted) - 1))
        var.set(formatted[idx])

    tk.Scale(
        row,
        from_=0,
        to=len(values) - 1,
        resolution=1,
        orient=tk.HORIZONTAL,
        variable=index_var,
        showvalue=False,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        troughcolor=styles.BG_LIGHT,
        highlightthickness=0,
        font=styles.FONT_CAPTION,
        length=220,
        command=_on_move,
    ).pack(side=tk.LEFT, padx=6)

    tk.Label(
        row,
        textvariable=var,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        width=6,
    ).pack(side=tk.LEFT)


# ── Processing tab ────────────────────────────────────────────────────────────


def build_processing_tab(
    parent: tk.Frame,
    slot_vars: list[tk.StringVar] | None = None,
    stats_text: str = "Processed: 0 | Skipped: 0 | Errors: 0",
) -> dict[str, Any]:
    """
    Build the standard Processing tab layout.

    Args:
        parent:      The notebook tab frame.
        slot_vars:   List of StringVars — one per worker thread.
                     Pass None (or omit) for single-threaded tools — the
                     Active Workers panel is simply not shown.
        stats_text:  Initial text for the stats label.

    Returns:
        {
            'overall_status': tk.StringVar,
            'progress':       ttk.Progressbar,
            'stats_label':    tk.Label,
            'file_listbox':   tk.Listbox,
        }
    """
    frame = tk.Frame(parent, padx=15, pady=15, bg=styles.BG_WHITE)
    frame.pack(expand=True, fill="both")

    overall_status = tk.StringVar(value="Waiting...")
    tk.Label(
        frame,
        textvariable=overall_status,
        font=styles.FONT_LABEL_B,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
    ).pack(anchor="w")

    progress = ttk.Progressbar(
        frame,
        orient="horizontal",
        mode="determinate",
        style="Suite.Horizontal.TProgressbar",
    )
    progress.pack(fill="x", pady=(10, 20))

    stats_frame = tk.Frame(frame, bg=styles.BG_WHITE)
    stats_frame.pack(fill="x", pady=(0, 10))
    stats_label = tk.Label(
        stats_frame,
        text=stats_text,
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
    )
    stats_label.pack(anchor="w")

    if slot_vars:
        worker_frame = tk.LabelFrame(
            frame,
            text="Active Workers",
            fg=styles.get_dark(),
            bg=styles.BG_WHITE,
            padx=10,
            pady=10,
        )
        worker_frame.pack(fill="x", pady=10)
        for i, var in enumerate(slot_vars):
            tk.Label(
                worker_frame,
                text=f"W{i + 1}:",
                font=styles.FONT_CAPTION_B,
                bg=styles.BG_WHITE,
                fg=styles.FG_SUB,
            ).grid(row=i, column=0, sticky="w")
            tk.Label(
                worker_frame,
                textvariable=var,
                font=styles.FONT_MONO,
                bg=styles.BG_WHITE,
                fg=styles.FG_MAIN,
            ).grid(row=i, column=1, sticky="w", padx=10)

    file_listbox = tk.Listbox(
        frame,
        height=8,
        font=styles.FONT_MONO,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        highlightthickness=0,
        borderwidth=1,
        relief=tk.SOLID,
    )
    file_listbox.pack(fill="both", expand=True, pady=5)
    scrollbar = tk.Scrollbar(file_listbox, bg=styles.BG_WHITE)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    file_listbox.config(yscrollcommand=scrollbar.set)
    scrollbar.config(command=file_listbox.yview)

    return {
        "overall_status": overall_status,
        "progress": progress,
        "stats_label": stats_label,
        "file_listbox": file_listbox,
    }


def _build_header(
    parent: tk.Toplevel, title: str, icon: str, icon_color: str
) -> tk.Frame:
    """Build the coloured header section of a show_message dialog.

    Args:
        parent: The dialog ``Toplevel``.
        title: The dialog title (also displayed in the header).
        icon: A short icon string prepended to the title.
        icon_color: Foreground colour for the icon/title label.

    Returns:
        The header ``Frame``.
    """
    header_bg = styles.get_main()
    header = tk.Frame(parent, bg=header_bg, pady=15)
    header.pack(fill="x")
    tk.Label(
        header,
        text=f"{icon}  {title}",
        font=styles.FONT_HEADER,
        bg=header_bg,
        fg=icon_color,
    ).pack()
    return header


def _build_content(parent: tk.Toplevel, message: str) -> tk.Frame:
    """Build the message-body section of a show_message dialog.

    Args:
        parent: The dialog ``Toplevel``.
        message: The text to display.

    Returns:
        The content ``Frame``.
    """
    content = tk.Frame(parent, bg=styles.BG_WHITE, padx=30, pady=30)
    content.pack(fill="both", expand=True)
    tk.Label(
        content,
        text=message,
        font=styles.FONT_LABEL,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        wraplength=340,
        justify=tk.CENTER,
    ).pack(fill="both", expand=True)
    return content


def _build_action_row(parent: tk.Toplevel) -> tk.Button:
    """Build the OK button row of a show_message dialog.

    Binds hover effects and keyboard shortcuts (Return/Escape) to dismiss
    the dialog.

    Args:
        parent: The dialog ``Toplevel``.

    Returns:
        The OK ``Button`` (for external binding if needed).
    """
    btn_frame = tk.Frame(parent, bg=styles.BG_WHITE)
    btn_frame.pack(fill="x", pady=(0, 20))
    ok_btn = tk.Button(
        btn_frame,
        text="OK",
        width=15,
        font=styles.FONT_BUTTON,
        bg=styles.get_main(),
        fg="white",
        command=parent.destroy,
        relief=tk.FLAT,
        bd=0,
    )
    ok_btn.pack()

    def _on_enter(_e: object) -> None:
        ok_btn["bg"] = styles.get_dark()

    def _on_leave(_e: object) -> None:
        ok_btn["bg"] = styles.get_main()

    ok_btn.bind("<Enter>", _on_enter)
    ok_btn.bind("<Leave>", _on_leave)
    parent.bind("<Return>", lambda _e: parent.destroy())
    parent.bind("<Escape>", lambda _e: parent.destroy())
    return ok_btn


def show_message(
    parent: tk.Misc,
    title: str,
    message: str,
    icon: str = "\u2139",
    icon_color: str = "#ffffff",
) -> None:
    """Show a themed modal dialog box with a coloured header.

    The dialog honours the suite palette, centres itself over *parent*,
    and closes on OK, Return, or Escape.  A warning is logged when
    called from a non-main thread (the dialog must be created on the
    main thread).

    Args:
        parent: The parent widget the dialog is transient to.
        title: Window title and header text.
        message: Body text displayed in the content area.
        icon: A short string prepended to the header title
            (default ``ℹ``).
        icon_color: Foreground colour for the header icon/title
            (default ``#ffffff``).
    """
    if threading.current_thread() is not threading.main_thread():
        _log.warning(
            "show_message() called from non-main thread — this is a bug. "
            "Use root.after(0, ...) to schedule dialog on the main thread."
        )
    dialog = tk.Toplevel(parent)
    dialog.title(title)
    dialog.configure(bg=styles.BG_WHITE)
    dialog.resizable(False, False)
    dialog.transient(cast("tk.Wm", parent))
    dialog.attributes("-topmost", True)

    dialog.grab_set()

    dialog.update_idletasks()
    w = 400
    h = 240

    try:
        px = parent.winfo_rootx()
        py = parent.winfo_rooty()
        pw = parent.winfo_width()
        ph = parent.winfo_height()
        x = px + (pw // 2) - (w // 2)
        y = py + (ph // 2) - (h // 2)
        dialog.geometry(f"{w}x{h}+{x}+{y}")
    except (OSError, tk.TclError) as _exc:
        _log.debug("Could not centre dialog: %s", _exc)
        dialog.geometry(f"{w}x{h}")

    _build_header(dialog, title, icon, icon_color)
    _build_content(dialog, message)
    _build_action_row(dialog)

    dialog.wait_window()


# ── Preset helpers ────────────────────────────────────────────────────────────


def save_preset_dialog(
    combo: ttk.Combobox,
    on_save: Callable[[str], None] | None,
) -> None:
    """Open the shared "Save Preset" modal dialog.

    Args:
        combo:   The preset combobox the saved name is written back to.
        on_save: Callback invoked with the typed name when the user confirms;
            None turns the dialog into a no-op confirmation.
    """
    dialog = tk.Toplevel(combo.winfo_toplevel())
    dialog.title("Save Preset")
    dialog.geometry("350x150+400+300")
    dialog.transient(combo.winfo_toplevel())
    dialog.grab_set()
    tk.Label(dialog, text="Preset Name:", font=styles.FONT_BODY).pack(pady=(15, 5))
    name_var = tk.StringVar(dialog)
    entry = tk.Entry(dialog, textvariable=name_var, font=styles.FONT_BODY, width=40)
    entry.pack(padx=20, pady=5)
    entry.focus_set()

    def _do_save() -> None:
        name = name_var.get().strip()
        if name and on_save is not None:
            on_save(name)
            combo.set(name)
        dialog.destroy()

    entry.bind("<Return>", lambda _event: _do_save())
    tk.Button(
        dialog,
        text="Save",
        command=_do_save,
        bg=styles.get_main(),
        fg="white",
        font=styles.FONT_BUTTON,
    ).pack(pady=10)


def delete_preset_action(
    combo: ttk.Combobox,
    on_delete: Callable[[str], None] | None,
) -> None:
    """Confirm then delete the preset currently selected in the combobox.

    Args:
        combo:     The preset combobox holding the selection.
        on_delete: Callback invoked with the preset name once the user
                   confirms the delete prompt.
    """
    name = combo.get()
    if not name:
        return

    from tkinter import messagebox

    if messagebox.askyesno("Delete Preset", f'Delete preset "{name}"?'):
        if on_delete is not None:
            on_delete(name)
        combo.set("")


# ── BaseSetupFrame ────────────────────────────────────────────────────────────


class BaseSetupFrame(tk.Frame):
    """Shared skeleton for tool Setup tabs.

    Renders the standard order — title, run-controls panel, preset row,
    tool-specific options, and start button — then packs itself to fill the
    parent. Subclasses implement ``_build_options()`` to emit tool-specific
    widgets and may override ``_layout()`` to reorder the additive stages.
    """

    def __init__(
        self,
        parent: tk.Frame,
        *,
        title: str,
        start_text: str,
        on_start: Callable[[], None],
        folder_path: tk.StringVar,
        run_mode: tk.StringVar,
        auto_start_var: tk.BooleanVar,
        auto_end_var: tk.BooleanVar,
        clear_logs_var: tk.BooleanVar | None = None,
        parallel_var: tk.BooleanVar | None = None,
        on_browse: Callable[[], None] | None = None,
        driver_locked: bool = False,
        preset_names: list[str] | None = None,
        preset_loader: Callable[[], list[str]] | None = None,
        on_save_preset: Callable[[str], None] | None = None,
        on_delete_preset: Callable[[str], None] | None = None,
        on_preset_selected: Callable[[str], None] | None = None,
        preset_row_always: bool = False,
        browse_text: str = "Browse...",
        modes: tuple[str, ...] | None = None,
        include_controls_panel: bool = True,
        padx: int = 30,
        pady: int = 30,
        title_font: Any = styles.FONT_TITLE,
        title_pady: tuple[int, int] = (0, 20),
        start_side: str | None = "bottom",
    ) -> None:
        """Populate the shared Setup-tab skeleton.

        Args:
            parent:    The parent frame the tab is placed into.
            title:     Tool title label text.
            start_text: Text for the start button, e.g. "BEGIN BPM ANALYSIS".
            on_start:  Callback for the start button.
            folder_path: StringVar bound to the source directory entry.
            run_mode:  StringVar holding the run mode for the mode combobox.
            auto_start_var: BooleanVar mirroring the driver's Auto Start.
            auto_end_var: BooleanVar mirroring the driver's Auto End.
            clear_logs_var: Optional BooleanVar mirroring Clear Logs.
            parallel_var: Optional BooleanVar mirroring Parallel.
            on_browse: Optional callback for the Browse button.
            driver_locked: When True the run-controls panel is read-only.
            preset_names: List of preset names seeded into the preset combo.
            preset_loader: Callable returning preset names for refreshes
                where no explicit names are passed.
            on_save_preset: Callback invoked when a preset is saved; also
                gates whether the preset row is rendered at all.
            on_delete_preset: Callback invoked to delete a preset.
            on_preset_selected: Callback when a preset is picked.
            preset_row_always: Render the preset row even when on_save_preset
                is None (replaygain_analyzer renders it unconditionally).
            browse_text: Text for the Browse button.
            modes: Custom mode labels for the run-controls panel; None keeps
                the panel's default ("Dry Run", "Live Update").
            include_controls_panel: False for tools without a controls panel.
            padx: Horizontal padding of the tab frame.
            pady: Vertical padding of the tab frame.
            title_font: Font for the title label.
            title_pady: Vertical padding applied to the title label.
            start_side: Pack side for the start button; "bottom" by default.
                Pass None to omit the side so the button packs after the
                preceding widgets (used by asx_extractor).
        """
        super().__init__(parent, padx=padx, pady=pady, bg=styles.BG_WHITE)

        self._title = title
        self._start_text = start_text
        self._on_start = on_start
        self._folder_path = folder_path
        self._run_mode = run_mode
        self._auto_start_var = auto_start_var
        self._auto_end_var = auto_end_var
        self._clear_logs_var = clear_logs_var
        self._parallel_var = parallel_var
        self._on_browse = on_browse
        self._driver_locked = driver_locked
        self._preset_names = preset_names
        self._preset_loader = preset_loader
        self._on_save_preset = on_save_preset
        self._on_delete_preset = on_delete_preset
        self._on_preset_selected = on_preset_selected
        self._preset_row_always = preset_row_always
        self._browse_text = browse_text
        self._modes = modes
        self._include_controls_panel = include_controls_panel
        self._title_font = title_font
        self._title_pady = title_pady
        self._start_side = start_side

        # Public handles — populated by the additive build stages below.
        self.start_btn: tk.Button | None = None
        self.controls_panel: DriverControlsPanel | None = None
        self.preset_combo: ttk.Combobox | None = None

        self.pack(expand=True, fill="both")
        self._layout()

    # ── Template method ───────────────────────────────────────────────────

    def _layout(self) -> None:
        """Standard skeleton ordering. Override to reorder additive methods."""
        self._add_title()
        if self._include_controls_panel:
            self._add_controls_panel()
        self._add_preset_row()
        self._build_options()
        self._add_start_button()

    def _build_options(self) -> None:
        """Per-tool hook; subclasses emit their tool-specific widgets here."""

    # ── Additive build stages ─────────────────────────────────────────────

    def _add_title(self) -> None:
        tk.Label(
            self,
            text=self._title,
            font=self._title_font,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=self._title_pady)

    def _add_controls_panel(self) -> None:
        modes_kwargs: dict[str, Any] = {}
        if self._modes is not None:
            modes_kwargs["modes"] = self._modes
        panel = DriverControlsPanel(
            self,
            source_var=self._folder_path,
            mode_var=self._run_mode,
            auto_start_var=self._auto_start_var,
            auto_end_var=self._auto_end_var,
            clear_logs_var=self._clear_logs_var,
            parallel_var=self._parallel_var,
            on_browse=self._on_browse,
            browse_text=self._browse_text,
            **modes_kwargs,
        )
        panel.pack(fill="x", pady=(0, 15))
        panel.set_driven(self._driver_locked)
        self.controls_panel = panel

    def _add_preset_row(self) -> None:
        # The preset row renders only when the tool wires a save handler
        # (unless preset_row_always forces it, see replaygain_analyzer).
        on_save = self._on_save_preset
        if on_save is None and not self._preset_row_always:
            self.preset_combo = None
            return

        preset_frame = tk.Frame(self, bg=styles.BG_WHITE)
        preset_frame.pack(fill="x", pady=(0, 15))
        tk.Label(
            preset_frame,
            text="Presets:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(0, 5))

        # Parented to preset_frame so it packs inline with the label and
        # Save/Delete buttons; a combo parented to self packs at the frame's
        # left edge and detaches from the Presets row.
        combo = ttk.Combobox(
            preset_frame,
            state="readonly",
            font=styles.FONT_BODY,
            width=28,
        )
        combo["values"] = self._preset_names or []
        combo.pack(side=tk.LEFT, padx=(0, 5))
        self.preset_combo = combo

        on_selected = self._on_preset_selected

        def _on_preset_combo_select(_event: object) -> None:
            name = combo.get()
            if name and on_selected is not None:
                on_selected(name)

        combo.bind("<<ComboboxSelected>>", _on_preset_combo_select)

        on_delete = self._on_delete_preset
        tk.Button(
            preset_frame,
            text="Save",
            command=lambda: save_preset_dialog(combo, on_save),
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BODY,
            padx=8,
        ).pack(side=tk.LEFT, padx=(0, 3))
        tk.Button(
            preset_frame,
            text="Delete",
            command=lambda: delete_preset_action(combo, on_delete),
            bg="#cc5555",
            fg="white",
            font=styles.FONT_BODY,
            padx=8,
        ).pack(side=tk.LEFT)

    def _add_start_button(self) -> None:
        self.start_btn = tk.Button(
            self,
            text=self._start_text,
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            height=2,
            command=self._on_start,
        )
        pack_options: dict[str, Any] = {"fill": "x", "pady": 10}
        if self._start_side is not None:
            pack_options["side"] = self._start_side
        self.start_btn.pack(**pack_options)

    # ── Shared option helpers ─────────────────────────────────────────────

    def add_config_group(self, text: str) -> tk.LabelFrame:
        """Create a standard " Configuration " LabelFrame packed into the tab.

        Args:
            text: Panel title; rendered as " {text} ".

        Returns:
            The populated LabelFrame.
        """
        group = tk.LabelFrame(
            self,
            text=f" {text} ",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            padx=15,
            pady=15,
        )
        group.pack(fill="x", pady=20)
        return group

    def add_parallel_row(
        self,
        parallel_mode: tk.BooleanVar,
        max_workers: tk.IntVar,
        caption: str,
    ) -> None:
        """Add the standard Parallel Processing / Workers row.

        Args:
            parallel_mode: BooleanVar toggling parallel worker usage.
            max_workers:   IntVar holding the worker count.
            caption:       Explanatory caption shown to the right.
        """
        par_frame = tk.Frame(self, bg=styles.BG_WHITE)
        par_frame.pack(fill="x", pady=(10, 0))
        tk.Checkbutton(
            par_frame,
            text="Parallel Processing",
            variable=parallel_mode,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
        ).pack(side=tk.LEFT)
        tk.Label(
            par_frame,
            text="Workers:",
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=(12, 2))
        tk.Entry(
            par_frame,
            textvariable=max_workers,
            width=4,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT)
        tk.Label(
            par_frame,
            text=caption,
            font=styles.FONT_CAPTION,
            bg=styles.BG_WHITE,
            fg=styles.FG_SUB,
        ).pack(side=tk.LEFT, padx=10)

    # ── Public API ─────────────────────────────────────────────────────────

    def refresh_preset_list(self, names: list[str] | None = None) -> None:
        """Reload the preset combobox from names, the loader, or the ctor.

        Args:
            names: Explicit replacement list; when None the preset_loader
                is tried first and the constructor preset_names last. A
                current selection missing from the new values is cleared.
        """
        combo = self.preset_combo
        if combo is None:
            return
        if names is not None:
            values = names
        elif self._preset_loader is not None:
            values = self._preset_loader()
        else:
            values = self._preset_names or []
        combo["values"] = values
        if combo.get() not in values:
            combo.set("")

    def get_widgets(self) -> dict[str, Any]:
        """Return the common widget handles built for this tab.

        Keys for widgets that were not built are omitted (start_btn,
        controls_panel, preset_combo, refresh_preset_list).

        Returns:
            Mapping of widget key to the built widget or callable.
        """
        widgets: dict[str, Any] = {}
        if self.start_btn is not None:
            widgets["start_btn"] = self.start_btn
        if self.controls_panel is not None:
            widgets["controls_panel"] = self.controls_panel
        if self.preset_combo is not None:
            widgets["preset_combo"] = self.preset_combo
            widgets["refresh_preset_list"] = self.refresh_preset_list
        return widgets


class AnalysisSetupFrame(BaseSetupFrame):
    """Setup tab for the analyse-and-tag tools.

    Builds the shared analysis-duration widget block, the optional
    Parallel Processing / Workers row with a tool caption, and an
    optional explanatory help block. Only the labels, ranges, defaults
    and help text differ per tool — the geometry lives here once
    (iteration-7 B3: third shared-seam customer after noise/pop and
    key/mood file processors).

    Subclasses stay data-thin; tool-specific extras that don't fit the
    shared shape may still extend ``_build_options()``.
    """

    def __init__(
        self,
        parent: tk.Frame,
        *,
        analysis_duration: tk.IntVar,
        parallel_mode: tk.BooleanVar | None = None,
        max_workers: tk.IntVar | None = None,
        parallel_caption: str = "",
        help_heading: str | None = None,
        help_text: str | None = None,
        help_wraplength: int = 520,
        **kwargs: Any,
    ) -> None:
        """Populate the analysis Setup tab.

        Args:
            analysis_duration: IntVar bound to the duration Entry.
            parallel_mode: BooleanVar toggling parallel processing; the
                parallel row is rendered only when both this and
                ``max_workers`` are supplied.
            max_workers: IntVar holding the worker count.
            parallel_caption: Caption shown next to the parallel row.
            help_heading: Optional bold heading above the help text
                (e.g. "How Mood Is Determined:").
            help_text: Optional explanatory paragraph. Omitted entirely
                (e.g. key_detector) when None.
            help_wraplength: Pixel wrap width of the help caption.
            **kwargs: Forwarded to :class:`BaseSetupFrame`.
        """
        self._analysis_duration = analysis_duration
        self._parallel_mode = parallel_mode
        self._max_workers = max_workers
        self._parallel_caption = parallel_caption
        self._help_heading = help_heading
        self._help_text = help_text
        self._help_wraplength = help_wraplength
        super().__init__(parent, **kwargs)

    def _add_analysis_duration(self) -> None:
        """The standard Analysis Duration label / entry / caption block."""
        tk.Label(
            self,
            text="Analysis Duration (seconds):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(15, 0))
        tk.Entry(
            self,
            textvariable=self._analysis_duration,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
            width=10,
        ).pack(anchor="w", pady=5)
        tk.Label(
            self,
            text="(Lower values = faster processing, less accuracy)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

    def _build_options(self) -> None:
        """Duration block, optional parallel row, optional help block."""
        self._add_analysis_duration()

        if self._parallel_mode is not None and self._max_workers is not None:
            self.add_parallel_row(
                self._parallel_mode,
                self._max_workers,
                self._parallel_caption,
            )

        if self._help_heading is not None:
            tk.Label(
                self,
                text=self._help_heading,
                font=styles.FONT_BODY,
                fg=styles.FG_MAIN,
                bg=styles.BG_WHITE,
            ).pack(anchor="w", pady=(20, 2))
        if self._help_text is not None:
            tk.Label(
                self,
                text=self._help_text,
                font=styles.FONT_CAPTION,
                fg=styles.FG_SUB,
                bg=styles.BG_WHITE,
                justify="left",
                wraplength=self._help_wraplength,
            ).pack(anchor="w")
