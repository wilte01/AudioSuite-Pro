"""text_utils.py — small text shaping the suite's user-facing records share.

A launcher failure record and a tool's run outcome both carry free text the
tool composed, and both write it to a JSON file another program reads: a
multi-line note in a one-line field breaks the reader's layout, and an
unbounded one can carry a whole traceback.  Both therefore collapsed their text
the same way — whitespace to single spaces, cut to a limit, ASCII ellipsis —
with their own copy of the four lines.

Changed in 2.9.0: new module - the truncation two record writers shared (C3).
"""

from __future__ import annotations

__all__ = ["one_line"]

#: The suffix a cut line ends with.  ASCII: a record is read on a console.
ELLIPSIS = "..."


def one_line(text: str, limit: int) -> str:
    """Collapse *text* to one bounded line.

    Args:
        text: The text to collapse; it may span lines.
        limit: The longest result, in characters, including the ellipsis.

    Returns:
        Whitespace-collapsed text of at most *limit* characters, with an ASCII
        ellipsis when it had to be cut.
    """
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - len(ELLIPSIS)].rstrip() + ELLIPSIS
