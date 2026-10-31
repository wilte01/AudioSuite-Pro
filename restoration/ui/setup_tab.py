"""Setup tab for the Restoration (declip) tool.

Two controls, both measured: how close to the file's own peak a sample must sit
to count as clipped, and how wide a plateau may be before it is reported rather
than reconstructed.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared import styles, ui_common
from audio_suite_shared.ui_common import BaseSetupFrame

from ..core.declipper import DEFAULT_MAX_RUN_MS, DEFAULT_THRESHOLD


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    threshold: tk.DoubleVar,
    max_run: tk.IntVar,
    on_browse: Callable[[], None],
    on_start: Callable[[], None],
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    preset_names: list[str] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
    clear_logs_var: tk.BooleanVar | None = None,
    parallel_var: tk.BooleanVar | None = None,
    driver_locked: bool = False,
) -> dict[str, Any]:
    """Populate the Setup tab and return the widgets the window drives.

    Args:
        parent: The notebook frame to build into.
        folder_path: Bound to the source directory entry in the strip.
        run_mode: Bound to the strip's Mode combobox.
        threshold: Bound to the clipping-threshold slider (0.50-1.00).
        max_run: Bound to the maximum plateau width slider (1-100 ms).
        on_browse: Callback for the strip's Browse button.
        on_start: Callback for the start button.
        auto_start_var: Mirror of the driver's Auto Start.
        auto_end_var: Mirror of the driver's Auto End.
        preset_names: Saved preset names for the combobox.
        on_save_preset: Callback to save the current settings as a preset.
        on_delete_preset: Callback to delete a named preset.
        on_preset_selected: Callback when a preset is picked.
        clear_logs_var: Mirror of Clear Logs (display only).
        parallel_var: Mirror of Parallel (display only).
        driver_locked: True when the Master Driver launched this window.

    Returns:
        The widget dict from ``BaseSetupFrame.get_widgets`` plus ``setup_frame``.
    """
    frame = _SetupFrame(
        parent,
        title="Restoration (Declip)",
        start_text="BEGIN DECLIP",
        on_start=on_start,
        folder_path=folder_path,
        run_mode=run_mode,
        auto_start_var=auto_start_var,
        auto_end_var=auto_end_var,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
        on_browse=on_browse,
        driver_locked=driver_locked,
        preset_names=preset_names,
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
        threshold=threshold,
        max_run=max_run,
    )
    widgets = frame.get_widgets()
    widgets["setup_frame"] = frame
    return widgets


class _SetupFrame(BaseSetupFrame):
    """Restoration Setup tab on the shared ``BaseSetupFrame``."""

    def __init__(
        self,
        parent: tk.Frame,
        *,
        threshold: tk.DoubleVar,
        max_run: tk.IntVar,
        **kwargs: Any,
    ) -> None:
        # Bound before super().__init__, which calls _layout() -> _build_options().
        self._threshold = threshold
        self._max_run = max_run
        super().__init__(parent, **kwargs)

    def _build_options(self) -> None:
        """Emit the detection and reconstruction controls."""
        group = self.add_config_group("Configuration")

        ui_common.slider_row(
            group, "Clipping threshold", self._threshold, 0.50, 1.00, 0.01
        )
        ui_common.slider_row(group, "Max plateau width (ms)", self._max_run, 1, 100, 1)

        tk.Label(
            group,
            text=(
                "A plateau is only repaired when the samples either side are "
                "cleaner than it, and only when the reconstruction can rise above "
                "it without exceeding full scale. Everything else is reported as "
                "skipped and left byte-identical, so a file with no clipping is "
                "never rewritten."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            justify=tk.LEFT,
            anchor="w",
            wraplength=760,
        ).pack(fill="x", pady=(4, 4))

        tk.Label(
            self,
            text=(
                f"Defaults: threshold {DEFAULT_THRESHOLD:.2f} of the file's own "
                f"peak, plateau width {DEFAULT_MAX_RUN_MS} ms. A ceiling at "
                "0 dBFS cannot be restored above full scale, so those plateaus "
                "are counted rather than invented."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            justify=tk.LEFT,
            anchor="w",
            wraplength=760,
        ).pack(fill="x", pady=(6, 4))
