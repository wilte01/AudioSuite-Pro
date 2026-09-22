"""
setup_tab.py
Builds the Setup tab for Audio Normalizer.
Returns the Start button so the app can enable/disable it.
"""

import tkinter as tk
from tkinter import ttk
from typing import Any, Callable, cast

from audio_suite_shared import styles, ui_common
from audio_suite_shared.cli_dataclasses import VALID_TARGET_LUFS_VALUES
from audio_suite_shared.ui_common import BaseSetupFrame


def _closest_lufs_index(value: float) -> int:
    """Map a LUFS value to the index of its matching permitted preset.

    Args:
        value: A LUFS value expected to already match one of the entries
            in VALID_TARGET_LUFS_VALUES (callers pass in values that have
            been validated upstream via ``validate_target_lufs``).

    Returns:
        Index into VALID_TARGET_LUFS_VALUES of the closest preset.
    """
    return min(
        range(len(VALID_TARGET_LUFS_VALUES)),
        key=lambda i: abs(VALID_TARGET_LUFS_VALUES[i] - value),
    )


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    target_lufs: tk.DoubleVar,
    tolerance: tk.DoubleVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    preset_names: list[str] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
) -> tuple[tk.Button, Callable[[list[str]], None], ttk.Combobox]:
    """
    Populate the Setup tab and return the Start button widget.
    """
    frame = _SetupFrame(
        parent,
        title="Audio Normalizer - Optimized",
        start_text="BEGIN NORMALIZATION",
        on_start=on_start,
        include_controls_panel=False,
        folder_path=folder_path,
        run_mode=run_mode,
        preset_names=preset_names,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
        target_lufs=target_lufs,
        tolerance=tolerance,
        on_browse=on_browse,
    )
    return (
        cast(tk.Button, frame.start_btn),
        cast(Callable[[list[str]], None], frame.refresh_preset_list),
        cast(ttk.Combobox, frame.preset_combo),
    )


class _SetupFrame(BaseSetupFrame):
    """Audio Normalizer Setup tab skeleton on the shared BaseSetupFrame."""

    def __init__(
        self,
        parent: tk.Frame,
        *,
        target_lufs: tk.DoubleVar,
        tolerance: tk.DoubleVar,
        **kwargs: Any,
    ) -> None:
        # Tool-specific option state must be bound before super().__init__,
        # which calls _layout() -> _build_options() during construction.
        self._target_lufs = target_lufs
        self._tolerance = tolerance
        # The base requires the run-controls panel auto-checkbox variables even
        # when the panel itself is not built (include_controls_panel=False);
        # provide inert placeholders so the skeleton constructs cleanly.
        kwargs.setdefault("auto_start_var", tk.BooleanVar(master=parent))
        kwargs.setdefault("auto_end_var", tk.BooleanVar(master=parent))
        super().__init__(parent, **kwargs)

    def _build_options(self) -> None:
        # Folder selection
        on_browse = cast(Callable[[], None], self._on_browse)
        ui_common.path_row(self, "Music Directory:", self._folder_path, on_browse)

        # Configuration LabelFrame
        cfg_frame = self.add_config_group("Configuration")
        build_config_panel(
            cfg_frame, self._run_mode, self._target_lufs, self._tolerance
        )


def build_config_panel(
    parent: tk.Misc,
    run_mode: tk.StringVar | None,
    target_lufs: tk.DoubleVar,
    tolerance: tk.DoubleVar,
) -> None:
    """Reusable configuration panel for Audio Normalizer.

    The Target LUFS control is a slider restricted to the five permitted
    preset values: -12.0, -14.0, -16.0, -18.0, -23.0.  Because those presets
    are not evenly spaced (2.0 LUFS apart for the first four, then 5.0 LUFS
    to the last), the slider operates on the preset's *index* (0-4, evenly
    spaced stops) rather than directly on the LUFS value — free-form values
    between presets are unreachable, and the backing DoubleVar is only ever
    set to one of the five permitted values. The readout label always shows
    the actual LUFS value for the selected index, not the index itself.

    Args:
        parent: Parent frame to populate.
        run_mode: StringVar for execution mode, or None when embedded in
            Audio Refinery (mode selection is suppressed).
        target_lufs: DoubleVar that holds the currently selected LUFS preset.
        tolerance: DoubleVar for the skip-tolerance value.
    """
    # Mode selection (only show when not embedded)
    if run_mode is not None:
        mode_row = tk.Frame(parent, bg=styles.BG_WHITE)
        mode_row.pack(fill="x", pady=5)
        tk.Label(
            mode_row,
            text="Select Mode:",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(side=tk.LEFT)
        mode_menu = ttk.Combobox(
            mode_row, textvariable=run_mode, state="readonly", font=styles.FONT_BODY
        )
        mode_menu["values"] = ("Dry Run", "Normalize", "Lossless Normalize")
        mode_menu.pack(side=tk.LEFT, padx=10)

    # Target LUFS — index-based slider restricted to permitted presets.
    # Built locally (rather than via ui_common.slider_row) because the five
    # presets are unevenly spaced: the slider must snap across preset
    # *index* (0-4), not the raw LUFS value, and the readout must display
    # the resolved LUFS value rather than the index. slider_row's generic
    # value-scale API doesn't support that index<->value indirection, and
    # extending it would affect every other tool that shares it.
    lufs_row = tk.Frame(parent, bg=styles.BG_WHITE)
    lufs_row.pack(fill="x", pady=1)

    tk.Label(
        lufs_row,
        text="Target LUFS:",
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        width=28,
        anchor="w",
    ).pack(side=tk.LEFT)

    # IntVar drives the slider position (preset index); the caller's
    # target_lufs DoubleVar is only ever set to one of the five permitted
    # values, resolved from that index.
    _lufs_index_var = tk.IntVar(value=_closest_lufs_index(target_lufs.get()))
    _lufs_readout_var = tk.StringVar(
        value=f"{VALID_TARGET_LUFS_VALUES[_lufs_index_var.get()]:.1f}"
    )

    def _on_lufs_index_changed(*_trace_args: object) -> None:
        selected = VALID_TARGET_LUFS_VALUES[_lufs_index_var.get()]
        target_lufs.set(selected)
        _lufs_readout_var.set(f"{selected:.1f}")

    # A variable trace is used instead of Scale's `command` option: Tk only
    # invokes `command` in response to live mouse/keyboard interaction, not
    # programmatic `.set()` calls on the widget or the variable — a trace
    # fires on any change to the index, regardless of source.
    _lufs_index_var.trace_add("write", _on_lufs_index_changed)

    tk.Scale(
        lufs_row,
        from_=0,
        to=len(VALID_TARGET_LUFS_VALUES) - 1,
        resolution=1,
        orient=tk.HORIZONTAL,
        variable=_lufs_index_var,
        showvalue=False,
        bg=styles.BG_WHITE,
        fg=styles.FG_MAIN,
        troughcolor=styles.BG_LIGHT,
        highlightthickness=0,
        font=styles.FONT_CAPTION,
        length=220,
    ).pack(side=tk.LEFT, padx=6)

    tk.Label(
        lufs_row,
        textvariable=_lufs_readout_var,
        font=styles.FONT_CAPTION,
        bg=styles.BG_WHITE,
        fg=styles.FG_SUB,
        width=6,
    ).pack(side=tk.LEFT)

    tk.Label(
        lufs_row,
        text="LUFS",
        font=styles.FONT_CAPTION,
        fg=styles.FG_SUB,
        bg=styles.BG_WHITE,
    ).pack(side=tk.LEFT)

    # Tolerance
    ui_common.slider_row(parent, "Tolerance (LUFS)", tolerance, 0.1, 2.0, 0.1)

    tk.Label(
        parent,
        text="(Files within ± tolerance of target will be skipped)",
        font=styles.FONT_CAPTION,
        fg=styles.FG_SUB,
        bg=styles.BG_WHITE,
    ).pack(anchor="w", padx=5)
