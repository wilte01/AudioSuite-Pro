"""
test_ui_helpers.py — Unit tests for audio_suite_shared.ui_helpers

Strategy
--------
ui_helpers wraps platform_utils and suite_config; all external I/O is mocked.
No Tkinter display is required for these tests — filedialog, messagebox, and
platform_utils are patched throughout.

Covers:
    • browse_folder_dialog: cancelled dialog returns None
    • browse_folder_dialog: valid folder returned and path_variable set
    • browse_folder_dialog: non-existent selection shows error
    • browse_folder_dialog: non-directory path shows error
    • browse_folder_dialog: exception handled gracefully
    • show_error_from_exception: maps exception and shows error dialog
    • open_help_guide: delegates to platform_utils.open_help
    • open_help_guide: exception from platform_utils handled gracefully
    • open_log_file: existing path delegates to platform_utils.open_path
    • open_log_file: missing log shows info dialog
    • open_log_file: exception handled gracefully
    • open_folder_path: existing folder delegates to platform_utils.open_path
    • open_folder_path: missing folder shows info dialog
    • UIHelperMixin: _browse_folder_standard, _open_help_standard,
      _open_log_standard, _open_folder_standard delegate correctly
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import audio_suite_shared.ui_helpers as ui_helpers

# ---------------------------------------------------------------------------
# browse_folder_dialog
# ---------------------------------------------------------------------------


class TestBrowseFolderDialog:
    """Tests for browse_folder_dialog."""

    def test_cancelled_dialog_returns_none(self) -> None:
        with patch(
            "audio_suite_shared.ui_helpers.filedialog.askdirectory", return_value=""
        ):
            result = ui_helpers.browse_folder_dialog("Pick folder")
            assert result is None

    def test_valid_folder_returned(self, tmp_path: Path) -> None:
        with (
            patch(
                "audio_suite_shared.ui_helpers.filedialog.askdirectory",
                return_value=str(tmp_path),
            ),
            patch("audio_suite_shared.ui_helpers.suite_config.save_last_directory"),
        ):
            result = ui_helpers.browse_folder_dialog("Pick folder")
            assert result == str(tmp_path)

    def test_valid_folder_sets_path_variable(self, tmp_path: Path) -> None:
        var = MagicMock()
        with (
            patch(
                "audio_suite_shared.ui_helpers.filedialog.askdirectory",
                return_value=str(tmp_path),
            ),
            patch("audio_suite_shared.ui_helpers.suite_config.save_last_directory"),
        ):
            ui_helpers.browse_folder_dialog("Pick", path_variable=var)
            var.set.assert_called_once_with(str(tmp_path))

    def test_nonexistent_folder_shows_error(self) -> None:
        with (
            patch(
                "audio_suite_shared.ui_helpers.filedialog.askdirectory",
                return_value="/does/not/exist/xyz",
            ),
            patch("audio_suite_shared.ui_helpers.messagebox.showerror") as mock_err,
        ):
            result = ui_helpers.browse_folder_dialog("Pick")
            assert result is None
            mock_err.assert_called_once()

    def test_not_a_directory_shows_error(self, tmp_path: Path) -> None:
        fake_file = tmp_path / "track.mp3"
        fake_file.write_bytes(b"data")
        with (
            patch(
                "audio_suite_shared.ui_helpers.filedialog.askdirectory",
                return_value=str(fake_file),
            ),
            patch("audio_suite_shared.ui_helpers.messagebox.showerror") as mock_err,
        ):
            result = ui_helpers.browse_folder_dialog("Pick")
            assert result is None
            mock_err.assert_called_once()

    def test_save_last_dir_false_skips_save(self, tmp_path: Path) -> None:
        with (
            patch(
                "audio_suite_shared.ui_helpers.filedialog.askdirectory",
                return_value=str(tmp_path),
            ) as mock_ask,
            patch(
                "audio_suite_shared.ui_helpers.suite_config.save_last_directory"
            ) as mock_save,
        ):
            ui_helpers.browse_folder_dialog("Pick", save_last_dir=False)
            mock_ask.assert_called_once()
            mock_save.assert_not_called()

    def test_exception_shows_error_and_returns_none(self) -> None:
        with (
            patch(
                "audio_suite_shared.ui_helpers.filedialog.askdirectory",
                side_effect=OSError("dialog crashed"),
            ),
            patch("audio_suite_shared.ui_helpers.messagebox.showerror") as mock_err,
        ):
            result = ui_helpers.browse_folder_dialog("Pick")
            assert result is None
            mock_err.assert_called_once()

    def test_error_logger_argument_ignored_after_deprecation(self) -> None:
        """
        ``error_logger`` is retained for API compatibility only.  Validation
        failures must show a dialog directly, never call the deprecated
        ``log_and_show_error`` method.
        """
        mock_logger = MagicMock()
        with (
            patch(
                "audio_suite_shared.ui_helpers.filedialog.askdirectory",
                return_value="/does/not/exist",
            ),
            patch("audio_suite_shared.ui_helpers.messagebox.showerror") as mock_err,
        ):
            ui_helpers.browse_folder_dialog("Pick", error_logger=mock_logger)
            mock_logger.log_and_show_error.assert_not_called()
            mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# show_error_from_exception
# ---------------------------------------------------------------------------


class TestShowErrorFromException:
    """Tests for show_error_from_exception."""

    def test_maps_and_shows_error_dialog(self) -> None:
        with (
            patch("audio_suite_shared.ui_helpers.messagebox.showerror") as mock_err,
            patch("audio_suite_shared.ui_helpers.map_to_audio_error") as mock_map,
            patch("audio_suite_shared.ui_helpers.user_message_for") as mock_msg,
        ):
            mock_map.return_value = RuntimeError("mapped")
            mock_msg.return_value = "Friendly message"
            ui_helpers.show_error_from_exception(ValueError("boom"))
            mock_map.assert_called_once()
            mock_msg.assert_called_once_with(mock_map.return_value)
            mock_err.assert_called_once_with("Error", "Friendly message")

    def test_uses_custom_title(self) -> None:
        with (
            patch("audio_suite_shared.ui_helpers.messagebox.showerror") as mock_err,
            patch("audio_suite_shared.ui_helpers.map_to_audio_error") as mock_map,
            patch(
                "audio_suite_shared.ui_helpers.user_message_for",
                return_value="msg",
            ),
        ):
            exc = FileNotFoundError("missing")
            mock_map.return_value = exc
            ui_helpers.show_error_from_exception(exc, title="Scan Failed")
            mock_err.assert_called_once_with("Scan Failed", "msg")

    def test_logs_mapped_error(self) -> None:
        with (
            patch("audio_suite_shared.ui_helpers.messagebox.showerror"),
            patch("audio_suite_shared.ui_helpers.map_to_audio_error") as mock_map,
            patch("audio_suite_shared.ui_helpers.logger") as mock_log,
        ):
            exc = PermissionError("denied")
            mock_map.return_value = exc
            ui_helpers.show_error_from_exception(exc)
            mock_log.error.assert_called_once()


# ---------------------------------------------------------------------------
# open_help_guide
# ---------------------------------------------------------------------------


class TestOpenHelpGuide:
    """Tests for open_help_guide."""

    def test_delegates_to_platform_open_help(self) -> None:
        with patch(
            "audio_suite_shared.ui_helpers.platform_utils.open_help"
        ) as mock_open:
            ui_helpers.open_help_guide("BPM_Analyzer_User_Guide.docx", "")
            mock_open.assert_called_once_with("BPM_Analyzer_User_Guide.docx")

    def test_exception_shows_error(self) -> None:
        with (
            patch(
                "audio_suite_shared.ui_helpers.platform_utils.open_help",
                side_effect=OSError("no file"),
            ),
            patch("audio_suite_shared.ui_helpers.messagebox.showerror") as mock_err,
        ):
            ui_helpers.open_help_guide("Missing_Guide.docx", "")
            mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# open_log_file
# ---------------------------------------------------------------------------


class TestOpenLogFile:
    """Tests for open_log_file."""

    def test_existing_log_calls_open_path(self, tmp_path: Path) -> None:
        log = tmp_path / "audio_suite.log"
        log.write_text("log data")
        with patch(
            "audio_suite_shared.ui_helpers.platform_utils.open_path"
        ) as mock_open:
            ui_helpers.open_log_file(str(log))
            mock_open.assert_called_once_with(str(log))

    def test_missing_log_shows_info(self) -> None:
        with patch("audio_suite_shared.ui_helpers.messagebox.showinfo") as mock_info:
            ui_helpers.open_log_file("")
            mock_info.assert_called_once()

    def test_nonexistent_log_path_shows_info(self) -> None:
        with patch("audio_suite_shared.ui_helpers.messagebox.showinfo") as mock_info:
            ui_helpers.open_log_file("/nonexistent/path.log")
            mock_info.assert_called_once()

    def test_exception_shows_error(self, tmp_path: Path) -> None:
        log = tmp_path / "audio_suite.log"
        log.write_text("x")
        with (
            patch(
                "audio_suite_shared.ui_helpers.platform_utils.open_path",
                side_effect=OSError("failed"),
            ),
            patch("audio_suite_shared.ui_helpers.messagebox.showerror") as mock_err,
        ):
            ui_helpers.open_log_file(str(log))
            mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# open_folder_path
# ---------------------------------------------------------------------------


class TestOpenFolderPath:
    """Tests for open_folder_path."""

    def test_existing_folder_calls_open_path(self, tmp_path: Path) -> None:
        with patch(
            "audio_suite_shared.ui_helpers.platform_utils.open_path"
        ) as mock_open:
            ui_helpers.open_folder_path(str(tmp_path))
            mock_open.assert_called_once_with(str(tmp_path))

    def test_empty_path_shows_info(self) -> None:
        with patch("audio_suite_shared.ui_helpers.messagebox.showinfo") as mock_info:
            ui_helpers.open_folder_path("")
            mock_info.assert_called_once()

    def test_nonexistent_folder_shows_info(self) -> None:
        with patch("audio_suite_shared.ui_helpers.messagebox.showinfo") as mock_info:
            ui_helpers.open_folder_path("/no/such/dir")
            mock_info.assert_called_once()

    def test_exception_shows_error(self, tmp_path: Path) -> None:
        with (
            patch(
                "audio_suite_shared.ui_helpers.platform_utils.open_path",
                side_effect=OSError("fail"),
            ),
            patch("audio_suite_shared.ui_helpers.messagebox.showerror") as mock_err,
        ):
            ui_helpers.open_folder_path(str(tmp_path))
            mock_err.assert_called_once()


# ---------------------------------------------------------------------------
# UIHelperMixin
# ---------------------------------------------------------------------------


class TestUIHelperMixin:
    """Tests for UIHelperMixin delegation methods."""

    def _make_mixin(self) -> ui_helpers.UIHelperMixin:
        obj = ui_helpers.UIHelperMixin()
        obj.error_logger = None
        obj._log_path = ""
        obj._out_dir = ""
        return obj

    def test_browse_folder_standard_delegates(self) -> None:
        mixin = self._make_mixin()
        var = MagicMock()
        var.get.return_value = ""

        with patch("audio_suite_shared.ui_helpers.browse_folder_dialog") as mock_browse:
            mixin._browse_folder_standard(path_variable=var)
            mock_browse.assert_called_once()

    def test_open_help_standard_delegates(self) -> None:
        mixin = self._make_mixin()
        with patch("audio_suite_shared.ui_helpers.open_help_guide") as mock_help:
            mixin._open_help_standard("BPM_Analyzer_User_Guide.docx")
            mock_help.assert_called_once_with("BPM_Analyzer_User_Guide.docx", None)

    def test_open_log_standard_delegates(self) -> None:
        mixin = self._make_mixin()
        with patch("audio_suite_shared.ui_helpers.open_log_file") as mock_log:
            mixin._open_log_standard()
            mock_log.assert_called_once_with("")

    def test_open_folder_standard_delegates(self) -> None:
        mixin = self._make_mixin()
        with patch("audio_suite_shared.ui_helpers.open_folder_path") as mock_folder:
            mixin._open_folder_standard()
            mock_folder.assert_called_once_with("")
