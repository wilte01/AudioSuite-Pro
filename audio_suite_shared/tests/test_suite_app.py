"""Tests for audio_suite_shared.suite_app — the shell's worker hand-off.

Strategy
--------
A window's own rendering is covered by that window's suite; what belongs to the
shell is the hand-off around it: a fresh queue per run, a daemon thread, and the
``event_pump.pump_events`` poller that drains the queue while the thread lives.
Each test drives the real methods on an ``object.__new__`` shell with a stub
root, so no Tk display is needed and nothing is mocked that the shell owns.

Changed in 2.9.0: new file.  ``_start_worker``, ``_poll_ui_updates`` and the
base ``_dispatch_ui_message`` moved here from four adopters that had written the
same wrapper byte for byte (D31).
"""

from __future__ import annotations

import threading
from queue import SimpleQueue
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.event_pump import DEFAULT_POLL_MS
from audio_suite_shared.suite_app import SuiteApp


class _Window(SuiteApp):
    """A shell whose dispatch only records, so no Tk root is built."""

    def _dispatch_ui_message(self, message: tuple[Any, ...]) -> None:
        self.rendered.append(message)


def _window() -> _Window:
    """Return a shell with a stub root and nothing running.

    Returns:
        The window, with an empty render log and no run thread.
    """
    app = object.__new__(_Window)
    app.root = MagicMock()
    app._run_thread = None
    app.rendered = []
    return app


class TestStartWorker:
    def test_it_builds_the_runs_queue_and_starts_a_daemon_thread(self) -> None:
        app = _window()
        started = threading.Event()
        release = threading.Event()

        def _target(token: str) -> None:
            """Stand in for a run: announce itself and wait to be released."""
            started.set()
            release.wait(5)

        app._start_worker(_target, ("first",))

        assert started.wait(5), "the target never ran"
        try:
            assert isinstance(app._ui_updates, SimpleQueue)
            thread = app._run_thread
            assert thread is not None and thread.daemon and thread.is_alive()
        finally:
            release.set()
            assert app._run_thread is not None
            app._run_thread.join(5)

    def test_it_starts_the_poller_while_the_run_is_live(self) -> None:
        app = _window()
        started = threading.Event()
        release = threading.Event()

        def _target() -> None:
            """Stand in for a run that stays alive until released."""
            started.set()
            release.wait(5)

        app._start_worker(_target, ())

        assert started.wait(5), "the target never ran"
        try:
            app.root.after.assert_called_once()
            delay, callback = app.root.after.call_args.args
            assert delay == DEFAULT_POLL_MS
            assert callback == app._poll_ui_updates
        finally:
            release.set()
            assert app._run_thread is not None
            app._run_thread.join(5)

    def test_every_run_gets_its_own_queue(self) -> None:
        # A message left in a finished run's queue must not reach the next one.
        app = _window()

        app._start_worker(lambda: None, ())
        assert app._run_thread is not None
        app._run_thread.join(5)
        first = app._ui_updates
        first.put(("stale",))

        app._start_worker(lambda: None, ())
        assert app._run_thread is not None
        app._run_thread.join(5)

        assert app._ui_updates is not first
        assert app.rendered == []


class TestPollUiUpdates:
    def test_it_renders_every_queued_message_in_order(self) -> None:
        app = _window()
        app._ui_updates = SimpleQueue()
        for item in (("progress", 1), ("progress", 2), ("complete",)):
            app._ui_updates.put(item)

        app._poll_ui_updates()

        assert app.rendered == [("progress", 1), ("progress", 2), ("complete",)]
        app.root.after.assert_not_called()

    def test_it_re_arms_while_the_run_is_live(self) -> None:
        app = _window()
        app._ui_updates = SimpleQueue()
        app._run_thread = MagicMock()
        app._run_thread.is_alive.return_value = True

        app._poll_ui_updates()

        app.root.after.assert_called_once()
        assert app.root.after.call_args.args[1] == app._poll_ui_updates

    def test_it_stops_once_the_run_has_ended(self) -> None:
        app = _window()
        app._ui_updates = SimpleQueue()
        app._ui_updates.put(("complete",))
        app._run_thread = MagicMock()
        app._run_thread.is_alive.return_value = False

        app._poll_ui_updates()

        assert app.rendered == [("complete",)]
        app.root.after.assert_not_called()


class TestDispatchIsTheToolsOwn:
    def test_the_base_shell_has_no_rendering_of_its_own(self) -> None:
        app = object.__new__(SuiteApp)

        with pytest.raises(NotImplementedError, match="_dispatch_ui_message"):
            app._dispatch_ui_message(("progress", 1))
