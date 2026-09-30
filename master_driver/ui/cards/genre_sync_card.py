"""Genre Sync card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from master_driver.ui.cards._card_base import SimpleCardSpec, build_simple_card

_GENRE_SYNC_SPEC = SimpleCardSpec(
    toggle="module_toggles:genre_sync",
    title="Genre Sync",
    description=(
        "Sets Genre (TCON) from custom fields:\n"
        "  \u2022 TITLEGENRE (priority 1)\n"
        "  \u2022 ALBUMGENRE / ARTISTGENRE (Various Artists)\n"
        "  \u2022 ALBUMGENRE / ALBUMARTISTGENRE (single artist)"
    ),
    description_wraplength=480,
)


def build(parent: tk.Frame, state: "AppState") -> None:
    build_simple_card(parent, state, _GENRE_SYNC_SPEC)
