"""ui.py — the example plugin's Master Driver card.

``MANIFEST.toml`` points ``[tool.ui].entry`` here, and the Utilities tab calls
:func:`build(parent, state)` exactly as it calls a first-party card module.  The
card is rendered through the suite's shared ``build_simple_card`` shell, so a
plugin card looks like the rest of the driver without copying any widget code.

A plugin that declares no ``ui.entry`` is still reachable: the driver renders
its generic plugin card.  Declaring one is how a plugin gets a body of its own.

Changed in 2.1.0: new module — the example plugin's card (Item 7.2).
"""

from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

from master_driver.ui.cards._card_base import (
    CardCaption,
    SimpleCardSpec,
    build_simple_card,
)

if TYPE_CHECKING:
    from master_driver.state.app_state import AppState

#: The toggle key the driver generates for every registry manifest, plugin or
#: not (``AppState.module_toggles[<tool id>]``).
TOGGLE_REFERENCE = "module_toggles:example_tool"


def build(parent: tk.Frame, state: "AppState") -> None:
    """Render the example tool's card into *parent*.

    Args:
        parent: The frame the Utilities tab hands to the card.
        state: The Master Driver state holding the module toggles.
    """
    build_simple_card(
        parent,
        state,
        SimpleCardSpec(
            toggle=TOGGLE_REFERENCE,
            title="Example Tool",
            description=(
                "Plugin card: this body comes from the plugin's own "
                "ui entry, not from master_driver.ui.cards."
            ),
            rows=(
                CardCaption(
                    "Select the utility on the left, then use LAUNCH UTILITY to "
                    "open the plugin's window."
                ),
            ),
        ),
    )
