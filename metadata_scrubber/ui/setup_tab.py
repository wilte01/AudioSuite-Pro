"""
setup_tab.py — Setup tab for Metadata Scrubber.

The dynamic tag-checkbox panel is managed here.
get_preserve_list() is the only bridge to the core layer.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_driver_controls import DriverControlsPanel


class SetupTab:
    def __init__(
        self,
        parent: tk.Frame,
        folder_path: tk.StringVar,
        run_mode: tk.StringVar,
        auto_start_var: tk.BooleanVar,
        auto_end_var: tk.BooleanVar,
        clear_logs_var: tk.BooleanVar,
        parallel_var: tk.BooleanVar,
        preserve_lyrics: tk.BooleanVar,
        preserve_album_artist: tk.BooleanVar,
        preserve_embedded_art: tk.BooleanVar,
        on_browse_scan: Callable[..., Any],
        on_start: Callable[..., Any],
        driver_locked: bool = False,
        preset_names: list[str] | None = None,
        on_save_preset: Callable[[str], None] | None = None,
        on_delete_preset: Callable[[str], None] | None = None,
        on_preset_selected: Callable[[str], None] | None = None,
    ):

        self._tag_vars: dict[str, tk.BooleanVar] = {}
        self._preset_names = preset_names
        self._on_save_preset = on_save_preset
        self._on_delete_preset = on_delete_preset
        self._on_preset_selected = on_preset_selected

        frame = tk.Frame(parent, padx=30, pady=20, bg=styles.BG_WHITE)
        frame.pack(expand=True, fill="both")

        tk.Label(
            frame,
            text="Metadata Scrubber & Tagger",
            font=styles.FONT_TITLE,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(pady=(0, 20))

        # ── Run Controls (mirrors the Master Driver strip) ───────────────
        self.controls_panel = DriverControlsPanel(
            frame,
            source_var=folder_path,
            mode_var=run_mode,
            auto_start_var=auto_start_var,
            auto_end_var=auto_end_var,
            clear_logs_var=clear_logs_var,
            parallel_var=parallel_var,
            on_browse=on_browse_scan,
            browse_text="Browse & Scan",
        )
        self.controls_panel.pack(fill="x", pady=(0, 10))
        self.controls_panel.set_driven(driver_locked)

        # ── Presets ────────────────────────────────────────────────────────────
        if on_save_preset is not None:
            preset_frame = tk.Frame(frame, bg=styles.BG_WHITE)
            preset_frame.pack(fill="x", pady=(0, 10))
            tk.Label(
                preset_frame,
                text="Presets:",
                font=styles.FONT_BODY,
                fg=styles.FG_MAIN,
                bg=styles.BG_WHITE,
            ).pack(side=tk.LEFT, padx=(0, 5))
            self.preset_combo = ttk.Combobox(
                preset_frame,
                state="readonly",
                font=styles.FONT_BODY,
                width=28,
            )
            self.preset_combo["values"] = preset_names or []
            self.preset_combo.pack(side=tk.LEFT, padx=(0, 5))

            self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_combo_select)

            tk.Button(
                preset_frame,
                text="Save",
                command=self._save_preset_dialog,
                bg=styles.get_main(),
                fg="white",
                font=styles.FONT_BODY,
                padx=8,
            ).pack(side=tk.LEFT, padx=(0, 3))

            tk.Button(
                preset_frame,
                text="Delete",
                command=self._delete_preset,
                bg="#cc5555",
                fg="white",
                font=styles.FONT_BODY,
                padx=8,
            ).pack(side=tk.LEFT)

        # Preserve lyrics toggle
        tk.Checkbutton(
            frame,
            text="Preserve Lyrics (USLT/SYLT)",
            variable=preserve_lyrics,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY_B,
        ).pack(anchor="w", pady=(10, 0))

        tk.Checkbutton(
            frame,
            text="Preserve Album Artist (TPE2)",
            variable=preserve_album_artist,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY_B,
        ).pack(anchor="w", pady=(4, 0))

        tk.Checkbutton(
            frame,
            text="Preserve Embedded Art (APIC)",
            variable=preserve_embedded_art,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY_B,
        ).pack(anchor="w", pady=(4, 0))

        # Dynamic tag checkbox panel
        tag_header_frame = tk.Frame(frame, bg=styles.BG_WHITE)
        tag_header_frame.pack(fill="x", pady=(15, 2))
        tk.Label(
            tag_header_frame,
            text="Select Custom Tags to Preserve:",
            font=styles.FONT_LABEL_B,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT)
        self._prefs_indicator = tk.Label(
            tag_header_frame,
            text="",
            font=styles.FONT_CAPTION_I,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        )
        self._prefs_indicator.pack(side=tk.LEFT, padx=8)

        tag_outer = tk.Frame(frame, bg=styles.BG_WHITE)
        tag_outer.pack(fill="both", expand=True, pady=5)

        self._tag_canvas = tk.Canvas(
            tag_outer, bg=styles.BG_ITEM, bd=1, relief="sunken"
        )
        tag_scroll = ttk.Scrollbar(
            tag_outer, orient="vertical", command=self._tag_canvas.yview
        )
        self._tag_frame = tk.Frame(self._tag_canvas, bg=styles.BG_ITEM)

        self._tag_canvas.create_window((0, 0), window=self._tag_frame, anchor="nw")
        self._tag_canvas.configure(yscrollcommand=tag_scroll.set)
        self._tag_canvas.pack(side=tk.LEFT, fill="both", expand=True)
        tag_scroll.pack(side=tk.RIGHT, fill="y")

        self.start_btn = tk.Button(
            frame,
            text="BEGIN SCRUBBING",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            height=2,
            state="disabled",
            command=on_start,
        )
        self.start_btn.pack(side=tk.BOTTOM, fill="x", pady=(10, 0))

    def refresh_preset_list(self, names: list[str]) -> None:
        if hasattr(self, "preset_combo"):
            self.preset_combo["values"] = names

    def _on_preset_combo_select(self, event: object = None) -> None:
        name = self.preset_combo.get()
        if name and self._on_preset_selected:
            self._on_preset_selected(name)

    def _save_preset_dialog(self) -> None:
        if not self._on_save_preset:
            return
        dialog = tk.Toplevel()
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
            if name and self._on_save_preset:
                self._on_save_preset(name)
                self.preset_combo.set(name)
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

    def _delete_preset(self) -> None:
        name = self.preset_combo.get()
        if name and self._on_delete_preset:
            from tkinter import messagebox

            if messagebox.askyesno("Delete Preset", f'Delete preset "{name}"?'):
                self._on_delete_preset(name)
                self.preset_combo.set("")

    def populate_tags(
        self, discovered: set[str], previously_kept: set[str] | None = None
    ) -> None:
        for widget in self._tag_frame.winfo_children():
            widget.destroy()
        self._tag_vars.clear()

        has_prefs = bool(previously_kept)

        if discovered:
            auto_ticked = 0
            kept = previously_kept or set()
            for desc in sorted(discovered):
                tick = desc in kept
                if tick:
                    auto_ticked += 1

                var = tk.BooleanVar(value=tick)
                row = tk.Frame(self._tag_frame, bg=styles.BG_ITEM)
                row.pack(fill="x", padx=5, pady=1)
                tk.Checkbutton(
                    row,
                    text=desc,
                    variable=var,
                    font=styles.FONT_BODY,
                    fg=styles.FG_MAIN,
                    bg=styles.BG_ITEM,
                    selectcolor=styles.BG_ITEM,
                    activebackground=styles.BG_ITEM,
                    activeforeground=styles.FG_MAIN,
                ).pack(side=tk.LEFT)
                if has_prefs and tick:
                    tk.Label(
                        row,
                        text="(saved)",
                        font=styles.FONT_MICRO,
                        fg=styles.FG_SUB,
                        bg=styles.BG_ITEM,
                    ).pack(side=tk.LEFT, padx=4)
                self._tag_vars[desc] = var

            if has_prefs:
                new_count = len(discovered) - auto_ticked
                if new_count:
                    self._prefs_indicator.config(
                        text=f"(preferences applied · {new_count} new tag(s) unticked)"
                    )
                else:
                    self._prefs_indicator.config(text="(preferences applied)")
            else:
                self._prefs_indicator.config(text="(no saved preferences yet)")
        else:
            tk.Label(
                self._tag_frame,
                text="No custom tags found.",
                font=styles.FONT_BODY,
                bg=styles.BG_ITEM,
                fg=styles.FG_SUB,
            ).pack(pady=20)
            self._prefs_indicator.config(text="")

        self._tag_frame.update_idletasks()
        self._tag_canvas.config(scrollregion=self._tag_canvas.bbox("all"))
        self.start_btn.config(state="normal")

    def get_preserve_list(self) -> list[Any]:
        return [desc for desc, var in self._tag_vars.items() if var.get()]
