"""Setup tab for the Duplicate Finder.

The shared ``BaseSetupFrame`` supplies the title, the Run Controls strip (source
row, Mode combobox, Browse, the driver's orchestration display) and the
full-width start button; this module adds the two controls the tool owns: the
similarity threshold and the quarantine folder.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any, Callable

from audio_suite_shared import styles, ui_common
from audio_suite_shared.ui_common import BaseSetupFrame

from ..core.models import DEFAULT_THRESHOLD


def build(
    parent: tk.Frame,
    folder_path: tk.StringVar,
    run_mode: tk.StringVar,
    threshold: tk.DoubleVar,
    quarantine_dir: tk.StringVar,
    auto_start_var: tk.BooleanVar,
    auto_end_var: tk.BooleanVar,
    clear_logs_var: tk.BooleanVar,
    parallel_var: tk.BooleanVar,
    on_browse: Callable[[], None],
    on_browse_quarantine: Callable[[], None],
    on_start: Callable[[], None],
    preset_names: list[str] | None = None,
    on_save_preset: Callable[[str], None] | None = None,
    on_delete_preset: Callable[[str], None] | None = None,
    on_preset_selected: Callable[[str], None] | None = None,
    driver_locked: bool = False,
) -> dict[str, Any]:
    """Populate the Setup tab and return the widgets the window drives.

    Args:
        parent: The notebook frame to build into.
        folder_path: Bound to the source directory entry in the strip.
        run_mode: Bound to the strip's Mode combobox.
        threshold: Bound to the similarity slider (0.02-0.40).
        quarantine_dir: Bound to the quarantine folder entry.
        auto_start_var: Mirror of the driver's Auto Start.
        auto_end_var: Mirror of the driver's Auto End.
        clear_logs_var: Mirror of Clear Logs (display only).
        parallel_var: Mirror of Parallel (display only).
        on_browse: Callback for the strip's Browse button.
        on_browse_quarantine: Callback for the quarantine folder's Browse.
        on_start: Callback for the start button.
        preset_names: Saved preset names for the combobox.
        on_save_preset: Callback to save the current settings as a preset.
        on_delete_preset: Callback to delete a named preset.
        on_preset_selected: Callback when a preset is picked.
        driver_locked: True when the Master Driver launched this window.

    Returns:
        The widget dict from ``BaseSetupFrame.get_widgets`` plus ``setup_frame``.
    """
    frame = _SetupFrame(
        parent,
        title="Duplicate Finder",
        start_text="SCAN FOR DUPLICATES",
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
        quarantine_dir=quarantine_dir,
        on_browse_quarantine=on_browse_quarantine,
    )
    widgets = frame.get_widgets()
    widgets["setup_frame"] = frame
    return widgets


class _SetupFrame(BaseSetupFrame):
    """Duplicate Finder Setup tab on the shared ``BaseSetupFrame``."""

    def __init__(
        self,
        parent: tk.Frame,
        *,
        threshold: tk.DoubleVar,
        quarantine_dir: tk.StringVar,
        on_browse_quarantine: Callable[[], None],
        **kwargs: Any,
    ) -> None:
        # Bound before super().__init__, which calls _layout() -> _build_options().
        self._threshold = threshold
        self._quarantine_dir = quarantine_dir
        self._on_browse_quarantine = on_browse_quarantine
        super().__init__(parent, **kwargs)

    def _build_options(self) -> None:
        """Emit the similarity threshold and the quarantine destination."""
        group = self.add_config_group("Comparison")

        ui_common.slider_row(
            group, "Similarity threshold", self._threshold, 0.02, 0.40, 0.01
        )
        tk.Label(
            group,
            text=(
                "Lower is stricter: two files are one recording only when their "
                "fingerprints agree within this bit-error rate. The default "
                f"{DEFAULT_THRESHOLD:.2f} was measured on a reference set where "
                "the same recording at different bitrates scored 0.0000-0.0002 "
                "and the closest distinct recording scored 0.1580."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            justify=tk.LEFT,
            anchor="w",
            wraplength=760,
        ).pack(fill="x", pady=(4, 8))

        tk.Label(
            group,
            text="Quarantine folder (a live run moves duplicates here):",
            font=styles.FONT_BODY,
            fg=styles.FG_MAIN,
            bg=styles.BG_WHITE,
        ).pack(anchor="w", pady=(6, 0))

        row = tk.Frame(group, bg=styles.BG_WHITE)
        row.pack(fill="x", pady=3)
        tk.Entry(
            row,
            textvariable=self._quarantine_dir,
            font=styles.FONT_BODY,
            bg=styles.BG_WHITE,
            fg=styles.FG_MAIN,
            insertbackground=styles.FG_MAIN,
        ).pack(side=tk.LEFT, fill="x", expand=True, padx=(0, 5))
        tk.Button(
            row,
            text="Browse...",
            bg=styles.get_main(),
            fg="white",
            font=styles.FONT_BUTTON,
            command=self._on_browse_quarantine,
        ).pack(side=tk.RIGHT)

        tk.Label(
            self,
            text=(
                "Nothing is deleted. A dry run reports every duplicate it found "
                "and moves nothing; a live run moves the extra copies into the "
                "quarantine folder, records the move for Undo Tag Edits, and "
                "leaves the kept copy untouched."
            ),
            font=styles.FONT_CAPTION,
            fg=styles.FG_SUB,
            bg=styles.BG_WHITE,
            justify=tk.LEFT,
            anchor="w",
            wraplength=760,
        ).pack(fill="x", pady=(6, 4))
