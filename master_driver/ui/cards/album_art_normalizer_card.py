"""
master_driver/ui/cards/album_art_normalizer_card.py
"""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from master_driver.ui.cards._card_base import (
    CardCaption,
    CardComboRow,
    SimpleCardSpec,
    build_simple_card,
)

_ALBUM_ART_NORM_SPEC = SimpleCardSpec(
    toggle="module_toggles:album_art_normalizer",
    title="Album Art Normalizer",
    description=("Centre-crops and resizes embedded artwork to a standard resolution."),
    rows=(
        CardComboRow(
            label="Target Size:",
            var_attr="art_normalizer_size",
            values=("600", "800", "1000", "1200"),
            combo_width=12,
            label_width=26,
            combo_padx=6,
        ),
        CardCaption(
            text="Normalises folder.jpg to 1000\u00d71000. Supports MP3 and FLAC.",
            pady=(4, 0),
        ),
        CardCaption(
            text="Note: Uses its own mode setting, not the Master Driver Mode option",
            amber=True,
            pady=(8, 0),
        ),
    ),
)


def build(parent: tk.Frame, state: "AppState") -> None:
    build_simple_card(parent, state, _ALBUM_ART_NORM_SPEC)
