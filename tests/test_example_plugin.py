"""Tests for the bundled example plugin's window hand-off.

``plugins/example_plugin`` is both a working plugin and the template a
third-party developer copies, so its reader for the Master Driver's argument
grammar is worth locking.  The driver launches every plugin tool with
``[directory, --live|--dry, --start|--no-start, --end|--no-end]``
(``arg_builder._build_plugin_tool_args``); a window that ignores that argv opens
empty and in the wrong mode whatever the driver was set to, which is why the
folder and run mode are checked here through the same seam the driver uses.

The window is exercised without a display through ``object.__new__`` +
``MagicMock`` (AGENTS: *GUI (Tkinter) Testing*), which is why it lives in
``example_plugin.window`` rather than inside the ``.pyw`` launcher — a ``.pyw``
file is not importable as a module.

Changed in 2.1.0: new module — the example plugin's argv and pre-fill locks.
"""

from __future__ import annotations

import importlib
import queue
import sys
import threading
import time
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_ROOT = REPO_ROOT / "plugins"
LAUNCHER = PLUGINS_ROOT / "example_plugin" / "Example_Plugin.pyw"


@pytest.fixture(scope="module")
def plugin() -> Iterator[SimpleNamespace]:
    """Import the bundled plugin with ``plugins/`` on ``sys.path``, then restore.

    Yields:
        Namespace holding the plugin's ``tool`` and ``window`` modules.
    """
    added = str(PLUGINS_ROOT) not in sys.path
    if added:
        sys.path.insert(0, str(PLUGINS_ROOT))
    try:
        yield SimpleNamespace(
            tool=importlib.import_module("example_plugin.tool"),
            window=importlib.import_module("example_plugin.window"),
        )
    finally:
        if added:
            sys.path.remove(str(PLUGINS_ROOT))


def _options(plugin: SimpleNamespace, *argv: str) -> Any:
    """Parse *argv* with the plugin's own reader."""
    return plugin.tool.parse_launch_args(list(argv))


class TestParseLaunchArgs:
    """The driver's grammar, read by the plugin that has to live with it."""

    def test_dry_run_and_folder_are_read(self, plugin: SimpleNamespace) -> None:
        """The exact argv the driver builds for a Dry Run launch."""
        options = _options(plugin, "/music", "--dry", "--no-start", "--no-end")

        assert options.directory == "/music"
        assert options.dry_run is True
        assert options.start is False
        assert options.end is False

    def test_live_mode_is_read(self, plugin: SimpleNamespace) -> None:
        """``--live`` selects live mode, not the default dry run."""
        options = _options(plugin, "D:/Music", "--live", "--no-start", "--no-end")

        assert options.directory == "D:/Music"
        assert options.dry_run is False

    def test_last_mode_flag_wins(self, plugin: SimpleNamespace) -> None:
        """A repeated mode flag behaves like any command line: last one wins."""
        assert _options(plugin, "/a", "--dry", "--live").dry_run is False
        assert _options(plugin, "/a", "--live", "--dry").dry_run is True

    def test_start_and_end_are_read(self, plugin: SimpleNamespace) -> None:
        """The auto-start and close-when-done flags are parsed, not dropped."""
        options = _options(plugin, "/a", "--dry", "--start", "--end")

        assert options.start is True
        assert options.end is True

    def test_bare_launch_has_no_folder_and_is_live(
        self, plugin: SimpleNamespace
    ) -> None:
        """Double-clicking the launcher passes no argv; nothing is invented."""
        options = _options(plugin)

        assert options.directory == ""
        assert options.dry_run is False
        assert options.start is False
        assert options.end is False

    def test_unknown_flag_is_ignored(self, plugin: SimpleNamespace) -> None:
        """A newer driver's flag must not break an older plugin."""
        options = _options(plugin, "/music", "--future-flag", "--dry")

        assert options.directory == "/music"
        assert options.dry_run is True

    def test_folder_with_spaces_survives(self, plugin: SimpleNamespace) -> None:
        """A Windows path arrives as one argument and stays whole."""
        options = _options(plugin, "D:/My Music/10cc", "--dry")

        assert options.directory == "D:/My Music/10cc"


class TestDriverGrammarAgrees:
    """The argv producer and the plugin's reader must describe the same thing."""

    @pytest.mark.parametrize(
        ("mode_flag", "expected_dry_run"),
        [("--dry", True), ("--live", False)],
    )
    def test_parser_reads_what_the_argument_builder_emits(
        self,
        plugin: SimpleNamespace,
        mode_flag: str,
        expected_dry_run: bool,
    ) -> None:
        """The driver's own builder, piped straight into the plugin's reader.

        Args:
            plugin: The imported plugin modules.
            mode_flag: The mode flag the driver is set to.
            expected_dry_run: The mode the plugin must therefore report.
        """
        from master_driver.runner.arg_builder import _build_plugin_tool_args

        argv = _build_plugin_tool_args("D:/Music", mode_flag, "--no-start", "--no-end")
        options = plugin.tool.parse_launch_args(argv)

        assert options.directory == "D:/Music"
        assert options.dry_run is expected_dry_run


class TestWindowPreFill:
    """The pre-filled state a launched window shows, without a display."""

    @staticmethod
    def _window(plugin: SimpleNamespace, *argv: str) -> Any:
        """Build an app shell with mock variables and apply the argv.

        Args:
            plugin: The imported plugin modules.
            *argv: The driver's arguments.

        Returns:
            The app object, with ``folder``/``mode`` mocks recorded.
        """
        app = object.__new__(plugin.window.ExamplePluginApp)
        app.root = MagicMock()
        app.folder = MagicMock()
        app.mode = MagicMock()
        app.dry_run = False
        app.output = MagicMock()
        app.apply_options(_options(plugin, *argv))
        return app

    def test_folder_and_dry_run_are_prefilled(self, plugin: SimpleNamespace) -> None:
        """The driver's folder and mode reach the widgets it opened with."""
        app = self._window(plugin, "D:/Music", "--dry", "--no-start", "--no-end")

        app.folder.set.assert_called_once_with("D:/Music")
        app.mode.set.assert_called_once_with("Dry Run")
        assert app.dry_run is True

    def test_live_mode_is_prefilled(self, plugin: SimpleNamespace) -> None:
        """A Live Update launch says so rather than falling back to dry run."""
        app = self._window(plugin, "D:/Music", "--live")

        app.mode.set.assert_called_once_with("Live Update")
        assert app.dry_run is False

    def test_bare_launch_prefills_nothing(self, plugin: SimpleNamespace) -> None:
        """No argv leaves the entry empty and the mode live."""
        app = self._window(plugin)

        app.folder.set.assert_called_once_with("")
        app.mode.set.assert_called_once_with("Live Update")

    def test_browse_writes_the_folder_through_the_same_path(
        self, plugin: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Browse and the argv pre-fill share one write path (AGENTS).

        A second, independent write to the entry is how a programmatic pre-fill
        and a widget edit drift apart.
        """
        monkeypatch.setattr(
            plugin.window.filedialog, "askdirectory", lambda **_kwargs: "/chosen"
        )
        app = object.__new__(plugin.window.ExamplePluginApp)
        app.root = MagicMock()
        app.folder = MagicMock()

        app._browse()

        app.folder.set.assert_called_once_with("/chosen")


class TestWindowOnARealRoot:
    """The pre-fill as the user actually sees it, on the shared hidden root."""

    def test_launched_window_shows_the_drivers_folder_and_mode(
        self, plugin: SimpleNamespace, tk_root: Any
    ) -> None:
        """Building the window with argv fills both widgets for real.

        The mock-based tests above prove the variables are written; this one
        proves the widgets a user looks at carry the value — a read-only
        default that the pre-fill route never reaches is the defect AGENTS'
        pre-fill rule exists for.
        """
        options = _options(plugin, "D:/Music", "--dry", "--no-start", "--no-end")
        host = tk.Toplevel(tk_root)
        try:
            app = plugin.window.ExamplePluginApp(host, options)
            assert app.folder.get() == "D:/Music"
            assert app.mode.get() == "Dry Run"
            assert app.dry_run is True
        finally:
            host.destroy()


class TestLauncherForwardsArguments:
    """The ``.pyw`` hands its argv to the window it opens."""

    def test_launcher_passes_its_arguments(self) -> None:
        """A launcher that calls ``main()`` bare ignores the driver again."""
        source = LAUNCHER.read_text(encoding="utf-8")

        assert "from example_plugin.window import main" in source
        assert "main(sys.argv[1:])" in source, (
            "the launcher must forward the driver's arguments to the window"
        )


class _FakeRoot:
    """A Tk root stand-in that records the callbacks scheduled on it.

    On a real root Tk would run them, so the fake keeps them until
    :meth:`pump`.  It also records every call made from a thread other than the
    one that built it: a worker that touches Tk — including ``root.after`` — is
    the defect this lock exists for, and on a real root it raises
    ``RuntimeError: main thread is not in main loop``.
    """

    def __init__(self) -> None:
        self.thread = threading.current_thread()
        self.callbacks: list[tuple[Any, tuple[Any, ...]]] = []
        self.cross_thread_calls: list[str] = []
        self.destroyed = False

    def after(self, _delay: int, callback: Any, *args: Any) -> None:
        """Queue a callback, noting any call that did not come from Tk's thread."""
        current = threading.current_thread()
        if current is not self.thread:
            self.cross_thread_calls.append(current.name)
        self.callbacks.append((callback, args))

    def destroy(self) -> None:
        """Record that the window asked to close."""
        self.destroyed = True

    def pump(self) -> None:
        """Run the callbacks queued so far, in order, and only those.

        A poll that finds no result schedules the next poll, so draining until
        the queue is empty would spin forever: one pump is one turn of the
        event loop.
        """
        batch, self.callbacks = self.callbacks, []
        for callback, args in batch:
            callback(*args)


def _shell(
    plugin: SimpleNamespace,
    root: _FakeRoot,
    *,
    folder: str = "D:/Music",
    close_when_done: bool = False,
) -> Any:
    """Build the app shell around *root* without constructing widgets.

    Args:
        plugin: The imported plugin modules.
        root: The root stand-in the app must marshal through.
        folder: What the folder entry holds.
        close_when_done: The value ``--end`` sets.

    Returns:
        The app object, with mock widgets.
    """
    app = object.__new__(plugin.window.ExamplePluginApp)
    app.root = root
    app.folder = MagicMock()
    app.folder.get.return_value = folder
    app.mode = MagicMock()
    app.output = MagicMock()
    app.run_button = MagicMock()
    app.dry_run = True
    app.close_when_done = close_when_done
    app._running = False
    app._results = queue.SimpleQueue()
    return app


def _pump_until(
    root: _FakeRoot, predicate: Any, description: str, timeout: float = 5.0
) -> None:
    """Pump the fake root's callbacks until *predicate* holds, or fail.

    This is the Tk event loop for the tests: the window polls its queue with
    ``root.after``, so a result is delivered only once the scheduled poll runs.

    Args:
        root: The root stand-in to pump.
        predicate: Callable returning True once the expected state is reached.
        description: What was expected, used as the failure message.
        timeout: How long to wait, in seconds.
    """
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        if root.callbacks:
            root.pump()
        else:
            time.sleep(0.01)
    assert predicate(), description


def _written(app: Any) -> str:
    """Return everything the app appended to its output pane."""
    return "".join(call.args[1] for call in app.output.insert.call_args_list)


class TestStartAndEndFlags:
    """``--start`` runs on open; ``--end`` closes when the run finishes."""

    @staticmethod
    def _window(plugin: SimpleNamespace, *argv: str) -> Any:
        """Apply *argv* to a shell whose root records scheduled calls.

        Args:
            plugin: The imported plugin modules.
            *argv: The driver's arguments.

        Returns:
            The app object after the pre-fill.
        """
        app = object.__new__(plugin.window.ExamplePluginApp)
        app.root = MagicMock()
        app.folder = MagicMock()
        app.mode = MagicMock()
        app.output = MagicMock()
        app.run_button = MagicMock()
        app._running = False
        app.dry_run = False
        app.close_when_done = False
        app.apply_options(_options(plugin, *argv))
        return app

    def test_start_schedules_the_run_instead_of_blocking(self, plugin) -> None:
        """The run is scheduled, so the window is drawn before the worker runs."""
        app = self._window(plugin, "D:/Music", "--dry", "--start", "--no-end")

        app.root.after.assert_called_once_with(0, app.start_run)

    def test_no_start_schedules_nothing(self, plugin) -> None:
        """Without --start the Run button stays the user's to press."""
        app = self._window(plugin, "D:/Music", "--dry", "--no-start", "--no-end")

        app.root.after.assert_not_called()

    def test_end_is_remembered(self, plugin) -> None:
        """--end reaches the window rather than being parsed and dropped."""
        app = self._window(plugin, "D:/Music", "--dry", "--start", "--end")

        assert app.close_when_done is True

    def test_end_without_start_waits_for_the_user(self, plugin) -> None:
        """--end closes a manual run; it does not open the tool unattended."""
        app = self._window(plugin, "D:/Music", "--dry", "--no-start", "--end")

        app.root.after.assert_not_called()
        assert app.close_when_done is True


class TestRunOnAWorkerThread:
    """The report runs off the Tk thread and returns through ``after``."""

    def test_the_walk_runs_off_the_tk_thread(
        self, plugin: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A slow drive must not freeze the window, and Tk stays on its thread."""
        seen: dict[str, Any] = {}
        widget_threads: list[threading.Thread] = []

        def fake_summarise(folder: str) -> list[str]:
            seen["thread"] = threading.current_thread()
            seen["folder"] = folder
            return ["Files:      2", "With genre: 1", "Formats:    mp3 (2)"]

        monkeypatch.setattr(plugin.window, "summarise", fake_summarise)
        root = _FakeRoot()
        app = _shell(plugin, root)
        app.output.insert.side_effect = lambda *_args: widget_threads.append(
            threading.current_thread()
        )

        app.start_run()
        _pump_until(
            root,
            lambda: not app._running,
            "the worker's report never reached the window",
        )

        assert seen["folder"] == "D:/Music"
        assert seen["thread"] is not threading.current_thread(), (
            "the folder walk ran on the Tk thread"
        )
        assert seen["thread"] is not root.thread
        assert root.cross_thread_calls == [], (
            "a worker touched Tk; on a real root that raises "
            "'main thread is not in main loop'"
        )
        assert widget_threads and all(t is root.thread for t in widget_threads), (
            "the report was written to the widget from a worker thread"
        )
        assert app.run_button.config.call_args_list[-1].kwargs == {"state": "normal"}
        written = _written(app)
        assert "Example Tool (dry run) — D:/Music" in written
        assert "Files:      2" in written
        assert "Error" not in written

    def test_a_run_in_flight_refuses_a_second_start(
        self, plugin: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The Run button is disabled while the walk is out on the worker."""
        gate = threading.Event()
        started = threading.Event()

        def fake_summarise(_folder: str) -> list[str]:
            started.set()
            gate.wait(5)
            return ["Files:      1"]

        monkeypatch.setattr(plugin.window, "summarise", fake_summarise)
        root = _FakeRoot()
        app = _shell(plugin, root)

        app.start_run()
        assert started.wait(5), "the worker never started"
        assert app._running is True
        app.run_button.config.assert_called_once_with(state="disabled")

        gate.set()
        _pump_until(root, lambda: not app._running, "the report never landed")

    def test_a_second_start_is_ignored_while_running(
        self, plugin: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Double-clicking Run must not start two walks of the same folder."""
        gate = threading.Event()
        started = threading.Event()
        calls: list[str] = []

        def fake_summarise(folder: str) -> list[str]:
            calls.append(folder)
            started.set()
            gate.wait(5)
            return ["Files:      1"]

        monkeypatch.setattr(plugin.window, "summarise", fake_summarise)
        root = _FakeRoot()
        app = _shell(plugin, root)

        app.start_run()
        assert started.wait(5), "the worker never started"
        app.start_run()
        gate.set()
        _pump_until(root, lambda: not app._running, "the report never landed")

        assert calls == ["D:/Music"]

    def test_end_closes_the_window_after_the_report(
        self, plugin: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--end closes, but only once the result has landed."""
        monkeypatch.setattr(
            plugin.window, "summarise", lambda _folder: ["Files:      0"]
        )
        root = _FakeRoot()
        app = _shell(plugin, root, close_when_done=True)

        app.start_run()
        _pump_until(root, lambda: root.destroyed, "an --end run never closed")

        assert "Files:      0" in _written(app)
        assert root.cross_thread_calls == []

    def test_a_run_without_end_keeps_the_window_open(
        self, plugin: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--no-end leaves the report on screen for the user to read."""
        monkeypatch.setattr(
            plugin.window, "summarise", lambda _folder: ["Files:      0"]
        )
        root = _FakeRoot()
        app = _shell(plugin, root)

        app.start_run()
        _pump_until(root, lambda: not app._running, "the report never landed")

        assert root.destroyed is False
        assert "Files:      0" in _written(app)

    def test_a_failed_run_stays_open_with_its_message(
        self, plugin: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Closing on failure would hide the only line saying what went wrong."""

        def failing(_folder: str) -> list[str]:
            raise OSError("disk gone")

        monkeypatch.setattr(plugin.window, "summarise", failing)
        root = _FakeRoot()
        app = _shell(plugin, root, close_when_done=True)

        app.start_run()
        _pump_until(root, lambda: not app._running, "the failure never landed")

        assert root.destroyed is False
        assert "Error: OSError: disk gone" in _written(app)
        assert app.run_button.config.call_args_list[-1].kwargs == {"state": "normal"}

    def test_an_empty_folder_runs_nothing(
        self, plugin: SimpleNamespace, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """--start with no folder reports it; it does not walk the cwd or exit."""
        calls: list[str] = []
        monkeypatch.setattr(
            plugin.window, "summarise", lambda folder: calls.append(folder) or []
        )
        root = _FakeRoot()
        app = _shell(plugin, root, folder="", close_when_done=True)

        app.start_run()

        assert calls == []
        assert root.callbacks == []
        assert root.destroyed is False
        assert "Choose a folder first." in _written(app)


class TestStartAndEndOnARealRoot:
    """The batch launch as the driver performs it, on the shared hidden root."""

    def test_start_runs_the_report_on_open(
        self, plugin: SimpleNamespace, tk_root: Any, tmp_path: Path
    ) -> None:
        """--start fills the pane without the user pressing Run."""
        options = _options(plugin, str(tmp_path), "--dry", "--start", "--no-end")
        host = tk.Toplevel(tk_root)
        text = ""
        try:
            app = plugin.window.ExamplePluginApp(host, options)
            deadline = time.monotonic() + 10
            while "Files:" not in text and time.monotonic() < deadline:
                host.update()
                text = app.output.get("1.0", tk.END)
                time.sleep(0.01)
        finally:
            host.destroy()

        assert "Example Tool (dry run)" in text, "--start did not run on open"
        assert "Files:      0" in text

    def test_end_closes_the_window_when_the_run_finishes(
        self, plugin: SimpleNamespace, tk_root: Any, tmp_path: Path
    ) -> None:
        """The driver's batch step must return by itself, not wait for a click."""
        options = _options(plugin, str(tmp_path), "--dry", "--start", "--end")
        host = tk.Toplevel(tk_root)
        plugin.window.ExamplePluginApp(host, options)

        closed = False
        deadline = time.monotonic() + 10
        while not closed and time.monotonic() < deadline:
            try:
                host.update()
                closed = not host.winfo_exists()
            except tk.TclError:
                closed = True
            time.sleep(0.01)

        assert closed, "an --start --end launch must close when its run finishes"
