"""
mood_analysis_batch_card.py — Mood Analysis Batch Tagger module card.
Collapsible panel matching the UTILITY section style.
"""

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

_BATCH_MOOD_SPEC = SimpleCardSpec(
    toggle="module_toggles:mood_analysis_batch",
    title="Mood Analysis Batch Tagger",
    description=(
        "Recursively analyses the audio signal of every file under the "
        "selected root and writes mood + confidence tags."
    ),
    rows=(
        CardEntryRow(
            label="Analysis Duration (sec):",
            var_attr="mood_analysis_batch_duration",
            entry_width=6,
            entry_padx=(8, 0),
            row_pady=2,
        ),
        CardCheckEntryRow(
            check_attr="mood_analysis_batch_parallel",
            var_attr="mood_analysis_batch_workers",
            row_pady=4,
        ),
    ),
)


def build(parent: tk.Frame, state: "AppState") -> None:
    build_simple_card(parent, state, _BATCH_MOOD_SPEC)
