"""
test_event_pump.py — Unit tests for audio_suite_shared.event_pump

Strategy
--------
The pump is pure scheduling over a queue and a fake root: every test drives
``pump_events`` directly with a stub root that records the tick it is asked to
schedule, so no Tk display is needed.  The window-side rendering is each
window's own ``_dispatch`` and is covered by that window's suite.

Covers:
    • pump_events: drains every queued item, in order
    • pump_events: re-arms while the worker runs, and returns the tick id
    • pump_events: a message queued as the worker ends is still rendered
    • pump_events: an inactive window drains nothing and schedules nothing
    • pump_events: nothing is scheduled once the run has finished
    • pump_events: poll_ms overrides the shared default

Changed in 2.9.0: new file - the shared poller's first tests, including the
finished-run drain that keeps a late completion (B2).
"""

from __future__ import annotations

import queue
from collections.abc import Callable
from typing import Any

from audio_suite_shared.event_pump import DEFAULT_POLL_MS, pump_events


class _Root:
    """A root that records the tick it is asked to schedule."""

    def __init__(self) -> None:
        self.scheduled: list[tuple[int, Callable[[], None]]] = []

    def after(self, delay: int, callback: Callable[[], None]) -> str:
        """Record one scheduled tick and return its id."""
        self.scheduled.append((delay, callback))
        return f"tick-{len(self.scheduled)}"


def _queue(*items: Any) -> queue.SimpleQueue[Any]:
    """A queue holding *items*, in order."""
    events: queue.SimpleQueue[Any] = queue.SimpleQueue()
    for item in items:
        events.put(item)
    return events


def test_drains_every_item_in_order() -> None:
    """One tick delivers the whole queue, in the order the worker wrote it."""
    root = _Root()
    seen: list[Any] = []

    tick = pump_events(
        root,
        _queue("a", "b", "c"),
        seen.append,
        is_running=lambda: False,
        next_tick=lambda: None,
    )

    assert seen == ["a", "b", "c"]
    assert tick == ""


def test_rearms_while_the_worker_runs() -> None:
    """A live worker keeps the pump scheduled, and the tick id is returned."""
    root = _Root()
    seen: list[Any] = []

    def next_tick() -> None:
        """Stand in for the window's poller."""

    tick = pump_events(
        root,
        _queue("a"),
        seen.append,
        is_running=lambda: True,
        next_tick=next_tick,
    )

    assert seen == ["a"]
    assert tick == "tick-1"
    assert root.scheduled == [(DEFAULT_POLL_MS, next_tick)]


def test_a_message_queued_as_the_worker_ends_still_lands() -> None:
    """A completion written while the tick drains is not stranded.

    This is the race the hand-written loops closed and the first version of the
    pump did not: the worker queues its last message after the drain read the
    queue empty but before the liveness check, then exits.  The pump must drain
    again rather than stop with that message still queued.
    """
    root = _Root()
    events: queue.SimpleQueue[Any] = _queue("progress")
    seen: list[Any] = []
    running = True

    def dispatch(item: Any) -> None:
        """Render one item, and finish the run from inside the drain."""
        nonlocal running
        seen.append(item)
        if item == "progress":
            events.put("complete")
            running = False

    tick = pump_events(
        root,
        events,
        dispatch,
        is_running=lambda: running,
        next_tick=lambda: None,
    )

    assert seen == ["progress", "complete"]
    assert tick == ""
    assert root.scheduled == []


def test_an_inactive_window_drains_nothing() -> None:
    """A closing window neither renders nor schedules, and leaves the queue."""
    root = _Root()
    events = _queue("progress", "complete")
    seen: list[Any] = []

    tick = pump_events(
        root,
        events,
        seen.append,
        is_running=lambda: True,
        next_tick=lambda: None,
        is_active=lambda: False,
    )

    assert seen == []
    assert tick == ""
    assert root.scheduled == []
    assert events.get_nowait() == "progress"


def test_nothing_is_scheduled_once_the_run_has_finished() -> None:
    """An empty queue and a dead worker end the pump with no pending tick."""
    root = _Root()

    tick = pump_events(
        root,
        _queue(),
        lambda _item: None,
        is_running=lambda: False,
        next_tick=lambda: None,
    )

    assert tick == ""
    assert root.scheduled == []


def test_poll_ms_overrides_the_shared_default() -> None:
    """A window with its own cadence still gets the shared loop."""
    root = _Root()

    pump_events(
        root,
        _queue(),
        lambda _item: None,
        is_running=lambda: True,
        next_tick=lambda: None,
        poll_ms=250,
    )

    assert [delay for delay, _callback in root.scheduled] == [250]
