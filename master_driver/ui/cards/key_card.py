"""Key Detector card for Master Driver UI."""

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

_KEY_SPEC = SimpleCardSpec(
    toggle="module_toggles:key",
    title="Key Detector",
    rows=(
        CardEntryRow(
            label="Analysis Duration (s):", var_attr="key_duration", label_width=26
        ),
        CardCheckEntryRow(check_attr="key_parallel", var_attr="key_workers"),
    ),
)


def build(parent: tk.Frame, state: "AppState") -> None:
    build_simple_card(parent, state, _KEY_SPEC)
