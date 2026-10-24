"""
ui/enrich_tab.py
Builds the ENRICH tab — tag and metadata tools only.

Modules are stacked in a single column, each as a collapsible panel
matching the style used in the REFINE section (audio_refinery setup_tab).

Cards are discovered dynamically via the ToolRegistry — adding a new
enrich tool to the registry automatically adds its card here.

Changed in 2.1.0: a plugin tool without a card module gets the generic plugin card.
"""

from __future__ import annotations

import importlib
import logging
import tkinter as tk
from typing import Callable

from audio_suite_shared import styles
from audio_suite_shared.plugin_system import get_plugins
from audio_suite_shared.tool_plugin import get_registry

from ..state.app_state import AppState

_log = logging.getLogger(__name__)


def build(parent: tk.Frame, state: AppState, on_run: "Callable[[], None]") -> tk.Button:
    """
    Build the Enrich tab content into parent.
    Returns the LAUNCH button so app.py can disable/enable it.
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

    # Build cards in registry order for the "enrich" category. A CLI-only
    # plugin has no launcher for the driver to open, so it gets no card.
    registry = get_registry()
    for manifest in registry.driver_by_category("enrich"):
        _build_card(manifest.id, scroll_frame, state)

    # ── Launch button ─────────────────────────────────────────────────────────
    btn_frame = tk.Frame(scroll_frame, bg=styles.BG_APP)
    btn_frame.pack(fill="x", pady=20, padx=2)
    run_btn = tk.Button(
        btn_frame,
        text="LAUNCH ENRICH PROCESS",
        font=styles.FONT_TITLE,
        bg=styles.get_main(),
        fg="white",
        height=2,
        command=on_run,
    )
    run_btn.pack(fill="x", expand=True)

    canvas.bind(
        "<MouseWheel>",
        lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"),
    )

    return run_btn


def _build_card(tool_id: str, parent: tk.Frame, state: AppState) -> None:
    """Build the card for *tool_id*, plugin-aware.

    Convention: card modules live at
    ``master_driver.ui.cards.{tool_id}_card`` and expose a ``build(parent,
    state)`` function.  A plugin tool instead supplies ``[tool.ui].entry`` in
    its manifest, and falls back to the generic plugin card when it ships none.

    Args:
        tool_id: The manifest id of the card to build.
        parent: The frame the card is built into.
        state: The Master Driver state holding the module toggles.
    """
    try:
        mod = importlib.import_module(f"master_driver.ui.cards.{tool_id}_card")
        mod.build(parent, state)
        return
    except (ImportError, AttributeError) as exc:
        manifest = get_registry().get(tool_id)
        if manifest is None or not manifest.plugin:
            _log.warning("No card UI for tool %r: %s", tool_id, exc)
            return
    if manifest.ui_entry:
        try:
            get_plugins().resolve(manifest.ui_entry)(parent, state)
            return
        except Exception as exc:  # a third-party card must not kill the tab
            _log.warning(
                "Plugin card for %r failed (%s); using the generic card",
                manifest.id,
                exc,
            )
    from .cards import plugin_card

    plugin_card.build(parent, state, manifest)
