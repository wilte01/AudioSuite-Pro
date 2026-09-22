"""
utilities_window.py — Builds the Utilities tab card area.

Cards are discovered via the ToolRegistry — adding a new utility tool to
the registry automatically adds its card here.
"""

from __future__ import annotations

import importlib
import logging
import os
import tkinter as tk
from tkinter import filedialog
from typing import Callable

from audio_suite_shared import styles
from audio_suite_shared.tool_plugin import get_registry

from ..state.app_state import AppState

_log = logging.getLogger(__name__)

# Mapping for cards whose module name doesn't follow the
# ``{tool_id}_card`` convention.  Key = manifest id, value = module name.
_CARD_MODULE_OVERRIDES: dict[str, str] = {
    "asx_extractor": "asx_card",
}


def build(
    parent: tk.Frame,
    state: AppState,
    on_run: "Callable[[], None]",
    on_open_undo: "Callable[[], None] | None" = None,
) -> tk.Button:
    """Build the Utilities tab content. Returns the LAUNCH button.

    Args:
        parent: The parent frame to pack into.
        state: The shared driver app state.
        on_run: Callback for the LAUNCH UTILITY PROCESS button.
        on_open_undo: Callback that opens the Undo Tag Edits window, or
            ``None`` to render the undo card without a live button.
    """
    canvas = tk.Canvas(parent, bg=styles.BG_APP, highlightthickness=0)
    scrollbar = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    scroll_frame = tk.Frame(canvas, bg=styles.BG_APP)

    scroll_frame.bind(
        "<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )
    window_id = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=10)
    scrollbar.pack(side="right", fill="y", padx=(0, 5))

    # Stretch scroll_frame to fill the full canvas width
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))

    # Build cards in registry order for the "utility" category
    registry = get_registry()
    for manifest in registry.by_category("utility"):
        if manifest.id == "converter":
            # converter card has extra callbacks — handle specially
            _build_converter_card(scroll_frame, state)
        elif manifest.id == "undo_tag_edits":
            # undo card has a dedicated open callback — handle specially
            _build_undo_card(scroll_frame, state, on_open_undo)
        else:
            _build_card(manifest.id, scroll_frame, state)

    # ── Launch button ─────────────────────────────────────────────────────────
    btn_frame = tk.Frame(scroll_frame, bg=styles.BG_APP)
    btn_frame.pack(fill="x", pady=20, padx=2)
    util_run_btn = tk.Button(
        btn_frame,
        text="LAUNCH UTILITY PROCESS",
        font=styles.FONT_TITLE,
        bg=styles.get_main(),
        fg="white",
        height=2,
        command=on_run,
    )
    util_run_btn.pack(fill="x", expand=True)

    canvas.bind(
        "<MouseWheel>",
        lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
    )

    return util_run_btn


def _build_card(tool_id: str, parent: tk.Frame, state: AppState) -> None:
    """Lazy-import the card module for *tool_id* and call ``build(parent, state)``."""
    mod_name = _CARD_MODULE_OVERRIDES.get(tool_id, f"{tool_id}_card")
    try:
        mod = importlib.import_module(f"master_driver.ui.cards.{mod_name}")
        mod.build(parent, state)
    except (ImportError, AttributeError) as exc:
        _log.warning("No card UI for tool %r: %s", tool_id, exc)


def _build_converter_card(parent: tk.Frame, state: AppState) -> None:
    """Build the converter card with its extra callbacks."""
    from .cards import converter_card

    converter_card.build(
        parent,
        state,
        on_browse_output=lambda: _browse_output(state),
        on_toggle=lambda: update_format_detection(state),
    )


def _build_undo_card(
    parent: tk.Frame,
    state: AppState,
    on_open: "Callable[[], None] | None" = None,
) -> None:
    """Build the Undo Tag Edits card with its dedicated open callback."""
    from .cards import undo_tag_edits_card

    if on_open is None:
        return
    undo_tag_edits_card.build(parent, state, on_open)


def _browse_output(state: AppState) -> None:
    folder = filedialog.askdirectory()
    if folder:
        state.converter_output_dir.set(folder)


def update_format_detection(state: AppState) -> None:
    dir_path = state.dir_path.get()
    detected_label = getattr(state, "_converter_detected_label", None)
    format_menu = getattr(state, "_converter_format_menu", None)

    if not dir_path or not os.path.isdir(dir_path):
        if detected_label:
            detected_label.config(text="")
        return

    detected_formats = set()
    file_count = 0
    try:
        for entry in os.scandir(dir_path):
            if entry.is_file():
                ext = entry.name.lower().rsplit(".", 1)[-1]
                if ext in state.converter_all_formats:
                    detected_formats.add(ext)
                    file_count += 1
    except (OSError, tk.TclError) as _exc:
        _log.warning("Format discovery failed, using defaults: %s", _exc, exc_info=True)
        state.converter_available_formats = list(state.converter_all_formats)
        if format_menu:
            format_menu["values"] = tuple(state.converter_all_formats)
        if detected_label:
            detected_label.config(text="")
        return

    if not detected_formats:
        state.converter_available_formats = list(state.converter_all_formats)
        if format_menu:
            format_menu["values"] = tuple(state.converter_all_formats)
        if detected_label:
            detected_label.config(
                text="\u26a0 No audio files found", fg=styles.COLOR_ERROR
            )
        return

    if len(detected_formats) > 1:
        fmt_list = ", ".join(sorted(detected_formats))
        if detected_label:
            detected_label.config(
                text=f"\u26a0 Mixed formats ({fmt_list})", fg=styles.COLOR_ERROR
            )
        state.converter_available_formats = []
        if format_menu:
            format_menu["values"] = tuple([])
        return

    input_format = list(detected_formats)[0]
    if detected_label:
        detected_label.config(
            text=f"\u2713 Detected: {file_count} {input_format.upper()} file(s)",
            fg=styles.COLOR_SUCCESS,
        )

    is_lossy = input_format in state.converter_lossy_formats
    if is_lossy:
        state.converter_available_formats = [
            f for f in state.converter_lossy_formats if f != input_format
        ]
    else:
        state.converter_available_formats = [
            f for f in state.converter_all_formats if f != input_format
        ]

    if format_menu:
        format_menu["values"] = tuple(state.converter_available_formats)
        current = state.converter_output_format.get()
        if current not in state.converter_available_formats:
            if state.converter_available_formats:
                new_fmt = (
                    "mp3"
                    if "mp3" in state.converter_available_formats
                    else state.converter_available_formats[0]
                )
                state.converter_output_format.set(new_fmt)
            else:
                state.converter_output_format.set("")
