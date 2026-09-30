"""Tag Editor card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from master_driver.ui.cards._card_base import SimpleCardSpec, build_simple_card

_TAG_EDITOR_SPEC = SimpleCardSpec(
    toggle="module_toggles:tag_editor",
    title="Tag Editor",
    description=(
        "Opens an editable grid for title, artist, album, album artist,\n"
        "track, year, genre, and comment fields. Writes are undoable\n"
        "through Undo Tag Edits."
    ),
)


def build(parent: tk.Frame, state: "AppState") -> None:
    build_simple_card(parent, state, _TAG_EDITOR_SPEC)
