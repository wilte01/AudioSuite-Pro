"""Mood Analyzer card for Master Driver UI."""

import tkinter as tk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...state.app_state import AppState

from master_driver.ui.cards._card_base import (
    CardCheckEntryRow,
    CardEntryRow,
    SimpleCardSpec,
    build_simple_card,
)

_MOOD_SPEC = SimpleCardSpec(
    toggle="module_toggles:mood_analyzer",
    title="Mood Analyzer",
    rows=(
        CardEntryRow(
            label="Analysis Duration (s):", var_attr="mood_duration", label_width=26
        ),
        CardCheckEntryRow(check_attr="mood_parallel", var_attr="mood_workers"),
    ),
)


def build(parent: tk.Frame, state: "AppState") -> None:
    build_simple_card(parent, state, _MOOD_SPEC)
