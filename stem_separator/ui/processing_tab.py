"""Processing tab UI for the Stem Separator."""

from __future__ import annotations

import tkinter as tk

from audio_suite_shared import ui_common


def build(
    parent: tk.Frame, slot_vars: list[tk.StringVar] | None = None
) -> dict[str, object]:
    """Populate the Processing tab and return widget references."""
    return ui_common.build_processing_tab(parent, slot_vars)
