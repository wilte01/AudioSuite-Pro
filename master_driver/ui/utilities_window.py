"""
utilities_window.py — Builds the Utilities tab card area.

Cards are discovered via the ToolRegistry — adding a new utility tool to
the registry automatically adds its card here.

Changed in 2.0.0: the cards sit in a two-column grid rather than one tall
stack, the card whose Settings are open spans both columns, and the LAUNCH
button is pinned below the scrolling area instead of riding at the end of the
card list.  With seventeen utility tools a single column overflowed the
window before the last four cards and the launch button, so the tab now fits
and the primary action never scrolls out of reach (PLAN_feature_expansion.md
D119).

Changed in 2.1.0: a plugin tool without a card module gets the generic plugin card, and
select-all includes plugin tools.
"""

from __future__ import annotations

import importlib
import logging
import os
import tkinter as tk
from tkinter import filedialog
from typing import Callable

from audio_suite_shared import styles
from audio_suite_shared.plugin_system import get_plugins
from audio_suite_shared.tool_plugin import ToolManifest, get_registry

from ..state.app_state import AppState

_log = logging.getLogger(__name__)

# Mapping for cards whose module name doesn't follow the
# ``{tool_id}_card`` convention.  Key = manifest id, value = module name.
_CARD_MODULE_OVERRIDES: dict[str, str] = {
    "asx_extractor": "asx_card",
}


#: Cards per row inside the scroll area.  Two columns halve the stacked
#: height, which is what a seventeen-card list needs.
_CARD_COLUMNS = 2


class _CardCell(tk.Frame):
    """One grid cell holding one card, plus the hook the card reports to.

    A card's shell looks for ``on_card_expand`` on the frame it was built into
    (``_card_base._expansion_hook``), so the grid can hand the open card the
    full width without every card file learning about the layout.
    """

    def __init__(self, parent: tk.Misc, on_card_expand: Callable[[bool], None]) -> None:
        super().__init__(parent, bg=styles.BG_APP)
        self.on_card_expand = on_card_expand


def build(
    parent: tk.Frame,
    state: AppState,
    on_run: "Callable[[], None]",
    on_open_undo: "Callable[[], None] | None" = None,
) -> tk.Button:
    """Build the Utilities tab content. Returns the LAUNCH button.

    Cards are laid out in :data:`_CARD_COLUMNS` weighted columns in registry
    order; opening a card's Settings re-lays the grid so that card spans both
    columns and the cards after it continue on the following row.  The LAUNCH
    button is packed before the scroll area, so it keeps a strip at the bottom
    of the tab and cannot scroll away.

    Args:
        parent: The parent frame to pack into.
        state: The shared driver app state.
        on_run: Callback for the LAUNCH UTILITY PROCESS button.
        on_open_undo: Callback that opens the Undo Tag Edits window, or
            ``None`` to render the undo card without a live button.
    """
    # ── Pinned launch button ─────────────────────────────────────────────────
    # Packed first (side=BOTTOM) so the canvas below takes the remaining space;
    # it is the tab's primary action and must not need scrolling to reach.
    launch_frame = tk.Frame(parent, bg=styles.BG_APP)
    launch_frame.pack(side=tk.BOTTOM, fill="x", padx=20, pady=(8, 12))
    util_run_btn = tk.Button(
        launch_frame,
        text="LAUNCH UTILITY PROCESS",
        font=styles.FONT_TITLE,
        bg=styles.get_main(),
        fg="white",
        height=2,
        command=on_run,
    )
    util_run_btn.pack(fill="x", expand=True)

    canvas = tk.Canvas(parent, bg=styles.BG_APP, highlightthickness=0)
    scrollbar = tk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    scroll_frame = tk.Frame(canvas, bg=styles.BG_APP)

    window_id = canvas.create_window((0, 0), window=scroll_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side="left", fill="both", expand=True, padx=(20, 0), pady=10)
    scrollbar.pack(side="right", fill="y", padx=(0, 5))

    # Stretch scroll_frame to fill the full canvas width
    canvas.bind("<Configure>", lambda e: canvas.itemconfig(window_id, width=e.width))

    def _sync_scrollregion(_event: "tk.Event[tk.Misc] | None" = None) -> None:
        canvas.configure(scrollregion=canvas.bbox("all"))

    scroll_frame.bind("<Configure>", _sync_scrollregion)

    grid_host = tk.Frame(scroll_frame, bg=styles.BG_APP)
    grid_host.pack(fill="x")
    for column in range(_CARD_COLUMNS):
        grid_host.columnconfigure(column, weight=1, uniform="util_card")
    grid_host.bind("<Configure>", _sync_scrollregion)

    cells: list[_CardCell] = []
    expanded: dict[_CardCell, bool] = {}

    def _relayout() -> None:
        """Place every card again, open cards spanning the full width."""
        for cell in cells:
            cell.grid_forget()
        row = column = 0
        for cell in cells:
            span = _CARD_COLUMNS if expanded.get(cell, False) else 1
            cell.grid(row=row, column=column, columnspan=span, sticky="new")
            column += span
            if column >= _CARD_COLUMNS:
                column = 0
                row += 1
        # Re-gridding can change the content height without changing the
        # scroll frame's own size, so the scrollregion is refreshed explicitly.
        canvas.after_idle(_sync_scrollregion)

    def _add_cell() -> _CardCell:
        """Create the next cell, wired to reflow the grid when its card opens."""
        holder: list[_CardCell] = []

        def _on_card_expand(is_open: bool) -> None:
            opened = holder[0]
            expanded[opened] = is_open
            _relayout()

        cell = _CardCell(grid_host, _on_card_expand)
        holder.append(cell)
        cells.append(cell)
        expanded[cell] = False
        return cell

    # Build cards in registry order for the "utility" category. A plugin that
    # ships only a CLI entry point has no launcher for the driver to open, so
    # it gets no cell at all rather than an empty one.
    registry = get_registry()
    for manifest in registry.driver_by_category("utility"):
        cell = _add_cell()
        if manifest.id == "converter":
            # converter card has extra callbacks — handle specially
            _build_converter_card(cell, state)
        elif manifest.id == "undo_tag_edits":
            # undo card has a dedicated open callback — handle specially
            _build_undo_card(cell, state, on_open_undo)
        else:
            _build_card(manifest.id, cell, state)
        if not cell.winfo_children():
            # No card was built (a failed import, or undo without a callback).
            # Drop the cell so the grid keeps no empty slot.
            cells.remove(cell)
            del expanded[cell]
            cell.destroy()

    _relayout()

    canvas.bind(
        "<MouseWheel>",
        lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
    )

    return util_run_btn


def _build_card(tool_id: str, parent: tk.Frame, state: AppState) -> None:
    """Build the card for *tool_id*, plugin-aware.

    A first-party tool is looked up by its module name, as it always has been.
    A plugin supplies its own builder through ``[tool.ui].entry``; if it ships
    none (or that builder fails), the generic plugin card renders instead, so
    the tool is always reachable from the tab.

    Args:
        tool_id: The manifest id of the card to build.
        parent: The cell the card is built into.
        state: The Master Driver state holding the module toggles.
    """
    mod_name = _CARD_MODULE_OVERRIDES.get(tool_id, f"{tool_id}_card")
    try:
        mod = importlib.import_module(f"master_driver.ui.cards.{mod_name}")
        mod.build(parent, state)
        return
    except (ImportError, AttributeError) as exc:
        manifest = get_registry().get(tool_id)
        if manifest is None or not manifest.plugin:
            _log.warning("No card UI for tool %r: %s", tool_id, exc)
            return
    _build_plugin_card(manifest, parent, state)


def _build_plugin_card(
    manifest: ToolManifest, parent: tk.Frame, state: AppState
) -> None:
    """Build a plugin's own card, falling back to the generic one.

    Args:
        manifest: The plugin's tool manifest.
        parent: The cell the card is built into.
        state: The Master Driver state holding the module toggles.
    """
    if manifest.ui_entry:
        try:
            hook = get_plugins().resolve(manifest.ui_entry)
            hook(parent, state)
            return
        except Exception as exc:  # a third-party card must not kill the tab
            _log.warning(
                "Plugin card for %r failed (%s); using the generic card",
                manifest.id,
                exc,
            )
    from .cards import plugin_card

    plugin_card.build(parent, state, manifest)


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

    # The converter's own scanner owns the rules: it walks subfolders,
    # accepts mixed source formats, and reports the per-format counts.
    from music_format_converter.core.formats import scan_input_directory

    result = scan_input_directory(dir_path)

    if not result.ok:
        _log.warning(
            "Format discovery failed for %s: %s",
            dir_path,
            result.error_message,
            exc_info=True,
        )
        state.converter_available_formats = list(state.converter_all_formats)
        if format_menu:
            format_menu["values"] = tuple(state.converter_all_formats)
        if detected_label:
            detected_label.config(text="")
        return

    if not result.file_count:
        state.converter_available_formats = list(state.converter_all_formats)
        if format_menu:
            format_menu["values"] = tuple(state.converter_all_formats)
        if detected_label:
            detected_label.config(
                text="\u26a0 No audio files found", fg=styles.COLOR_ERROR
            )
        return

    if detected_label:
        detected_label.config(
            text=result.status_text,
            fg=styles.COLOR_SUCCESS,
        )

    state.converter_available_formats = list(result.output_formats)

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
