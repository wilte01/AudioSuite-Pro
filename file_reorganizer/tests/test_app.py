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

from unittest.mock import MagicMock, patch

import pytest

from file_reorganizer.app import FileReorganizerApp


class TestSeedSourceFromLastDirectory:
    """_seed_source_from_last_directory() restores the Master Driver hand-off."""

    @pytest.fixture
    def app(self) -> FileReorganizerApp:
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
        app.source_dir.set.assert_not_called()

    def test_destination_is_never_seeded(self, app: FileReorganizerApp) -> None:
        app.source_dir.get.return_value = ""
        app.dest_dir.get.return_value = ""
        with patch("file_reorganizer.app.suite_config") as mock_config:
            mock_config.load_last_directory.return_value = "/music/from/driver"
            app._seed_source_from_last_directory()
        app.dest_dir.set.assert_not_called()


class TestBrowseDirectories:
    """_browse_source/_browse_dest mirror the sibling-tool save-back pattern."""

    @pytest.fixture
    def app(self) -> FileReorganizerApp:
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

    @pytest.fixture
    def app(self) -> FileReorganizerApp:
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
