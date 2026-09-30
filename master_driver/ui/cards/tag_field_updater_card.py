"""Tag Field Updater card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from master_driver.ui.cards._card_base import SimpleCardSpec, build_simple_card

_TAG_FIELD_UPDATER_SPEC = SimpleCardSpec(
    toggle="module_toggles:tag_field_updater",
    title="Tag Field Updater",
    description=(
        "Recursively scans your music library and normalises custom\n"
        "TXXX genre fields (ALBUMARTISTGENRE, ALBUMGENRE, ARTISTGENRE)\n"
        "by replacing '/' separators with '; '."
    ),
    description_wraplength=480,
)


def build(parent: tk.Frame, state: "AppState") -> None:
    build_simple_card(parent, state, _TAG_FIELD_UPDATER_SPEC)
