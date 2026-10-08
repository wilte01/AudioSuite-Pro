"""
Tests for cd_ripper.ui.drive_config_panel — drive refresh, C2 diagnostic,
disc read, release application (offset detection has its own classes).

Uses the AGENTS.md GUI pattern: ``object.__new__`` + ``MagicMock`` widgets,
no real Tk display. Function-local worker imports (``read_toc``,
``diagnose_c2_reliability``) are patched at their source module.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cd_ripper.core.disc import DiscInfo
from cd_ripper.core.drive_handler import SECTORS_PER_SEC
from cd_ripper.core.offset_detect import ReadOffsetDetectionError
from cd_ripper.core.track_processor import C2DiagnosticResult
from cd_ripper.ui.drive_config_panel import DriveConfigPanel


def _panel(drive: str = "E:") -> DriveConfigPanel:
    panel = object.__new__(DriveConfigPanel)
    panel.frame = MagicMock()
    panel._offset_btn = MagicMock()
    panel._drive_var = MagicMock()
    panel._drive_var.get.return_value = drive
    panel._status_lbl = MagicMock()
    return panel


def _full_panel(drive: str = "E:") -> DriveConfigPanel:
    """Panel shell with every widget/attribute the non-offset paths touch."""
    panel = _panel(drive)
    panel.state: dict[str, Any] = {}
    panel._c2_btn = MagicMock()
    panel._read_btn = MagicMock()
    panel._read_progress = MagicMock()
    panel._drive_combo = MagicMock()
    panel._release_combo = MagicMock()
    panel._disc_info: DiscInfo | None = None
    panel._on_disc_read_cb: Any = None
    panel._on_release_applied_cb: Any = None
    panel._set_proceed_enabled = MagicMock()
    return panel


def _status_text(panel: DriveConfigPanel) -> str:
    return panel._status_lbl.configure.call_args.kwargs["text"]


def _c2_result(
    *, honest: bool = True, all_zero: bool = False, matched: bool = True
) -> C2DiagnosticResult:
    return C2DiagnosticResult(
        lba_tested=150,
        sectors_tested=8,
        audio_data_matched=matched,
        c2_flags_all_zero=all_zero,
        c2_nonzero_byte_count=0 if all_zero else 3,
        c2_appears_honest=honest,
        detail="detail",
    )


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


class TestRefreshDrives:
    def test_unsupported_platform_clears_combo_and_warns(self) -> None:
        panel = _full_panel()
        with patch(
            "cd_ripper.ui.drive_config_panel.platform_supported",
            return_value=False,
        ):
            panel.refresh_drives()
        panel._drive_combo.__setitem__.assert_called_once_with("values", [])
        assert "not supported on this OS" in _status_text(panel)
        assert panel._status_lbl.configure.call_args.kwargs["fg"] == "#cc0000"
        panel._drive_combo.current.assert_not_called()

    def test_supported_platform_with_drives_selects_first(self) -> None:
        panel = _full_panel()
        with (
            patch(
                "cd_ripper.ui.drive_config_panel.platform_supported",
                return_value=True,
            ),
            patch(
                "cd_ripper.ui.drive_config_panel.list_cd_drives",
                return_value=["E:"],
            ),
        ):
            panel.refresh_drives()
        panel._drive_combo.__setitem__.assert_called_once_with("values", ["E:"])
        panel._drive_combo.current.assert_called_once_with(0)
        assert "Drive(s) found" in _status_text(panel)

    def test_supported_platform_without_drives_reports_none(self) -> None:
        panel = _full_panel()
        with (
            patch(
                "cd_ripper.ui.drive_config_panel.platform_supported",
                return_value=True,
            ),
            patch("cd_ripper.ui.drive_config_panel.list_cd_drives", return_value=[]),
        ):
            panel.refresh_drives()
        assert _status_text(panel) == "No CD drive detected."
        assert panel._status_lbl.configure.call_args.kwargs["fg"] == "#cc0000"
        panel._drive_combo.current.assert_not_called()


class TestC2Threaded:
    def test_no_drive_selected_shows_warning_and_starts_no_thread(self) -> None:
        panel = _full_panel(drive="")
        with (
            patch("cd_ripper.ui.drive_config_panel.messagebox") as mb,
            patch("cd_ripper.ui.drive_config_panel.threading") as threading_mod,
        ):
            panel._test_c2_threaded()
        mb.showwarning.assert_called_once()
        threading_mod.Thread.assert_not_called()
        panel._c2_btn.configure.assert_not_called()

    def test_disables_button_and_starts_worker_thread(self) -> None:
        panel = _full_panel(drive="E:")
        with (
            patch("cd_ripper.ui.drive_config_panel.messagebox"),
            patch("cd_ripper.ui.drive_config_panel.threading") as threading_mod,
        ):
            panel._test_c2_threaded()
        panel._c2_btn.configure.assert_called_once_with(state="disabled")
        assert threading_mod.Thread.call_args.kwargs["target"] == (
            panel._run_c2_diagnostic
        )
        threading_mod.Thread.return_value.start.assert_called_once()


class TestRunC2DiagnosticWorker:
    def _after(self, panel: DriveConfigPanel) -> MagicMock:
        panel.frame.after = MagicMock()
        return panel.frame.after

    def test_empty_toc_schedules_done_with_insert_disc_error(self) -> None:
        """Regression: AudioIOError (empty TOC) must be caught like OSError.

        It escaped the worker's except tuple, so no done-callback was
        scheduled: the C2 button stayed disabled and no dialog appeared.
        """
        panel = _full_panel()
        after = self._after(panel)
        with patch("cd_ripper.core.ripper.read_toc", return_value=[]):
            panel._run_c2_diagnostic("E:")
        after.assert_called_once()
        delay, callback = after.call_args.args
        assert delay == 0

        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            callback()
        panel._c2_btn.configure.assert_called_once_with(state="normal")
        assert "insert a disc" in _status_text(panel)
        mb.showerror.assert_called_once()

    def test_read_toc_oserror_schedules_done_with_error(self) -> None:
        panel = _full_panel()
        after = self._after(panel)
        with patch(
            "cd_ripper.core.ripper.read_toc",
            side_effect=OSError("device not ready"),
        ):
            panel._run_c2_diagnostic("E:")
        delay, callback = after.call_args.args
        assert delay == 0
        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            callback()
        assert "device not ready" in _status_text(panel)
        mb.showerror.assert_called_once()

    def test_success_runs_diagnostic_at_toc_start_plus_two_seconds(self) -> None:
        from cd_ripper.ui import drive_config_panel as dcp

        panel = _full_panel()
        after = self._after(panel)
        expected = _c2_result()
        with (
            patch(
                "cd_ripper.core.ripper.read_toc",
                return_value=[{"start_lba": 150}],
            ),
            patch(
                "cd_ripper.core.ripper.diagnose_c2_reliability",
                return_value=expected,
            ) as diagnose,
        ):
            panel._run_c2_diagnostic("E:")
        args = diagnose.call_args
        assert args.args[0] == "E"
        assert args.args[1] == 150 + SECTORS_PER_SEC * 2
        assert args.args[2] is dcp.write_log_line
        assert args.kwargs["sectors"] == 8
        delay, callback = after.call_args.args
        assert delay == 0
        with patch("cd_ripper.ui.drive_config_panel.messagebox"):
            callback()
        panel._c2_btn.configure.assert_called_once_with(state="normal")
        assert "populate C2 error flags" in _status_text(panel)


class TestOnC2DiagnosticDone:
    def test_error_reenables_button_and_shows_dialog(self) -> None:
        panel = _full_panel()
        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            panel._on_c2_diagnostic_done(None, "boom")
        panel._c2_btn.configure.assert_called_once_with(state="normal")
        assert _status_text(panel) == "C2 test failed: boom"
        assert panel._status_lbl.configure.call_args.kwargs["fg"] == "#cc0000"
        mb.showerror.assert_called_once_with("C2 Diagnostic Failed", "boom")

    def test_honest_drive_reported_without_error_flag(self) -> None:
        panel = _full_panel()
        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            panel._on_c2_diagnostic_done(_c2_result(honest=True), None)
        assert "populate C2 error flags" in _status_text(panel)
        assert panel._status_lbl.configure.call_args.kwargs["fg"] != "#cc0000"
        mb.showinfo.assert_called_once()

    def test_all_zero_flags_flagged_as_unreliable(self) -> None:
        panel = _full_panel()
        with patch("cd_ripper.ui.drive_config_panel.messagebox"):
            panel._on_c2_diagnostic_done(_c2_result(honest=False, all_zero=True), None)
        assert "all-zero" in _status_text(panel)
        assert panel._status_lbl.configure.call_args.kwargs["fg"] == "#cc0000"

    def test_mismatched_audio_reported_as_bad_test_spot(self) -> None:
        panel = _full_panel()
        with patch("cd_ripper.ui.drive_config_panel.messagebox"):
            panel._on_c2_diagnostic_done(
                _c2_result(honest=False, all_zero=False, matched=False), None
            )
        assert "differed between the two test reads" in _status_text(panel)
        assert panel._status_lbl.configure.call_args.kwargs["fg"] == "#cc0000"


class TestReadDiscThreaded:
    def test_no_drive_selected_shows_warning_and_starts_no_thread(self) -> None:
        panel = _full_panel(drive="")
        with (
            patch("cd_ripper.ui.drive_config_panel.messagebox") as mb,
            patch("cd_ripper.ui.drive_config_panel.threading") as threading_mod,
        ):
            panel._read_disc_threaded()
        mb.showwarning.assert_called_once()
        threading_mod.Thread.assert_not_called()
        panel._read_btn.configure.assert_not_called()

    def test_disables_button_packs_progress_and_starts_thread(self) -> None:
        panel = _full_panel(drive="E:")
        with (
            patch("cd_ripper.ui.drive_config_panel.messagebox"),
            patch("cd_ripper.ui.drive_config_panel.threading") as threading_mod,
        ):
            panel._read_disc_threaded()
        panel._read_btn.configure.assert_called_once_with(state="disabled")
        panel._set_proceed_enabled.assert_called_once_with(False)
        panel._read_progress.pack.assert_called_once()
        panel._read_progress.start.assert_called_once_with(12)
        assert _status_text(panel) == "Reading disc…"
        threading_mod.Thread.assert_called_once()
        assert threading_mod.Thread.call_args.kwargs["daemon"] is True
        threading_mod.Thread.return_value.start.assert_called_once()

    def test_thread_without_proceed_hook_still_reads(self) -> None:
        panel = _full_panel(drive="E:")
        panel._set_proceed_enabled = None
        with (
            patch("cd_ripper.ui.drive_config_panel.messagebox"),
            patch("cd_ripper.ui.drive_config_panel.threading") as threading_mod,
        ):
            panel._read_disc_threaded()
        assert threading_mod.Thread.call_count == 1


class TestOnDiscRead:
    @staticmethod
    def _info(**kwargs: Any) -> DiscInfo:
        info = DiscInfo()
        info.drive = "E:"
        info.disc_id = "abc123"
        for key, value in kwargs.items():
            setattr(info, key, value)
        return info

    def test_error_without_tracks_shows_dialog_and_stops(self) -> None:
        panel = _full_panel()
        cb = MagicMock()
        panel._on_disc_read_cb = cb
        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            panel._on_disc_read(self._info(error="No disc found"))
        panel._read_progress.stop.assert_called_once()
        panel._read_btn.configure.assert_called_once_with(state="normal")
        assert _status_text(panel) == "No disc found"
        mb.showerror.assert_called_once()
        cb.assert_not_called()
        panel._set_proceed_enabled.assert_not_called()
        assert panel.state == {}

    def test_error_with_tracks_continues_as_warning(self) -> None:
        panel = _full_panel()
        tracks = [{"number": 1, "title": "One"}]
        with patch("cd_ripper.ui.drive_config_panel.messagebox") as mb:
            panel._on_disc_read(
                self._info(tracks=tracks, error="MusicBrainz lookup failed")
            )
        assert _status_text(panel).startswith("Warning: MusicBrainz lookup failed")
        mb.showerror.assert_not_called()
        assert panel.state["tracks"] == tracks

    def test_clean_read_populates_combo_state_and_callbacks(self) -> None:
        panel = _full_panel()
        tracks = [{"number": 1, "title": "One"}]
        releases = [
            {
                "title": "Greatest Hits",
                "date": "1999-05-01",
                "country": "GB",
                "artist-credit": [{"artist": {"name": "Queen"}}],
            }
        ]
        cb = MagicMock()
        release_cb = MagicMock()
        panel._on_disc_read_cb = cb
        panel._on_release_applied_cb = release_cb
        info = self._info(
            tracks=tracks,
            mb_releases=releases,
            release_info=releases[0],
        )

        panel._on_disc_read(info)

        assert _status_text(panel) == ("Found 1 track(s). MusicBrainz match found.")
        panel._release_combo.__setitem__.assert_called_once()
        values = panel._release_combo.__setitem__.call_args.args[1]
        assert values == ["Queen – Greatest Hits  (1999)  [GB]"]
        panel._release_combo.current.assert_called_once_with(0)
        cb.assert_called_once_with(info)
        assert panel.state == {
            "tracks": tracks,
            "disc_id": "abc123",
            "release_info": releases[0],
            "drive": "E:",
        }
        panel._set_proceed_enabled.assert_called_once_with(True)

    def test_no_release_candidates_shows_manual_entry_hint(self) -> None:
        panel = _full_panel()
        info = self._info(tracks=[{"number": 1}])
        panel._on_disc_read(info)
        values = panel._release_combo.__setitem__.call_args.args[1]
        assert values == ["(No MusicBrainz match — enter metadata manually)"]
        assert "No MusicBrainz match." in _status_text(panel)

    def test_absent_callbacks_and_proceed_hook_are_skipped(self) -> None:
        panel = _full_panel()
        panel._on_disc_read_cb = None
        panel._set_proceed_enabled = None
        panel._on_disc_read(self._info(tracks=[{"number": 1}]))
        assert panel.state["disc_id"] == "abc123"
        assert panel.state["tracks"] == [{"number": 1}]


class TestReleaseLabel:
    def test_joins_artist_credits_and_truncates_date(self) -> None:
        panel = _full_panel()
        label = panel._release_label(
            {
                "title": "Album",
                "date": "2001-11-05",
                "country": "US",
                "artist-credit": [
                    {"artist": {"name": "Foo"}},
                    {"joinphrase": " & ", "artist": {"name": "Bar"}},
                    " Baz",
                ],
            }
        )
        assert label == "FooBar Baz – Album  (2001)  [US]"

    def test_missing_keys_render_placeholders(self) -> None:
        panel = _full_panel()
        assert panel._release_label({}) == " – ?  ()  []"


class TestApplySelectedRelease:
    def test_no_disc_info_is_a_no_op(self) -> None:
        panel = _full_panel()
        with patch("cd_ripper.ui.drive_config_panel.apply_release") as apply_rel:
            panel._apply_selected_release()
        apply_rel.assert_not_called()
        panel._release_combo.current.assert_not_called()

    def test_selected_release_is_applied_and_broadcast(self) -> None:
        panel = _full_panel()
        info = DiscInfo()
        info.tracks = [{"number": 1, "title": "Old"}]
        info.mb_releases = [{"title": "Release"}]
        panel._disc_info = info
        panel._release_combo.current.return_value = 0
        cb = MagicMock()
        panel._on_release_applied_cb = cb

        with patch("cd_ripper.ui.drive_config_panel.apply_release") as apply_rel:
            panel._apply_selected_release()

        apply_rel.assert_called_once_with(info, info.mb_releases[0])
        assert panel.state["tracks"] is info.tracks
        cb.assert_called_once()

    def test_out_of_range_index_applies_nothing(self) -> None:
        panel = _full_panel()
        info = DiscInfo()
        info.mb_releases = [{"title": "Release"}]
        panel._disc_info = info
        panel._release_combo.current.return_value = 7
        cb = MagicMock()
        panel._on_release_applied_cb = cb

        with patch("cd_ripper.ui.drive_config_panel.apply_release") as apply_rel:
            panel._apply_selected_release()

        apply_rel.assert_not_called()
        cb.assert_not_called()

    def test_missing_release_callback_is_skipped(self) -> None:
        panel = _full_panel()
        info = DiscInfo()
        info.mb_releases = [{"title": "Release"}]
        panel._disc_info = info
        panel._release_combo.current.return_value = 0
        panel._on_release_applied_cb = None

        with patch("cd_ripper.ui.drive_config_panel.apply_release"):
            panel._apply_selected_release()

        assert panel.state["tracks"] is info.tracks
