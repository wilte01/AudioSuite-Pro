"""
group_caption.py — the full-width heading that introduces one group of cards.

Both driver tabs render their cards in captioned sections, so the heading is
one widget in one place: the Utilities tab's two-column grid and the Enrich
tab's single-column stack have to read the same, and a copy per tab is how the
two drift apart.

Changed in 2.6.0: extracted from ``utilities_window`` when the Enrich tab gained
the same grouping (PLAN_2026-11-08_enrich_card_grouping.md).
"""

from __future__ import annotations

import tkinter as tk

from audio_suite_shared import styles


class GroupCaption(tk.Label):
    """The full-width caption that introduces one group of cards.

    A ``Label`` rather than a ``Frame`` on purpose: the Utilities grid's card
    cells are its host's only ``Frame`` children, so a caption can never be
    mistaken for a card by the layout or by the tests that walk the grid.
    """

    def __init__(self, parent: tk.Misc, heading: str) -> None:
        """
        Args:
            parent: The container the caption is packed into.
            heading: The group's declared title, rendered uppercase.
        """
        super().__init__(
            parent,
            text=heading.upper(),
            font=styles.FONT_CAPTION_B,
            fg=styles.FG_SUB,
            bg=styles.BG_APP,
            anchor="w",
        )
