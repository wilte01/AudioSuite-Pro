"""event_pump.py — the Tk-thread half of a GUI tool's worker protocol.

Every tool that runs a batch off the Tk thread follows the same contract: the
worker puts ``(kind, payload)`` on a ``queue.SimpleQueue`` and **never** touches
a widget, and a poller the Tk thread started drains that queue, renders each
item, and re-arms itself while the worker still runs (AGENTS.md, *GUI Callback
Contract* — D136, where the first version of the example plugin marshalled from
the worker and hung on a real launch).

Eight windows wrote that drain loop by hand, and the loop is the part with no
tool-specific content in it: what to do with an item differs per tool, when to
stop polling is the window's business.  So this module owns only the loop —
take everything queued, in order, then schedule the next tick — and each tool
keeps a ``_dispatch`` method holding its own rendering.

``is_active`` and ``is_running`` are separate questions on purpose.  A window
that is closing must not drain anything at all, while a window whose worker has
finished drains what is left and then stops re-arming; collapsing the two would
either lose the last events or spin forever.

Changed in 2.9.0: new module - the Tk poller eight windows wrote by hand (B1).
"""

from __future__ import annotations

import queue
import tkinter as tk
from collections.abc import Callable
from typing import Any

__all__ = ["pump_events"]


def pump_events(
    root: tk.Misc,
    events: queue.SimpleQueue[Any],
    dispatch: Callable[[Any], None],
    *,
    is_running: Callable[[], bool],
    next_tick: Callable[[], None],
    is_active: Callable[[], bool] | None = None,
    poll_ms: int = 100,
) -> str:
    """Apply every queued worker result, then re-arm while the run is live.

    Args:
        root: The window that owns the timer.
        events: The worker's queue.  Nothing else may consume it.
        dispatch: Renders one item on the Tk thread, in queue order.
        is_running: Whether the worker still needs polling — normally the
            window's ``_thread is not None and _thread.is_alive()``.
        next_tick: The poller to schedule, normally the caller itself.
        is_active: Whether the window is still open.  ``None`` means "always",
            for a window that has no closing flag to consult.
        poll_ms: Delay before the next tick.

    Returns:
        The id of the scheduled tick, or ``""`` when nothing was scheduled.
        The caller stores it so ``_on_close`` can cancel a pending tick.
    """
    if is_active is not None and not is_active():
        return ""

    while True:
        try:
            item = events.get_nowait()
        except queue.Empty:
            break
        dispatch(item)

    if is_running():
        return root.after(poll_ms, next_tick)
    return ""
