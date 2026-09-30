"""ASX Playlist Extractor card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from master_driver.ui.cards._card_base import SimpleCardSpec, build_simple_card

_ASX_SPEC = SimpleCardSpec(
    toggle="asx_extractor_toggle",
    title="ASX Playlist Extractor",
)


def build(parent: tk.Frame, state: "AppState") -> None:
    build_simple_card(parent, state, _ASX_SPEC)
