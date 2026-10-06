"""Tempo Analyzer card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from master_driver.ui.cards._card_base import (
    CardComboRow,
    SimpleCardSpec,
    build_simple_card,
)

_TEMPO_SPEC = SimpleCardSpec(
    toggle="module_toggles:tempo",
    title="Tempo Analyzer",
    rows=(
        CardComboRow(
            label="Tempo Naming Scheme:",
            var_attr="tempo_scheme",
            values=(
                "Italian",
                "English",
                "Descriptive",
                "Numeric",
                "Simplified",
                "Dance",
                "Running",
            ),
            combo_width=15,
            label_width=26,
        ),
    ),
)


def build(parent: tk.Frame, state: "AppState") -> None:
    build_simple_card(parent, state, _TEMPO_SPEC)
