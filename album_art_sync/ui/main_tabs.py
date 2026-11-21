"""
main_tabs.py — Builds the Album Art Sync Setup tab.

The Processing and Results tabs come from the shared ``SuiteApp`` shell, so
this module owns only the tool's own settings panel.

Changed in 2.9.0: the Processing and Results builders moved to the shell (C1
stage 2), and the Setup panel now shows the tool's title.
"""

import tkinter as tk
from tkinter import filedialog, ttk
from typing import Any, Callable, Optional

from audio_suite_shared import styles
from audio_suite_shared.ui_driver_controls import DriverControlsPanel


def build_setup_tab(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    size_var: tk.StringVar,
    purge_var: tk.BooleanVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    on_start: Callable[[], None],
    driver_locked: bool = False,
    on_browse: Optional[Callable[[], None]] = None,
    preset_names: Optional[list[str]] = None,
    on_save_preset: Optional[Callable[[], None]] = None,
    on_delete_preset: Optional[Callable[[], None]] = None,
    on_preset_selected: Optional[Callable[[str], None]] = None,
    title: str = "",
) -> dict[str, Any]:
    """
    Returns:
        {
            'start_btn':          tk.Button,
            'refresh_preset_list': Callable[[list[str]], None],
            'preset_combo':        ttk.Combobox,
            'controls_panel':      DriverControlsPanel,
        }
    """
    setup_frame = tk.Frame(parent, padx=30, pady=30, bg=styles.BG_WHITE)
    setup_frame.pack(expand=True, fill="both")

    if title:
        tk.Label(
            setup_frame,
            text=title,
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=(0, 15))

    # ── Run Controls panel (mirrors the Master Driver control strip) ─────────
    controls_panel = DriverControlsPanel(
        setup_frame,
        source_var=folder_path,
        mode_var=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse or (lambda: folder_path.set(filedialog.askdirectory())),
    )
    controls_panel.pack(fill="x", pady=(0, 15))
    controls_panel.set_driven(driver_locked)

    cfg = tk.LabelFrame(
        setup_frame,
        text=" Configuration ",
        fg=styles.FG_MAIN,
        bg=styles.BG_WHITE,
        padx=15,
        pady=15,
    )
    cfg.pack(fill="x", pady=20)

    r_f = tk.Frame(cfg, bg=styles.BG_WHITE)
    r_f.pack(fill="x", pady=5)
    tk.Label(
        r_f,
        text="Embedded Res:",
        fg=styles.FG_MAIN,
        bg=styles.BG_WHITE,
        font=styles.FONT_BODY,
    ).pack(side=tk.LEFT)
    ttk.Combobox(
        r_f,
        textvariable=size_var,
        values=("600", "800", "1000", "1200"),
        font=styles.FONT_BODY,
        state="readonly",
        width=10,
    ).pack(side=tk.LEFT, padx=10)

    p_f = tk.Frame(cfg, bg=styles.BG_WHITE)
    p_f.pack(fill="x", pady=5)
    tk.Checkbutton(
        p_f,
        text="Purge Hidden System Art",
        font=styles.FONT_BODY,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        selectcolor=styles.BG_WHITE,
        activebackground=styles.BG_WHITE,
        activeforeground=styles.FG_MAIN,
        variable=purge_var,
    ).pack(side=tk.LEFT)

    # ── Presets ─────────────────────────────────────────────────────
    preset_frame = tk.LabelFrame(
        setup_frame,
        text=" Presets ",
        fg=styles.FG_MAIN,
        bg=styles.BG_WHITE,
        padx=15,
        pady=15,
    )
    preset_frame.pack(fill="x", pady=(0, 20))

    preset_sel_frame = tk.Frame(preset_frame, bg=styles.BG_WHITE)
    preset_sel_frame.pack(fill="x", pady=5)

    tk.Label(
        preset_sel_frame,
        text="Load Preset:",
        fg=styles.FG_MAIN,
        bg=styles.BG_WHITE,
        font=styles.FONT_BODY,
    ).pack(side=tk.LEFT)

    preset_combo = ttk.Combobox(
        preset_sel_frame,
        values=preset_names or [],
        font=styles.FONT_BODY,
        state="readonly",
        width=20,
    )
    preset_combo.pack(side=tk.LEFT, padx=10)

    if on_preset_selected:
        preset_combo.bind(
            "<<ComboboxSelected>>",
            lambda e: on_preset_selected(preset_combo.get()),
        )

    preset_btn_frame = tk.Frame(preset_frame, bg=styles.BG_WHITE)
    preset_btn_frame.pack(fill="x", pady=5)

    tk.Button(
        preset_btn_frame,
        text="Save Preset",
        bg=styles.get_main(),
        fg="white",
        font=styles.FONT_BUTTON,
        command=on_save_preset or (lambda: None),
    ).pack(side=tk.LEFT, padx=(0, 5))

    tk.Button(
        preset_btn_frame,
        text="Delete Preset",
        bg="#999",
        fg="white",
        font=styles.FONT_BUTTON,
        command=on_delete_preset or (lambda: None),
    ).pack(side=tk.LEFT)

    def refresh_preset_list(names: list[str]) -> None:
        preset_combo["values"] = names
        if not names:
            preset_combo.set("")

    # ── Start button ────────────────────────────────────────────────
    start_btn = tk.Button(
        setup_frame,
        text="BEGIN ALBUM ART SYNCH",
        bg=styles.get_main(),
        fg="white",
        font=styles.FONT_BUTTON,
        height=2,
        command=on_start,
    )
    start_btn.pack(side=tk.BOTTOM, fill="x", pady=10)

    return {
        "start_btn": start_btn,
        "refresh_preset_list": refresh_preset_list,
        "preset_combo": preset_combo,
        "controls_panel": controls_panel,
    }
