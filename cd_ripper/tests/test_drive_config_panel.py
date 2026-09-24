"""
Tests for cd_ripper.ui.drive_config_panel — Detect Read Offset button.

Uses the AGENTS.md GUI pattern: ``object.__new__`` + ``MagicMock`` widgets,
no real Tk display. ``run_read_offset_detection`` is imported function-locally
by the worker, so it is patched at its source module.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from cd_ripper.core.offset_detect import ReadOffsetDetectionError
from cd_ripper.ui.drive_config_panel import DriveConfigPanel


def _panel(drive: str = "E:") -> DriveConfigPanel:
    panel = object.__new__(DriveConfigPanel)
    panel.frame = MagicMock()
    panel._offset_btn = MagicMock()
    panel._drive_var = MagicMock()
    panel._drive_var.get.return_value = drive
    panel._status_lbl = MagicMock()
    return panel


class TestDetectOffsetThreaded:
    def test_no_drive_selected_shows_warning_and_starts_no_thread(self) -> None:
        panel = _panel(drive="")
        with (
            patch("cd_ripper.ui.drive_config_panel.messagebox") as mb,
            patch("cd_ripper.ui.drive_config_panel.threading") as threading_mod,
        ):
            panel._detect_offset_threaded()
        mb.showwarning.assert_called_once()
        threading_mod.Thread.assert_not_called()
        panel._offset_btn.configure.assert_not_called()

    def test_disables_button_and_starts_worker_thread(self) -> None:
        panel = _panel(drive="E:")
        with (
            patch("cd_ripper.ui.drive_config_panel.messagebox"),
            patch("cd_ripper.ui.drive_config_panel.threading") as threading_mod,
        ):
            panel._detect_offset_threaded()
        panel._offset_btn.configure.assert_called_once_with(state="disabled")
        threading_mod.Thread.assert_called_once()
        # Bound methods are recreated on each attribute access, so compare
        # by value (== checks __func__ and __self__), not identity.
        assert (
            threading_mod.Thread.call_args.kwargs["target"]
            == panel._run_offset_detection
        )
        threading_mod.Thread.return_value.start.assert_called_once()


class TestRunOffsetDetectionWorker:
    def _captured_done_callback(self, panel: DriveConfigPanel) -> MagicMock:
        panel.frame.after = MagicMock()
        return panel.frame.after

    def test_success_schedules_done_with_offset(self) -> None:
        panel = _panel()
        after = self._captured_done_callback(panel)
        with patch(
            "cd_ripper.core.offset_detect.run_read_offset_detection",
            return_value=6,
        ):
            panel._run_offset_detection("E:")
        after.assert_called_once()
        delay, callback = after.call_args.args
        assert delay == 0

        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            callback()
        panel._offset_btn.configure.assert_called_once_with(state="normal")
        status_text = panel._status_lbl.configure.call_args.kwargs["text"]
        assert "offset +6 frames stored" in status_text
        mb.showinfo.assert_called_once()

    def test_pipeline_failure_schedules_done_with_error(self) -> None:
        panel = _panel()
        after = self._captured_done_callback(panel)
        with patch(
            "cd_ripper.core.offset_detect.run_read_offset_detection",
            side_effect=ReadOffsetDetectionError("no database record"),
        ):
            panel._run_offset_detection("E:")
        after.assert_called_once()
        callback = after.call_args.args[1]

        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            callback()
        panel._offset_btn.configure.assert_called_once_with(state="normal")
        status_text = panel._status_lbl.configure.call_args.kwargs["text"]
        assert "failed" in status_text
        assert "no database record" in status_text
        mb.showerror.assert_called_once()

    def test_device_error_schedules_done_with_error(self) -> None:
        from audio_suite_shared.exceptions import AudioIOError

        panel = _panel()
        after = self._captured_done_callback(panel)
        with patch(
            "cd_ripper.core.offset_detect.run_read_offset_detection",
            side_effect=AudioIOError("Cannot open CD device"),
        ):
            panel._run_offset_detection("E:")
        callback = after.call_args.args[1]

        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            callback()
        status_text = panel._status_lbl.configure.call_args.kwargs["text"]
        assert "Cannot open CD device" in status_text
        mb.showerror.assert_called_once()


class TestOnOffsetDetectionDone:
    def test_success_status_uses_bare_drive_letter(self) -> None:
        panel = _panel(drive="E:")
        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            panel._on_offset_detection_done(6, None)
        status_text = panel._status_lbl.configure.call_args.kwargs["text"]
        assert "drive E." in status_text
        panel._offset_btn.configure.assert_called_once_with(state="normal")
        mb.showinfo.assert_called_once()

    def test_error_status_is_flagged(self) -> None:
        panel = _panel()
        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            panel._on_offset_detection_done(None, "boom")
        kwargs = panel._status_lbl.configure.call_args.kwargs
        assert kwargs["text"] == "Read-offset detection failed: boom"
        assert kwargs["fg"] == "#cc0000"
        mb.showerror.assert_called_once()

    def test_normalises_drive_suffix_in_status(self) -> None:
        panel = _panel(drive="E:\\")
        with patch("cd_ripper.ui.drive_config_panel.messagebox"):
            panel._on_offset_detection_done(0, None)
        status_text = panel._status_lbl.configure.call_args.kwargs["text"]
        assert "drive E." in status_text


@pytest.mark.parametrize("offset", [0, 6, 587])
def test_success_message_reports_signed_offset(offset: int) -> None:
    panel = _panel()
    with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
        panel._on_offset_detection_done(offset, None)
    status_text = panel._status_lbl.configure.call_args.kwargs["text"]
    assert f"offset {offset:+d} frames" in status_text
    mb.showinfo.assert_called_once()
