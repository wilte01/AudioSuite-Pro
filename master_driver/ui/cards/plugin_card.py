"""plugin_card.py — the generic card for a plugin tool.

A plugin may ship its own card (``[tool.ui].entry`` in its manifest) or none at
all.  This module is the none-at-all case: without it the Utilities tab would
find no ``master_driver.ui.cards.{id}_card`` module, log

    No card UI for tool '<id>'

and drop the cell, so the plugin would be selected nowhere and silently
unreachable.  The card reuses the shared declarative shell, so a plugin looks
like every other tool in the tab and still carries the description and origin a
user needs to tell where it came from.

The signature is ``build(parent, state, manifest)`` rather than the discovered
``build(parent, state)``: this module is called directly by the tab, never
looked up by card filename, because a plugin id is not a first-party tool id.

Changed in 2.1.0: new module — the generic plugin card (Sprint 7, Item 7.1).
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from audio_suite_shared.tool_plugin import ToolManifest

from ._card_base import CardCaption, SimpleCardSpec, build_simple_card

if TYPE_CHECKING:
    from ...state.app_state import AppState


def build(parent: tk.Frame, state: "AppState", manifest: ToolManifest) -> None:
    """Render the generic card for a plugin tool.

    Args:
        parent: The cell the tab builds cards into.
        state: The Master Driver state holding the module toggles.
        manifest: The plugin's tool manifest, for the title and description.
    """
    description = manifest.description or "A plugin tool."
    origin = manifest.origin or "plugins/"
    build_simple_card(
        parent,
        state,
        SimpleCardSpec(
            toggle=f"module_toggles:{manifest.id}",
            title=manifest.name,
            description=description,
            rows=(
                CardCaption(
                    f"Plugin card (generic): this tool ships no UI entry, so the "
                    f"driver renders this one. Installed from {origin}.",
                    wraplength=460,
                ),
            ),
        ),
    )
