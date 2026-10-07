"""
tests/test_app.py
Tests for app.py — FileReorganizerApp orchestration logic.

Run with:
    pytest tests/test_app.py -v

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
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from file_reorganizer.app import FileReorganizerApp


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


# ---------------------------------------------------------------------------
# Stage 3 / item D3 (audit A4): the full app is constructed on a withdrawn
# Toplevel of the shared hidden root (setup_ui, presets, settings, seeds), and
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
    from file_reorganizer.app import FileReorganizerApp

    monkeypatch.setattr(
        "file_reorganizer.app.suite_config.load_last_directory", lambda: ""
    )
    return FileReorganizerApp(app_root)


def assert_bound(callback: object, name: str, obj: object) -> None:
    """Bound methods are fresh objects per access: compare attributes."""
    assert getattr(callback, "__self__", None) is obj
    assert getattr(callback, "__name__", None) == name


def _shell_app():
    from file_reorganizer.app import FileReorganizerApp

    app = object.__new__(FileReorganizerApp)
    app.root = MagicMock()
    app.source_dir = MagicMock()
    app.dest_dir = MagicMock()
    app.action = MagicMock()
    app.dry_run = MagicMock()
    app.running = MagicMock()
    app.files_scanned = MagicMock()
    app.files_processed = MagicMock()
    app.files_skipped = MagicMock()
    app.errors = MagicMock()
    app.current_file = MagicMock()
    app.preview_list = MagicMock()
    app.status_var = MagicMock()
    app.preview_btn = MagicMock()
    app.execute_btn = MagicMock()
    app.stop_btn = MagicMock()
    app.specific_text = MagicMock()
    app.various_text = MagicMock()
    app._reorganizer = None
    app._thread = None
    return app


class TestRealAppConstruction:
    def test_wiring_and_defaults(self, real_app):
        app = real_app
        assert app.dry_run.get() is True
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
        assert app.dry_run.get() is False
        assert app.specific_text.get("1.0", "end-1c") == "{artist}/{album}"
        assert app.various_text.get("1.0", "end-1c") == "Various/{album}"


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
        app_mod.ui_common.show_message = shown  # type: ignore[attr-defined]
        monkeypatch.setattr(app_mod, "threading", MagicMock())

        app._preview()

        shown.assert_called_once()

    def test_preview_requires_destination(
        self, app_root, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        import file_reorganizer.app as app_mod

        app = self._guard_app(str(tmp_path), "")
        shown = MagicMock()
        app_mod.ui_common.show_message = shown  # type: ignore[attr-defined]
        monkeypatch.setattr(app_mod, "threading", MagicMock())

        app._preview()

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

        assert app.status_var.set.call_args_list[0].args[0] == "Previewing..."
        assert str(app.preview_btn.config.call_args.kwargs.get("state")) == "disabled"
        thread = fake_threading.Thread.call_args
        assert_bound(thread.kwargs["target"], "_preview_thread", app)
        fake_threading.Thread.return_value.start.assert_called_once_with()

    def test_preview_thread_runs_engine_and_schedules_finish(
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
        after_calls = app.root.after.call_args_list
        completion = [call for call in after_calls if call.args[0] == 0]
        assert completion, "status, button and thread-clear resets were scheduled"


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
        assert app.status_var.set.call_args_list[0].args[0] == "Executing..."
        thread = fake_threading.Thread.call_args
        assert_bound(thread.kwargs["target"], "_execute_thread", app)
        assert thread.kwargs["args"][:2] == (
            str(tmp_path / "src"),
            str(tmp_path / "dst"),
        ), thread.kwargs["args"]

    def test_execute_thread_runs_in_undo_batch_and_finishes(
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
        finish_scheduled = [
            call
            for call in app.root.after.call_args_list
            if len(call.args) >= 2 and call.args[1].__name__ == "_finish"
        ]
        assert finish_scheduled
        app._finish()
        assert app.running.set.call_args.args[0] is False
        assert app.status_var.set.call_args.args[0] == "Complete"

    def test_progress_callback_updates_all_stat_vars(self) -> None:
        from file_reorganizer.core.engine import ReorganizerStats

        app = _shell_app()
        app.root.after = MagicMock()
        stats = ReorganizerStats(
            files_scanned=9, files_processed=5, files_skipped=3, errors=1
        )
        app._update_ui(str(Path(str(Path("D:/lib/song.mp3")))), stats)
        assert app.current_file.set.call_args.args[0] == "song.mp3"
        assert app.files_scanned.set.call_args.args[0] == 9
        assert app.files_processed.set.call_args.args[0] == 5
        assert app.files_skipped.set.call_args.args[0] == 3
        assert app.errors.set.call_args.args[0] == 1

    def test_stop_requests_engine_stop(self) -> None:
        app = _shell_app()
        engine = MagicMock()
        app._reorganizer = engine

        app._stop()

        engine.stop.assert_called_once()
        assert app.status_var.set.call_args.args[0] == "Stopping..."


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

    def test_run_enters_mainloop(self) -> None:
        app = _shell_app()
        app.run()
        app.root.mainloop.assert_called_once_with()
