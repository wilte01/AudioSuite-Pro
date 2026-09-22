"""
ui/enrich_tab.py
Builds the ENRICH tab — tag and metadata tools only.

Modules are stacked in a single column, each as a collapsible panel
matching the style used in the REFINE section (audio_refinery setup_tab).

Cards are discovered dynamically via the ToolRegistry — adding a new
enrich tool to the registry automatically adds its card here.
"""

from __future__ import annotations

import importlib
import logging
import tkinter as tk
from typing import Callable

from audio_suite_shared import styles
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

    # Build cards in registry order for the "enrich" category
    registry = get_registry()
    for manifest in registry.by_category("enrich"):
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
    """Lazy-import the card module for *tool_id* and call its ``build()``.

    Convention: card modules live at
    ``master_driver.ui.cards.{tool_id}_card`` and expose a ``build(parent,
    state)`` function.
    """
    try:
        mod = importlib.import_module(f"master_driver.ui.cards.{tool_id}_card")
        mod.build(parent, state)
    except (ImportError, AttributeError) as exc:
        _log.warning("No card UI for tool %r: %s", tool_id, exc)
