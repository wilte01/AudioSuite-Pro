"""Tests for audio_suite_shared.suite_app — the shell's worker hand-off.

Strategy
--------
A window's own rendering is covered by that window's suite; what belongs to the
shell is the hand-off around it: a fresh queue per run, a daemon thread, and the
``event_pump.pump_events`` poller that drains the queue while the thread lives,
plus the run report whose ``SUMMARY:`` footer every tool's View Log reads.
Each test drives the real methods on an ``object.__new__`` shell with a stub
root, so no Tk display is needed and nothing is mocked that the shell owns.

Changed in 2.9.0: new file.  ``_start_worker``, ``_poll_ui_updates`` and the
base ``_dispatch_ui_message`` moved here from four adopters that had written the
same wrapper byte for byte (D31).
Changed in 2.9.0: covers ``_write_run_report_standard``, the report three
adopters had written for themselves (D32).
Changed in 2.9.0: covers the writer creating its report's folder, and a write
failure the folder creation cannot repair (D33).
Changed in 2.9.0: covers the run controls a preset-carrying window shares -
the config key, the preset trio, the driver's argv mirror, the analysis start
- and the Auto End marker (D56).
Changed in 2.9.0: covers the two adopters the plain trio could not serve - a
window whose saved key differs from its variable's name, and one whose
presets still live under the older per-tool keys (D58).

Changed in 2.9.0: covers the shell's Auto End close - the marker it writes,
the status sentence it shows, and a checkbox-only launch (D60).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from queue import SimpleQueue
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared import suite_app, suite_config
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


class TestWriteRunReport:
    def test_it_writes_the_header_the_entries_and_the_summary(
        self, tmp_path: Path
    ) -> None:
        app = _window()
        app._log_path = str(tmp_path / "run_log.txt")
        app.TAGGED_LABEL = "Files read"

        app._write_run_report_standard(
            header=["REPORT\n"],
            log_entries=["[OK] a.mp3\n"],
            rows=(),
            total=2,
            tagged=1,
            skipped=1,
            errors=0,
            duration_secs=75.0,
        )

        lines = (tmp_path / "run_log.txt").read_text(encoding="utf-8").splitlines()
        assert lines[:2] == ["REPORT", "[OK] a.mp3"]
        for expected in (
            "SUMMARY:",
            "Total files: 2",
            "Files read: 1",
            "Skipped: 1",
            "Errors: 0",
            "Time: 01:15",
        ):
            assert expected in lines, lines
        assert lines[-1] == "Time: 01:15"
        assert lines.index("[OK] a.mp3") < lines.index("SUMMARY:")

    def test_the_tools_own_rows_follow_the_shared_counters(
        self, tmp_path: Path
    ) -> None:
        app = _window()
        app._log_path = str(tmp_path / "run_log.txt")
        app.TAGGED_LABEL = "Files scanned"

        app._write_run_report_standard(
            header=[],
            log_entries=[],
            rows=(("Duplicate groups", "2"), ("Files quarantined", "3")),
            total=4,
            tagged=4,
            skipped=0,
            errors=0,
            duration_secs=0.0,
        )

        lines = (tmp_path / "run_log.txt").read_text(encoding="utf-8").splitlines()
        assert lines.index("Errors: 0") < lines.index("Duplicate groups: 2")
        assert lines.index("Duplicate groups: 2") < lines.index("Files quarantined: 3")

    def test_a_failed_write_is_logged_not_raised(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        # The writer creates the folder, so the failure has to be one mkdir
        # cannot repair: the report path is itself a directory.  The run's audio
        # work is already done, so the completion must not raise off-thread.
        app = _window()
        app._log_path = str(tmp_path)
        app.TAGGED_LABEL = "Files read"

        with caplog.at_level(logging.ERROR):
            app._write_run_report_standard(
                header=[],
                log_entries=[],
                rows=(),
                total=1,
                tagged=1,
                skipped=0,
                errors=0,
                duration_secs=0.0,
            )

        assert "Could not write log" in caplog.text

    def test_it_creates_the_reports_folder(self, tmp_path: Path) -> None:
        # A run that writes into a fresh output directory must still leave a
        # report View Log can open, not a logged failure.
        app = _window()
        app._log_path = str(tmp_path / "run" / "nested" / "run_log.txt")
        app.TAGGED_LABEL = "Files read"

        app._write_run_report_standard(
            header=["REPORT\n"],
            log_entries=[],
            rows=(),
            total=1,
            tagged=1,
            skipped=0,
            errors=0,
            duration_secs=0.0,
        )

        assert Path(app._log_path).is_file()


class _ControlsWindow(_Window):
    """A shell with the run controls a preset-carrying analysis window has."""

    SETTINGS_PREFIX = "probe"
    TOOL_ID = "probe"
    STARTING_STATUS = "Probing..."

    started: bool = False

    def _start_run(self) -> None:
        self.started = True


class _AliasWindow(_ControlsWindow):
    """A window whose saved preset keys are not its variables' names."""

    PRESET_ALIASES = {"execution_mode": "run_mode"}


class _LegacyWindow(_ControlsWindow):
    """A window whose presets live under the older per-tool keys."""

    PRESET_KEY_PREFIX = "legacy"

    def _collect_settings(self) -> dict[str, Any]:
        """Collect the one setting this window's presets carry."""
        return {"threshold": 1.0}


def _controls_window(
    window_class: type[_ControlsWindow] = _ControlsWindow,
) -> _ControlsWindow:
    """Return a controls shell with stub Tk variables and a stub start button.

    Args:
        window_class: The adopter whose preset fields seed the stubs.

    Returns:
        The window, with one stub variable per preset field.
    """
    app = object.__new__(window_class)
    app.root = MagicMock()
    app.rendered = []
    for name in window_class.PRESET_FIELDS:
        setattr(app, name, MagicMock(**{"get.return_value": f"{name}-value"}))
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()
    app.auto_end = False
    app.start_btn = MagicMock()
    app.file_listbox = MagicMock()
    app.progress = {}
    app.notebook = MagicMock()
    app.processing_frame = MagicMock()
    app.overall_status = MagicMock()
    app._refresh_preset_list = MagicMock()
    app.slot_vars = [MagicMock() for _ in range(6)]
    return app


class TestRunControls:
    def test_a_preset_carries_every_declared_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _controls_window()
        saved: dict[str, Any] = {}

        def _save(_tool: str, _name: str, settings: dict[str, Any]) -> None:
            saved.update(settings)

        monkeypatch.setattr(suite_config, "save_preset", _save)
        monkeypatch.setattr(suite_config, "list_presets", lambda _tool: ["One"])

        app.store_preset("One")

        assert saved == {
            name: f"{name}-value" for name in _ControlsWindow.PRESET_FIELDS
        }
        app._refresh_preset_list.assert_called_once_with(["One"])

    def test_selecting_a_preset_restores_only_what_it_carries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _controls_window()

        def _load(_tool: str, _name: str) -> dict[str, Any]:
            return {"run_mode": "Live Update"}

        monkeypatch.setattr(suite_config, "load_preset", _load)

        app.use_preset("One")

        app.run_mode.set.assert_called_once_with("Live Update")
        app.max_workers.set.assert_not_called()

    def test_deleting_a_preset_refreshes_the_combo(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _controls_window()
        deleted: list[tuple[str, str]] = []
        monkeypatch.setattr(
            suite_config,
            "delete_preset",
            lambda tool, name: deleted.append((tool, name)),
        )
        monkeypatch.setattr(suite_config, "list_presets", lambda _tool: [])

        app.remove_preset("One")

        assert deleted == [("probe", "One")]
        app._refresh_preset_list.assert_called_once_with([])

    def test_a_window_can_store_a_setting_under_another_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _controls_window(_AliasWindow)
        saved: dict[str, Any] = {}
        monkeypatch.setattr(
            suite_config, "save_preset", lambda _tool, _name, s: saved.update(s)
        )
        monkeypatch.setattr(suite_config, "list_presets", lambda _tool: [])

        app.store_preset("One")

        assert saved["execution_mode"] == "run_mode-value"
        assert "run_mode" not in saved

        monkeypatch.setattr(
            suite_config,
            "load_preset",
            lambda _tool, _name: {"execution_mode": "Live"},
        )

        app.use_preset("One")

        app.run_mode.set.assert_called_once_with("Live")

    def test_a_window_can_keep_the_older_per_tool_preset_keys(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _controls_window(_LegacyWindow)
        written: list[tuple[str, str, dict[str, Any]]] = []
        dropped: list[tuple[str, str]] = []
        monkeypatch.setattr(
            suite_app,
            "save_tool_preset",
            lambda prefix, name, settings: written.append((prefix, name, settings)),
        )
        monkeypatch.setattr(
            suite_app,
            "delete_tool_preset",
            lambda prefix, name: dropped.append((prefix, name)),
        )
        monkeypatch.setattr(suite_app, "load_preset_names", lambda _key: ["Old"])

        app.store_preset("Old")
        app.remove_preset("Old")

        assert written == [("legacy", "Old", {"threshold": 1.0})]
        assert dropped == [("legacy", "Old")]
        assert app._refresh_preset_list.call_args_list == [
            ((["Old"],), {}),
            ((["Old"],), {}),
        ]

        monkeypatch.setattr(
            suite_app,
            "load_tool_preset",
            lambda _prefix, _name: {"threshold": 2.0},
        )
        app._apply_preset = MagicMock()

        app.use_preset("Old")

        app._apply_preset.assert_called_once_with({"threshold": 2.0})

    def test_a_missing_legacy_preset_applies_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _controls_window(_LegacyWindow)
        monkeypatch.setattr(suite_app, "load_tool_preset", lambda _prefix, _name: None)
        app._apply_preset = MagicMock()

        app.use_preset("Gone")

        app._apply_preset.assert_not_called()

    def test_a_driver_launch_mirrors_the_handshake_and_auto_starts(self) -> None:
        app = _controls_window()
        parsed = MagicMock(
            folder_path="C:/music",
            live_mode=True,
            auto_start=True,
            auto_end=True,
            clear_logs=True,
            parallel_run=True,
            analysis_duration=45,
            parallel_mode=False,
            max_workers=2,
        )

        app._mirror_cli_args(parsed)

        app.folder_path.set.assert_called_once_with("C:/music")
        app.run_mode.set.assert_called_once_with("Live Update")
        app.analysis_duration.set.assert_called_once_with(45)
        assert app.auto_end is True
        app.root.after.assert_called_once_with(1500, app.start_processing)

    def test_start_processing_snapshots_and_starts_the_run(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        app = _controls_window()
        folder = str(tmp_path)
        app.folder_path = MagicMock(**{"get.return_value": folder})
        app.run_mode = MagicMock(**{"get.return_value": "Live Update"})
        app.analysis_duration = MagicMock(**{"get.return_value": 45})
        app.parallel_mode = MagicMock(**{"get.return_value": True})
        app.max_workers = MagicMock(**{"get.return_value": 6})
        app.slot_vars = [MagicMock() for _ in range(4)]
        app._launched_from_driver = True
        saved: dict[str, object] = {}
        monkeypatch.setattr(
            suite_config,
            "save_value",
            lambda key, value: saved.update({key: value}),
        )

        app.start_processing()

        assert saved == {"probe_parallel_mode": True, "probe_max_workers": 4}
        assert app._dir_path == folder
        assert app._is_dry_run is False
        assert app._analysis_seconds == 45
        assert app._parallel is True
        assert app._workers == 4
        assert app.started is True
        app.overall_status.set.assert_called_once_with("Probing...")

    def test_auto_end_marks_the_report_and_schedules_the_close(
        self, tmp_path: Path
    ) -> None:
        app = _controls_window()
        app._log_path = str(tmp_path / "probe_log.txt")
        Path(app._log_path).write_text("PROBE REPORT\n", encoding="utf-8")

        app.close_for_auto_end()

        text = Path(app._log_path).read_text(encoding="utf-8")
        assert text.startswith("PROBE REPORT\n")
        assert text.endswith("\n[Auto End enabled - closing in 2 seconds...]\n")
        app.root.after.assert_called_once_with(2000, app.root.destroy)

    def test_auto_end_reads_the_flag_or_the_checkbox(self) -> None:
        app = _controls_window()
        app.auto_end_var = MagicMock(**{"get.return_value": False})
        app.auto_end = False
        assert app.auto_end_requested() is False

        app.auto_end_var.get.return_value = True
        assert app.auto_end_requested() is True

        app.auto_end_var.get.return_value = False
        app.auto_end = True
        assert app.auto_end_requested() is True

    def test_a_shell_without_its_checkbox_reads_the_flag(self) -> None:
        app = object.__new__(suite_app.SuiteApp)
        app.auto_end = False
        assert app.auto_end_requested() is False
        app.auto_end = True
        assert app.auto_end_requested() is True

    def test_close_for_auto_end_shows_the_sentence_in_a_status_line(
        self, tmp_path: Path
    ) -> None:
        app = _controls_window()
        app._log_path = str(tmp_path / "probe_log.txt")
        Path(app._log_path).write_text("PROBE REPORT\n", encoding="utf-8")
        status = MagicMock()

        app.close_for_auto_end(status=status)

        status.set.assert_called_once_with("Auto End enabled - closing in 2 seconds...")
        assert (
            Path(app._log_path)
            .read_text(encoding="utf-8")
            .endswith("\n[Auto End enabled - closing in 2 seconds...]\n")
        )
        app.root.after.assert_called_once_with(2000, app.root.destroy)
