"""
setup_tab.py — Setup tab for Music Format Converter.

Opens with the shared DriverControlsPanel mirroring the Master Driver's
source bar and control strip, followed by tool-specific controls.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable

from audio_suite_shared import styles
from audio_suite_shared.ui_common import BaseSetupFrame

from ..core.ffmpeg_params import BIT_DEPTH_PRESETS, SAMPLE_RATE_PRESETS
from ..core.formats import format_info


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    output_folder: tk.StringVar,
    output_format: tk.StringVar,
    quality_preset: tk.StringVar,
    sample_rate: tk.StringVar,
    bit_depth: tk.StringVar,
    delete_originals: tk.BooleanVar,
    normalize_mp3: tk.BooleanVar,
    target_lufs: tk.DoubleVar,
    dither: tk.BooleanVar,
    run_mode: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    ffmpeg_available: bool,
    all_formats: list[str],
    on_browse_input: Callable[..., Any],
    on_browse_output: Callable[..., Any],
    on_start: Callable[..., Any],
    on_folder_change: Callable[..., Any],
    driver_locked: bool = False,
    preset_names: list[str] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    """
    Populate the Setup tab.

    Returns:
        Dict with keys: start_btn, update_detected_label,
        update_format_menu, update_format_info, refresh_preset_list,
        preset_combo, controls_panel.
    """
    frame = _SetupFrame(
        parent,
        title="Music Format Converter",
        start_text="START CONVERSION",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse_input,
        driver_locked=driver_locked,
        preset_names=preset_names,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
        pady=15,
        title_pady=(0, 10),
        start_side=None,
        output_folder=output_folder,
        output_format=output_format,
        quality_preset=quality_preset,
        sample_rate=sample_rate,
        bit_depth=bit_depth,
        delete_originals=delete_originals,
        normalize_mp3=normalize_mp3,
        target_lufs=target_lufs,
        dither=dither,
        ffmpeg_available=ffmpeg_available,
        all_formats=all_formats,
        on_browse_output=on_browse_output,
        on_folder_change=on_folder_change,
    )
    return {
        "start_btn": frame.start_btn,
        "update_detected_label": frame.update_detected_label,
        "update_format_menu": frame.update_format_menu,
        "update_format_info": frame.update_format_info,
        "refresh_preset_list": frame.refresh_preset_list,
        "preset_combo": frame.preset_combo,
        "controls_panel": frame.controls_panel,
    }


class _SetupFrame(BaseSetupFrame):
    """Music Format Converter Setup tab built on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        output_folder: tk.StringVar,
        output_format: tk.StringVar,
        quality_preset: tk.StringVar,
        sample_rate: tk.StringVar,
        bit_depth: tk.StringVar,
        delete_originals: tk.BooleanVar,
        normalize_mp3: tk.BooleanVar,
        target_lufs: tk.DoubleVar,
        dither: tk.BooleanVar,
        ffmpeg_available: bool,
        all_formats: list[str],
        on_browse_output: Callable[..., Any],
        on_folder_change: Callable[..., Any],
        **kwargs: Any,
    ) -> None:
        self._output_folder_var = output_folder
        self._output_format_var = output_format
        self._quality_preset_var = quality_preset
        self._sample_rate_var = sample_rate
        self._bit_depth_var = bit_depth
        self._delete_originals_var = delete_originals
        self._normalize_mp3_var = normalize_mp3
        self._target_lufs_var = target_lufs
        self._dither_var = dither
        self._ffmpeg_available = ffmpeg_available
        self._all_formats = all_formats
        self._on_browse_output = on_browse_output
        self._on_folder_change = on_folder_change
        super().__init__(parent, **kwargs)

    def _layout(self) -> None:
        """Presets sit above the Run Controls panel for this tool."""
        self._add_title()
        self._add_preset_row()
        if self._include_controls_panel:
            self._add_controls_panel()
        self._build_options()
        self._add_start_button()

    def _add_controls_panel(self) -> None:
        if not self._ffmpeg_available:
            self._add_ffmpeg_warning()
        super()._add_controls_panel()
        if self.controls_panel is not None:
            # Preserve the legacy folder-change triggers on the panel's entry.
            self.controls_panel.source_entry.bind(
                "<FocusOut>", lambda _e: self._on_folder_change()
            )
            self.controls_panel.source_entry.bind(
                "<Return>", lambda _e: self._on_folder_change()
            )

    def _add_ffmpeg_warning(self) -> tk.Frame:
        warn = tk.Frame(self, bg="#ffeeee", relief=tk.RIDGE, bd=2)
        warn.pack(fill="x", pady=(0, 8))
        tk.Label(
            warn,
            text="⚠ FFmpeg not found! Please install FFmpeg to use this converter.",
            font=styles.FONT_BODY_B,
            bg="#ffeeee",
            fg="#cc0000",
            wraplength=700,
        ).pack(padx=10, pady=8)
        return warn

    def _add_start_button(self) -> None:
        super()._add_start_button()
        if not self._ffmpeg_available and self.start_btn is not None:
            self.start_btn.config(state="disabled")

    def _build_options(self) -> None:
        detected_label = tk.Label(
            self,
            text="",
            font=styles.FONT_BODY_B,
            bg=styles.BG_WHITE,
            fg=styles.get_main(),
        )
        detected_label.pack(anchor="w", pady=(2, 0))

        # ── Output folder ─────────────────────────────────────────────────────
        tk.Label(
            self,
            text="Output Directory (leave empty for same as input):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(8, 0))
        o_frame = tk.Frame(self, bg=styles.BG_WHITE)
        o_frame.pack(fill="x", pady=3)
        tk.Entry(
            o_frame,
            textvariable=self._output_folder_var,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 5))
        tk.Button(
            o_frame,
            text="Browse",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self._on_browse_output,
        ).pack(side=tk.RIGHT)

        # ── Output format ─────────────────────────────────────────────────────
        tk.Label(
            self,
            text="Output Format:",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            font=styles.FONT_BODY,
        ).pack(anchor="w", pady=(8, 0))
        format_menu = ttk.Combobox(
            self,
            textvariable=self._output_format_var,
            state="readonly",
            font=styles.FONT_BODY,
        )
        format_menu["values"] = tuple(self._all_formats)
        format_menu.pack(fill="x", pady=3)

        format_info_label = tk.Label(
            self,
            text="",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=700,
        )
        format_info_label.pack(anchor="w")

        def _update_format_info(fmt: str | None = None) -> None:
            if fmt is None:
                fmt = self._output_format_var.get()
            if fmt:
                format_info_label.config(text=format_info(fmt))

        format_menu.bind("<<ComboboxSelected>>", lambda _e: _update_format_info())
        _update_format_info()

        # ── Quality preset ────────────────────────────────────────────────────
        tk.Label(
            self,
            text="Quality Preset:",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            font=styles.FONT_BODY,
        ).pack(anchor="w", pady=(8, 0))
        quality_menu = ttk.Combobox(
            self,
            textvariable=self._quality_preset_var,
            state="readonly",
            font=styles.FONT_BODY,
        )
        quality_menu["values"] = ("highest", "high", "medium", "low")
        quality_menu.pack(fill="x", pady=3)
        tk.Label(
            self,
            text="(Highest = best quality, larger files)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

        # ── Sample rate ──────────────────────────────────────────────────────
        tk.Label(
            self,
            text="Sample Rate:",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            font=styles.FONT_BODY,
        ).pack(anchor="w", pady=(8, 0))
        sr_menu = ttk.Combobox(
            self,
            textvariable=self._sample_rate_var,
            state="readonly",
            font=styles.FONT_BODY,
        )
        sr_menu["values"] = SAMPLE_RATE_PRESETS
        sr_menu.pack(fill="x", pady=3)
        tk.Label(
            self,
            text="(source = keep the input's original sample rate)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(anchor="w")

        # ── Bit depth (WAV output only) ───────────────────────────────────────
        tk.Label(
            self,
            text="Bit Depth:",
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
            font=styles.FONT_BODY,
        ).pack(anchor="w", pady=(8, 0))
        bd_menu = ttk.Combobox(
            self,
            textvariable=self._bit_depth_var,
            state="readonly",
            font=styles.FONT_BODY,
        )
        bd_menu["values"] = BIT_DEPTH_PRESETS
        bd_menu.pack(fill="x", pady=3)

        def _sync_bit_depth_state() -> None:
            enabled = self._output_format_var.get() == "wav"
            bd_menu.config(state="readonly" if enabled else "disabled")
            if not enabled and self._bit_depth_var.get() != "auto":
                self._bit_depth_var.set("auto")

        def _on_format_selected(_event: object) -> None:
            _update_format_info()
            _sync_bit_depth_state()

        hint = tk.Label(
            self,
            text="(WAV output only; auto = preserve the source depth)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        )
        hint.pack(anchor="w")
        format_menu.bind("<<ComboboxSelected>>", _on_format_selected)

        tk.Label(
            self,
            text="Post-Conversion Options:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(8, 0))
        tk.Checkbutton(
            self,
            text="Delete original files after successful conversion",
            variable=self._delete_originals_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(anchor="w", pady=2)
        tk.Label(
            self,
            text="⚠ Warning: Original files will be permanently deleted!",
            font=styles.FONT_CAPTION,
            fg="#cc0000",
            bg=styles.BG_WHITE,
        ).pack(anchor="w")
        tk.Checkbutton(
            self,
            text="Normalize MP3 output to target loudness (lossless, no re-encode)",
            variable=self._normalize_mp3_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(anchor="w", pady=(8, 0))
        lufs_frame = tk.Frame(self, bg=styles.BG_WHITE)
        lufs_frame.pack(anchor="w", fill="x", pady=(2, 0))
        tk.Label(
            lufs_frame,
            text="Target Loudness (LUFS):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT)
        tk.Entry(
            lufs_frame,
            textvariable=self._target_lufs_var,
            width=8,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, padx=(6, 0))
        tk.Label(
            lufs_frame,
            text="(e.g. -16.0; MP3 output only)",
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT, padx=(6, 0))
        tk.Checkbutton(
            self,
            text="Apply TPDF dither when reducing bit depth (WAV/AIFF)",
            variable=self._dither_var,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            selectcolor=styles.BG_WHITE,
            activebackground=styles.BG_WHITE,
            activeforeground=styles.FG_MAIN,
            font=styles.FONT_BODY,
        ).pack(anchor="w", pady=(8, 0))
        tk.Label(
            self,
            text=(
                "(recommended: prevents distortion when lowering depth; "
                "clear only if you need bit-identical legacy output)"
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            wraplength=700,
        ).pack(anchor="w")

        # ── Info box ──────────────────────────────────────────────────────────
        info_frame = tk.Frame(self, bg="#e8f4f8", relief=tk.RIDGE, bd=1)
        info_frame.pack(fill="x", pady=8)
        tk.Label(
            info_frame,
            text=(
                "ℹ Supported input formats: MP3, AAC, M4A, WAV, FLAC, "
                "OGG, OPUS, WMA, ALAC, APE, WV\n"
                "• All input files must be in the same format\n"
                "• Output format options automatically exclude the input format\n"
                "• Conversion maintains highest possible quality\n"
                "• Lossy to lossless conversion is automatically prevented"
            ),
            font=styles.FONT_CAPTION,
            bg="#e8f4f8",
            fg="#004466",
            justify=tk.LEFT,
            wraplength=700,
        ).pack(padx=10, pady=6)

        # ── Injected-callable factories ───────────────────────────────────────
        def update_detected_label(text: str, is_error: bool = False) -> None:
            color = "#cc0000" if is_error else styles.get_main()
            detected_label.config(text=text, fg=color)

        def update_format_menu(formats: list[Any], selected: str) -> None:
            format_menu["values"] = tuple(formats)
            self._output_format_var.set(selected)
            _update_format_info(selected)
            _sync_bit_depth_state()

        self.update_detected_label = update_detected_label
        self.update_format_menu = update_format_menu
        self.update_format_info = _update_format_info
        _sync_bit_depth_state()
