"""
tests/test_app.py
Tests for app.py — FileReorganizerApp orchestration logic.

Run with:
    pytest file_reorganizer/tests/test_app.py -v

Coverage
--------
_seed_source_from_last_directory
  * Source always follows the suite-wide last-used directory at launch,
    overriding any locally restored value (Master Driver hand-off wins)
  * Leaves the current value in place when last_directory is unset/empty
  * Never seeds the destination directory

_browse_source / _browse_dest
  * Browsing the source saves it as suite-wide last-used directory
  * A cancelled browse neither sets nor saves anything
  * Browsing the destination never updates the last-used directory

_save_settings / _load_settings
  * Persist dest/action/patterns only — never source_dir, whose single
    source of truth is the suite-wide last-used directory

Mode / dry_run
  * The run-controls strip's Mode is the control; dry_run is derived from it
  * A preset that stored only the legacy ``dry_run`` boolean still restores
    the mode, so old presets keep working

Worker threading
  * A scan thread never touches a widget or ``root.after``; it posts
    ``_RunEvent`` objects that the Tk-thread poller drains

Changed in 1.0.1: TestExecuteFlow::test_execute_thread_runs_in_undo_batch_and_finishes
stubs ui_common.show_message — _finish() opened the completion modal, and with a
MagicMock root the real modal builds tk.Toplevel(MagicMock) and loops forever.

Changed in 2.4.3: the app runs on the shared shell (WP-8, WP-8 order #2).  The
completion modal is gone (the Results tab shows the summary), the preview list
is the shared Processing listbox, the four counters are rendered as the shared
stats line, and the scan thread's widget writes became queued events.  The
tests assert those seams rather than the deleted widgets.
"""

from __future__ import annotations

import queue
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from file_reorganizer.app import FileReorganizerApp
from file_reorganizer.core.engine import ReorganizerStats


class TestSeedSourceFromLastDirectory:
    """_seed_source_from_last_directory() restores the Master Driver hand-off."""

    @staticmethod
    @pytest.fixture
    def app() -> FileReorganizerApp:
        app = object.__new__(FileReorganizerApp)
        app.source_dir = MagicMock()
        app.dest_dir = MagicMock()
        return app

    def test_seeds_empty_source_from_last_directory(
        self, app: FileReorganizerApp
    ) -> None:
        app.source_dir.get.return_value = ""
        with patch("file_reorganizer.app.suite_config") as mock_config:
            mock_config.load_last_directory.return_value = "/music/from/driver"
            app._seed_source_from_last_directory()
        app.source_dir.set.assert_called_once_with("/music/from/driver")
        mock_config.load_last_directory.assert_called_once()

    def test_last_directory_overrides_restored_settings(
        self, app: FileReorganizerApp
    ) -> None:
        app.source_dir.get.return_value = (
            "D:/Users/Public/Music/Monitored/Various Artists/stale"
        )
        with patch("file_reorganizer.app.suite_config") as mock_config:
            mock_config.load_last_directory.return_value = "/music/from/driver"
            app._seed_source_from_last_directory()
        app.source_dir.set.assert_called_once_with("/music/from/driver")
        mock_config.load_last_directory.assert_called_once()

    def test_empty_last_directory_leaves_value_untouched(
        self, app: FileReorganizerApp
    ) -> None:
        app.source_dir.get.return_value = ""
        with patch("file_reorganizer.app.suite_config") as mock_config:
            mock_config.load_last_directory.return_value = ""
            app._seed_source_from_last_directory()
        mock_config.load_last_directory.assert_called_once()
        app.source_dir.set.assert_not_called()

    def test_destination_is_never_seeded(self, app: FileReorganizerApp) -> None:
        app.source_dir.get.return_value = ""
        app.dest_dir.get.return_value = ""
        with patch("file_reorganizer.app.suite_config") as mock_config:
            mock_config.load_last_directory.return_value = "/music/from/driver"
            app._seed_source_from_last_directory()
        app.source_dir.set.assert_called_once_with("/music/from/driver")
        app.dest_dir.set.assert_not_called()


class TestBrowseDirectories:
    """_browse_source/_browse_dest mirror the sibling-tool save-back pattern."""

    @staticmethod
    @pytest.fixture
    def app() -> FileReorganizerApp:
        app = object.__new__(FileReorganizerApp)
        app.source_dir = MagicMock()
        app.dest_dir = MagicMock()
        return app

    def test_browse_source_saves_last_directory(self, app: FileReorganizerApp) -> None:
        with (
            patch("file_reorganizer.app.filedialog") as mock_dialog,
            patch("file_reorganizer.app.suite_config") as mock_config,
        ):
            mock_dialog.askdirectory.return_value = "/music/picked"
            app._browse_source()
        app.source_dir.set.assert_called_once_with("/music/picked")
        mock_config.save_last_directory.assert_called_once_with("/music/picked")

    def test_browse_source_cancelled_saves_nothing(
        self, app: FileReorganizerApp
    ) -> None:
        with (
            patch("file_reorganizer.app.filedialog") as mock_dialog,
            patch("file_reorganizer.app.suite_config") as mock_config,
        ):
            mock_dialog.askdirectory.return_value = ""
            app._browse_source()
            mock_dialog.askdirectory.assert_called_once()
        app.source_dir.set.assert_not_called()
        mock_config.save_last_directory.assert_not_called()

    def test_browse_dest_never_saves_last_directory(
        self, app: FileReorganizerApp
    ) -> None:
        with (
            patch("file_reorganizer.app.filedialog") as mock_dialog,
            patch("file_reorganizer.app.suite_config") as mock_config,
        ):
            mock_dialog.askdirectory.return_value = "/music/destination"
            app._browse_dest()
        app.dest_dir.set.assert_called_once_with("/music/destination")
        mock_config.save_last_directory.assert_not_called()


class TestSettingsPersistence:
    """Settings delegate to the shared suite config — never the legacy file."""

    @staticmethod
    @pytest.fixture
    def app() -> FileReorganizerApp:
        app = object.__new__(FileReorganizerApp)
        app.source_dir = MagicMock()
        app.dest_dir = MagicMock()
        app.action = MagicMock()
        app.specific_text = MagicMock()
        app.various_text = MagicMock()
        return app

    def test_save_settings_excludes_source_dir(self, app: FileReorganizerApp) -> None:
        with patch("file_reorganizer.app.save_settings") as mock_save:
            app._save_settings()

        kwargs = mock_save.call_args.kwargs
        assert "source_dir" not in kwargs
        assert kwargs["dest_dir"] == app.dest_dir.get.return_value
        assert kwargs["action"] == app.action.get.return_value
        assert kwargs["specific_pattern"] == app.specific_text.get.return_value
        assert kwargs["various_pattern"] == app.various_text.get.return_value

    def test_load_settings_does_not_touch_source(self, app: FileReorganizerApp) -> None:
        payload = {
            "dest_dir": "/dest",
            "action": "move",
            "specific_pattern": "sp",
            "various_pattern": "va",
        }
        with patch("file_reorganizer.app.load_settings", return_value=payload):
            app._load_settings()

        app.source_dir.set.assert_not_called()
        app.dest_dir.set.assert_called_once_with("/dest")
        app.action.set.assert_called_once_with("move")
        app.specific_text.insert.assert_called_once_with("1.0", "sp")
        app.various_text.insert.assert_called_once_with("1.0", "va")


class TestMainLaunchWiring:
    def test_main_parses_argv_and_builds_app(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """main() must run the driver argv through parse_cli_args into the app."""
        import file_reorganizer.app as app_mod

        out = tmp_path / "out"
        argv = [
            "file_reorganizer",
            str(tmp_path),
            "--output-dir",
            str(out),
            "--action",
            "move",
        ]
        captured: dict[str, Any] = {}
        fake_root = MagicMock()

        def _fake_app(root: Any, **kwargs: Any) -> Any:
            captured["root"] = root
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(app_mod.tk, "Tk", lambda: fake_root)
        monkeypatch.setattr(app_mod, "FileReorganizerApp", _fake_app)
        monkeypatch.setattr(app_mod, "parse_cli_args", lambda parse_fn: parse_fn(argv))

        app_mod.main()

        assert captured["root"] is fake_root
        assert captured["directory"] == str(tmp_path)
        assert captured["output_dir"] == str(out)
        assert captured["action"] == "move"

    def test_main_forwards_the_driver_mode_flags(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The parsed --live/--start/--end flags must reach the app, not be dropped."""
        import file_reorganizer.app as app_mod

        argv = ["file_reorganizer", str(tmp_path), "--live", "--start", "--end"]
        captured: dict[str, Any] = {}

        def _fake_app(root: Any, **kwargs: Any) -> Any:
            captured.update(kwargs)
            return MagicMock()

        monkeypatch.setattr(app_mod.tk, "Tk", lambda: MagicMock())
        monkeypatch.setattr(app_mod, "FileReorganizerApp", _fake_app)
        monkeypatch.setattr(app_mod, "parse_cli_args", lambda parse_fn: parse_fn(argv))

        app_mod.main()

        assert captured["live_mode"] is True
        assert captured["auto_start"] is True
        assert captured["auto_end"] is True


# ---------------------------------------------------------------------------
# Stage 3 / item D3 (audit A4): the full app is constructed on a withdrawn
# Toplevel of the shared hidden root (setup tab, presets, settings, seeds), and
# the run flows are driven in-process with the engine seam mocked so the
# settings persistences stay off the real config file.
# ---------------------------------------------------------------------------


@pytest.fixture()
def app_root(root):
    import tkinter as tk

    top = tk.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


@pytest.fixture()
def real_app(app_root, monkeypatch):
    from file_reorganizer import app as app_mod

    monkeypatch.setattr(app_mod.suite_config, "load_last_directory", lambda: "")
    monkeypatch.setattr(
        app_mod,
        "load_settings",
        lambda: {
            "dest_dir": "",
            "action": "copy",
            "specific_pattern": "sp",
            "various_pattern": "va",
        },
    )
    return FileReorganizerApp(app_root)


def assert_bound(callback: object, name: str, obj: object) -> None:
    """Bound methods are fresh objects per access: compare attributes."""
    assert getattr(callback, "__self__", None) is obj
    assert getattr(callback, "__name__", None) == name


def _shell_app() -> Any:
    from file_reorganizer.app import FileReorganizerApp

    app = object.__new__(FileReorganizerApp)
    app.root = MagicMock()
    app.source_dir = MagicMock()
    app.dest_dir = MagicMock()
    app.action = MagicMock()
    app.run_mode = MagicMock()
    app.dry_run = MagicMock()
    app.running = MagicMock()
    app.overall_status = MagicMock()
    app.stats_label = MagicMock()
    app.progress = MagicMock()
    app.file_listbox = MagicMock()
    app.preview_btn = MagicMock()
    app.execute_btn = MagicMock()
    app.stop_btn = MagicMock()
    app.summary_label = MagicMock()
    app.specific_text = MagicMock()
    app.various_text = MagicMock()
    app.stats = ReorganizerStats()
    app._events = queue.SimpleQueue()
    app._poll_id = ""
    app._closing = False
    app._run_started = 0.0
    app._reorganizer = None
    app._thread = None
    return app


def _drain(app: Any) -> list[Any]:
    """Every event currently queued by the worker."""
    events: list[Any] = []
    while True:
        try:
            events.append(app._events.get_nowait())
        except queue.Empty:
            return events


class TestRealAppConstruction:
    def test_wiring_and_defaults(self, real_app):
        app = real_app
        assert app.dry_run.get() is True
        assert app.run_mode.get() == "Dry Run"
        assert app.running.get() is False
        assert app.source_dir.get() == ""

    def test_action_and_dry_survive_preset_application(self, real_app, tmp_path):
        app = real_app
        app._apply_preset(
            {
                "dest_dir": str(tmp_path),
                "action": "move",
                "dry_run": False,
                "specific_pattern": "{artist}/{album}",
                "various_pattern": "Various/{album}",
            }
        )
        assert app.action.get() == "move"
        assert app.run_mode.get() == "Live Update"
        assert app.dry_run.get() is False
        assert app.specific_text.get("1.0", "end-1c") == "{artist}/{album}"
        assert app.various_text.get("1.0", "end-1c") == "Various/{album}"

    def test_driver_argv_pre_fills_the_widgets(self, app_root, monkeypatch, tmp_path):
        """G2.1 acceptance: the driver's exact argv pre-fills the app."""
        from file_reorganizer import app as app_mod
        from file_reorganizer.utils.cli_args import parse

        monkeypatch.setattr(app_mod.suite_config, "load_last_directory", lambda: "")
        monkeypatch.setattr(
            app_mod,
            "load_settings",
            lambda: {
                "dest_dir": "",
                "action": "copy",
                "specific_pattern": "sp",
                "various_pattern": "va",
            },
        )
        out = tmp_path / "out"
        argv = [
            "file_reorganizer",
            str(tmp_path),
            "--output-dir",
            str(out),
            "--action",
            "move",
            "--specific-pattern",
            "{artist}/{album}",
            "--various-pattern",
            "Various/{album}",
        ]
        args = parse(argv)
        app = FileReorganizerApp(
            app_root,
            directory=args.folder_path,
            output_dir=args.output_dir,
            action=args.action,
            specific_pattern=args.specific_pattern,
            various_pattern=args.various_pattern,
        )
        assert app.source_dir.get() == str(tmp_path)
        assert app.dest_dir.get() == str(out)
        assert app.action.get() == "move"
        assert app.specific_text.get("1.0", "end-1c") == "{artist}/{album}"
        assert app.various_text.get("1.0", "end-1c") == "Various/{album}"

    def test_live_flag_starts_in_live_update_mode(self, app_root, monkeypatch):
        from file_reorganizer import app as app_mod

        monkeypatch.setattr(app_mod.suite_config, "load_last_directory", lambda: "")
        monkeypatch.setattr(
            app_mod,
            "load_settings",
            lambda: {
                "dest_dir": "",
                "action": "copy",
                "specific_pattern": "sp",
                "various_pattern": "va",
            },
        )
        app = FileReorganizerApp(app_root, live_mode=True)
        assert app.run_mode.get() == "Live Update"
        assert app.dry_run.get() is False


class TestModeControl:
    """The strip's Mode is the control; ``dry_run`` merely follows it."""

    def test_mode_change_updates_the_derived_flag(self, real_app):
        real_app.run_mode.set("Live Update")
        assert real_app.dry_run.get() is False
        real_app.run_mode.set("Dry Run")
        assert real_app.dry_run.get() is True

    def test_collected_settings_carry_mode_and_flag(self, real_app):
        real_app.run_mode.set("Live Update")
        settings = real_app._collect_settings()
        assert settings["run_mode"] == "Live Update"
        assert settings["dry_run"] is False

    def test_preset_round_trip_keeps_the_mode(self, real_app, tmp_path):
        real_app.run_mode.set("Live Update")
        settings = real_app._collect_settings()
        real_app.run_mode.set("Dry Run")
        real_app._apply_preset(settings)
        assert real_app.run_mode.get() == "Live Update"
        assert real_app.dry_run.get() is False


class TestValidationGuards:
    def _guard_app(self, source: str, dest: str) -> Any:
        from file_reorganizer.app import FileReorganizerApp

        app = object.__new__(FileReorganizerApp)
        app.root = MagicMock()
        app.source_dir = MagicMock()
        app.dest_dir = MagicMock()
        app.source_dir.get.return_value = source
        app.dest_dir.get.return_value = dest
        return app

    def test_preview_requires_a_real_source(
        self, app_root, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import file_reorganizer.app as app_mod

        app = self._guard_app("  ", "anything")
        shown = MagicMock()
        monkeypatch.setattr(app_mod.ui_common, "show_message", shown)
        monkeypatch.setattr(app_mod, "threading", MagicMock())

        app._preview()

        shown.assert_called_once()

    def test_preview_requires_destination(
        self, app_root, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        import file_reorganizer.app as app_mod

        app = self._guard_app(str(tmp_path), "")
        shown = MagicMock()
        monkeypatch.setattr(app_mod.ui_common, "show_message", shown)
        monkeypatch.setattr(app_mod, "threading", MagicMock())

        app._preview()

        shown.assert_called_once()

    def test_execute_requires_a_real_source(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import file_reorganizer.app as app_mod

        app = self._guard_app("", "anything")
        shown = MagicMock()
        monkeypatch.setattr(app_mod.ui_common, "show_message", shown)
        monkeypatch.setattr(app_mod, "threading", MagicMock())

        app._execute()

        shown.assert_called_once()

    def test_execute_requires_destination(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        import file_reorganizer.app as app_mod

        app = self._guard_app(str(tmp_path), "")
        shown = MagicMock()
        monkeypatch.setattr(app_mod.ui_common, "show_message", shown)
        monkeypatch.setattr(app_mod, "threading", MagicMock())

        app._execute()

        shown.assert_called_once()


class TestPreviewFlow:
    def test_preview_validates_then_starts_thread(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        app = _shell_app()
        fake_threading = MagicMock()
        monkeypatch.setattr("file_reorganizer.app.threading", fake_threading)
        monkeypatch.setattr("file_reorganizer.app.save_settings", MagicMock())
        app.source_dir.get.return_value = str(tmp_path / "src")
        app.dest_dir.get.return_value = str(tmp_path / "dst")
        (tmp_path / "src").mkdir()
        (tmp_path / "dst").mkdir()

        app._preview()

        assert app.overall_status.set.call_args_list[0].args[0] == "Previewing..."
        assert str(app.preview_btn.config.call_args.kwargs.get("state")) == "disabled"
        thread = fake_threading.Thread.call_args
        assert_bound(thread.kwargs["target"], "_preview_thread", app)
        fake_threading.Thread.return_value.start.assert_called_once_with()

    def test_preview_thread_runs_engine_and_posts_completion(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        app = _shell_app()

        engine_cls = MagicMock()
        monkeypatch.setattr("file_reorganizer.app.FileReorganizer", engine_cls)

        app._preview_thread(str(tmp_path / "src"), str(tmp_path / "dst"), "a", "b")

        engine_cls.assert_called_once()
        assert engine_cls.call_args.args[:2] == ("a", "b")
        assert engine_cls.call_args.args[2] == str(tmp_path / "dst")
        assert engine_cls.call_args.kwargs["dry_run"] is True
        assert app._reorganizer is engine_cls.return_value
        assert [event.kind for event in _drain(app)] == ["preview_done"]
        app.root.after.assert_not_called()

    def test_preview_progress_posts_an_event_without_touching_widgets(self) -> None:
        app = _shell_app()

        app._on_progress_preview("/lib/song.mp3", ReorganizerStats(files_scanned=1))

        (event,) = _drain(app)
        assert event.kind == "progress"
        assert event.path_info == "/lib/song.mp3"
        app.file_listbox.insert.assert_not_called()
        app.overall_status.set.assert_not_called()

    def test_preview_failure_posts_a_user_facing_error(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        from audio_suite_shared.exceptions import AudioSuiteError

        app = _shell_app()
        monkeypatch.setattr(
            "file_reorganizer.app.FileReorganizer",
            MagicMock(side_effect=AudioSuiteError("boom")),
        )

        app._preview_thread(str(tmp_path / "src"), str(tmp_path / "dst"), "a", "b")

        events = _drain(app)
        assert [event.kind for event in events] == ["error", "preview_done"]
        assert events[0].message.startswith("Preview failed.")
        app.root.after.assert_not_called()


class TestExecuteFlow:
    def test_execute_starts_thread_and_records_mode(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        app = _shell_app()
        fake_threading = MagicMock()
        monkeypatch.setattr("file_reorganizer.app.threading", fake_threading)
        monkeypatch.setattr("file_reorganizer.app.save_settings", MagicMock())
        app.source_dir.get.return_value = str(tmp_path / "src")
        app.dest_dir.get.return_value = str(tmp_path / "dst")
        (tmp_path / "src").mkdir()
        app.action.get.return_value = "move"
        app.dry_run.get.return_value = False

        app._execute()

        assert app.running.set.call_args_list[0].args[0] is True
        assert app.stop_btn.config.call_args.kwargs["state"] == "normal"
        assert app.overall_status.set.call_args_list[0].args[0] == "Executing..."
        thread = fake_threading.Thread.call_args
        assert_bound(thread.kwargs["target"], "_execute_thread", app)
        assert thread.kwargs["args"][:2] == (
            str(tmp_path / "src"),
            str(tmp_path / "dst"),
        ), thread.kwargs["args"]

    def test_execute_thread_runs_in_undo_batch_and_posts_completion(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        app = _shell_app()
        engine_cls = MagicMock()
        monkeypatch.setattr("file_reorganizer.app.FileReorganizer", engine_cls)
        app.action.get.return_value = "move"
        app.dry_run.get.return_value = False

        app._execute_thread(str(tmp_path / "src"), str(tmp_path / "dst"), "a", "b")

        engine_cls.assert_called_once()
        assert engine_cls.call_args.kwargs["dry_run"] is False
        assert engine_cls.call_args.kwargs["action"] == "move"
        assert [event.kind for event in _drain(app)] == ["execute_done"]
        app.root.after.assert_not_called()

    def test_finish_writes_the_shared_results_tab(self) -> None:
        app = _shell_app()
        app.stats = ReorganizerStats(
            files_scanned=9, files_processed=5, files_skipped=3, errors=1
        )

        app._finish()

        assert app.running.set.call_args.args[0] is False
        assert app.overall_status.set.call_args.args[0] == "Complete"
        summary = app.summary_label.config.call_args.kwargs["text"]
        assert "Scanned: 9" in summary
        assert "Processed: 5" in summary
        assert "Skipped: 3" in summary
        assert "Errors: 1" in summary
        # The shell records the target and switches to the Results tab.
        assert app._out_dir == app.dest_dir.get.return_value.strip()
        app.root.after.assert_called_once()

    def test_progress_callback_updates_the_shared_processing_widgets(self) -> None:
        app = _shell_app()
        stats = ReorganizerStats(
            files_scanned=9, files_processed=5, files_skipped=3, errors=1
        )

        app._update_ui(str(Path(str(Path("D:/lib/song.mp3")))), stats)

        assert app.overall_status.set.call_args.args[0] == "Current File: song.mp3"
        stats_text = app.stats_label.config.call_args.kwargs["text"]
        assert "Scanned: 9" in stats_text
        assert "Processed: 5" in stats_text
        assert "Skipped: 3" in stats_text
        assert "Errors: 1" in stats_text
        assert app.file_listbox.insert.call_args.args[1] == str(Path("D:/lib/song.mp3"))
        assert app.progress.__setitem__.call_args_list[1].args == ("value", 5)

    def test_stop_requests_engine_stop(self) -> None:
        app = _shell_app()
        engine = MagicMock()
        app._reorganizer = engine

        app._stop()

        engine.stop.assert_called_once()
        assert app.overall_status.set.call_args.args[0] == "Stopping..."


class TestWorkerHandoff:
    """The poller is the only place worker output reaches a widget."""

    def test_poller_drains_events_and_rearms_while_the_thread_lives(self) -> None:
        app = _shell_app()
        app._on_progress_preview("/lib/a.mp3", ReorganizerStats(files_scanned=1))
        thread = MagicMock()
        thread.is_alive.return_value = True
        app._thread = thread

        app._poll_events()

        assert app.file_listbox.insert.called
        assert app.root.after.called

    def test_poller_stops_once_the_thread_is_gone(self) -> None:
        import threading as real_threading

        app = _shell_app()
        done = real_threading.Thread(target=lambda: None)
        done.start()
        done.join()
        app._thread = done

        app._poll_events()

        app.root.after.assert_not_called()

    def test_error_event_reenables_buttons_and_reports_the_message(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from file_reorganizer.app import _RunEvent

        app = _shell_app()
        shown = MagicMock()
        app._on_error = shown

        app._handle_event(_RunEvent(kind="error", message="Preview failed."))

        shown.assert_called_once_with("Preview failed.")
        assert app.preview_btn.config.call_args.kwargs["state"] == "normal"
        assert app.execute_btn.config.call_args.kwargs["state"] == "normal"


class TestCloseLifecycle:
    def test_on_close_saves_and_stops(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        app = _shell_app()
        engine = MagicMock()
        app._reorganizer = engine
        fake_thread = MagicMock()
        fake_thread.is_alive.return_value = False
        app._thread = fake_thread
        save = MagicMock()
        monkeypatch.setattr("file_reorganizer.app.save_settings", save)

        app._on_close()

        engine.stop.assert_called_once()
        save.assert_called_once()
        app.root.destroy.assert_called_once_with()
        assert app._closing is True

    def test_on_close_cancels_a_pending_poll(self) -> None:
        app = _shell_app()
        app._poll_id = "after#7"
        app._save_settings = MagicMock()

        app._on_close()

        app.root.after_cancel.assert_called_once_with("after#7")
        assert app._poll_id == ""

    def test_run_enters_mainloop(self) -> None:
        app = _shell_app()
        app.run()
        app.root.mainloop.assert_called_once_with()
