"""
tests/test_app.py
Tests for app.py — AudioEnhancerApp orchestration logic.

Run with:
    pytest tests/test_app.py -v

Coverage
--------
_on_complete log formatting
  * DONE result -> correct [DONE] line with gain and tags
  * SKIPPED result -> pre-built display_text used as-is
  * FAILED result -> pre-built display_text used as-is
  * Summary block with total/done/errors/duration
  * Mixed results produce correct log content
  * OSError during log write -> messagebox.showerror called
  * UI labels updated on completion
  * auto_end flag schedules root.destroy

start_processing output resolution
  * Empty output + source is a directory -> output = source
  * Empty output + source is a file -> output = source.parent
  * Custom output path -> output = that path
  * Empty source -> shows warning, returns early
  * Missing source path -> shows warning, returns early
  * No thread spawned for invalid source
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_enhancer.app import AudioEnhancerApp
from audio_enhancer.core.models import JobStatus, ProcessingResult

# ── _on_complete log-formatting tests ─────────────────────────────────────


class TestOnCompleteLogFormatting:
    """_on_complete() constructs correct log lines and updates UI."""

    @staticmethod
    @pytest.fixture
    def app(tmp_path: Path) -> AudioEnhancerApp:
        """Create an AudioEnhancerApp with mocked Tk root for test isolation."""
        root = MagicMock()
        scheduled: list = []
        root.after.side_effect = lambda delay, fn, *a: scheduled.append(fn)

        app = object.__new__(AudioEnhancerApp)
        app.root = root
        app._log_path = str(tmp_path / "enhancement_log.txt")
        app._in_place = False
        app._audition_original = None
        app._audition_result = None
        app.time_label = MagicMock()
        app.summary_label = MagicMock()
        app.completion_label = MagicMock()
        app.notebook = MagicMock()
        app._tab_results = MagicMock()
        app.start_btn = MagicMock()
        app._run_was_dry_run = False
        app.auto_end_var = MagicMock()
        app.auto_end_var.get.return_value = False
        app._scheduled = scheduled  # stash so _run_completion can invoke it
        return app

    def _run(self, app: AudioEnhancerApp, **kwargs) -> None:
        """Call _on_complete and invoke the scheduled UI update."""
        defaults = dict(total=0, done=0, errors=0, duration_secs=0.0, results=[])
        defaults.update(kwargs)
        app._on_complete(**defaults)
        if app._scheduled:
            app._scheduled[0]()

    # ── DONE path ─────────────────────────────────────────────────────────

    def test_done_result_log_line(self, app: AudioEnhancerApp) -> None:
        results = [
            ProcessingResult(
                source=Path("track.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-14.0,
                tags_copied=5,
            )
        ]
        self._run(app, total=1, done=1, results=results)
        log = Path(app._log_path).read_text(encoding="utf-8")
        assert "[DONE]  track.mp3  +6.0 dB  tags:5" in log

    def test_done_result_zero_gain(self, app: AudioEnhancerApp) -> None:
        results = [
            ProcessingResult(
                source=Path("flat.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-18.0,
                rms_after_db=-18.0,
                tags_copied=0,
            )
        ]
        self._run(app, total=1, done=1, results=results)
        log = Path(app._log_path).read_text(encoding="utf-8")
        assert "[DONE]  flat.mp3  +0.0 dB  tags:0" in log

    # ── SKIPPED path ──────────────────────────────────────────────────────

    def test_skipped_result_uses_display_text(self, app: AudioEnhancerApp) -> None:
        results = [
            ProcessingResult(
                status=JobStatus.SKIPPED,
                display_text="[SKIP] gone.mp3: file not found",
            )
        ]
        self._run(app, results=results)
        log = Path(app._log_path).read_text(encoding="utf-8")
        assert "[SKIP] gone.mp3: file not found" in log

    def test_skipped_negative_gain_fields_not_used(self, app: AudioEnhancerApp) -> None:
        """Even if source/error_message are zero-valued on a SKIPPED result,
        the display_text must be used verbatim instead."""
        results = [
            ProcessingResult(
                status=JobStatus.SKIPPED,
                display_text="[SKIP] vanished.flac: file not found",
            )
        ]
        self._run(app, results=results)
        log = Path(app._log_path).read_text(encoding="utf-8")
        # Must NOT include the placeholder "[DONE]  .  +0.0 dB" string
        assert "vanished.flac" in log
        assert "[DONE]" not in log

    # ── FAILED path ───────────────────────────────────────────────────────

    def test_failed_result_uses_display_text(self, app: AudioEnhancerApp) -> None:
        results = [
            ProcessingResult(
                status=JobStatus.FAILED,
                display_text="[ERROR] locked.mp3: permission denied",
            )
        ]
        self._run(app, total=1, errors=1, results=results)
        log = Path(app._log_path).read_text(encoding="utf-8")
        assert "[ERROR] locked.mp3: permission denied" in log

    # ── Summary block ─────────────────────────────────────────────────────

    def test_summary_block_format(self, app: AudioEnhancerApp) -> None:
        results = [
            ProcessingResult(
                source=Path("ok.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-15.0,
                tags_copied=3,
            )
        ]
        self._run(app, total=1, done=1, errors=0, duration_secs=65.0, results=results)
        log = Path(app._log_path).read_text(encoding="utf-8")
        assert "Total files : 1" in log
        assert "Enhanced    : 1" in log
        assert "Errors      : 0" in log
        assert "Duration    : 01:05" in log

    def test_mixed_results_in_log(self, app: AudioEnhancerApp) -> None:
        results = [
            ProcessingResult(
                source=Path("a.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-14.0,
                tags_copied=2,
            ),
            ProcessingResult(
                status=JobStatus.SKIPPED,
                display_text="[SKIP] b.mp3: file not found",
            ),
            ProcessingResult(
                status=JobStatus.FAILED,
                display_text="[ERROR] c.mp3: permission denied",
            ),
        ]
        self._run(app, total=3, done=1, errors=1, duration_secs=10.0, results=results)
        log = Path(app._log_path).read_text(encoding="utf-8")
        assert "[DONE]  a.mp3  +6.0 dB  tags:2" in log
        assert "[SKIP] b.mp3: file not found" in log
        assert "[ERROR] c.mp3: permission denied" in log
        assert "Total files : 3" in log
        assert "Enhanced    : 1" in log
        assert "Errors      : 1" in log

    # ── Error handling ────────────────────────────────────────────────────

    def test_log_write_oserror_caught(self, app: AudioEnhancerApp) -> None:
        """OSError during log write must call messagebox.showerror, not crash."""
        results = [
            ProcessingResult(
                source=Path("ok.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-15.0,
                tags_copied=1,
            )
        ]
        with patch("builtins.open", side_effect=OSError(13, "Permission denied")):
            with patch("audio_enhancer.app.messagebox.showerror") as mock_showerror:
                self._run(app, total=1, done=1, results=results)
                mock_showerror.assert_called_once()

    # ── UI update assertions ──────────────────────────────────────────────

    def test_completion_updates_ui_labels(self, app: AudioEnhancerApp) -> None:
        """_on_complete must update time, summary, and completion labels."""
        results = [
            ProcessingResult(
                source=Path("ok.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-15.0,
                tags_copied=1,
            )
        ]
        self._run(app, total=1, done=1, errors=0, duration_secs=90.0, results=results)
        app.time_label.config.assert_called()
        app.summary_label.config.assert_called()
        app.completion_label.config.assert_called_once_with(
            text="Enhancement Complete!"
        )
        app.start_btn.config.assert_called_once_with(state="normal")

    def test_auto_end_schedules_root_destroy(self, app: AudioEnhancerApp) -> None:
        """When auto_end_var is True, root.after must be called for root.destroy."""
        app.auto_end_var.get.return_value = True
        results = [
            ProcessingResult(
                source=Path("ok.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-15.0,
                tags_copied=1,
            )
        ]
        # Clear the scheduled list from the initial _on_complete call
        self._run(app, total=1, done=1, results=results)
        # Check if any root.after call scheduled root.destroy
        destroy_calls = [
            call
            for call in app.root.after.call_args_list
            if len(call[0]) >= 2 and call[0][1] == app.root.destroy
        ]
        assert len(destroy_calls) == 1

    # ── Audition state ────────────────────────────────────────────────────

    def test_audition_non_in_place_ready_caption(self, app: AudioEnhancerApp) -> None:
        """Non in-place completion advertises the first enhanced file."""
        app._in_place = False
        results = [
            ProcessingResult(
                source=Path("ok.mp3"),
                output=Path("enhanced/ok.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-15.0,
                tags_copied=1,
            )
        ]
        self._run(app, total=1, done=1, results=results)
        assert app._audition_result is not None
        caption = _audition_caption(app.root)
        assert caption == "Audition ready — ok.mp3 (original vs enhanced)"

    def test_audition_in_place_ready_caption(self, app: AudioEnhancerApp) -> None:
        """In-place completion keeps the captured original/result pair."""
        app._in_place = True
        app._audition_original = Path("snap_track_orig.mp3")
        app._audition_result = Path("track.mp3")
        results = [
            ProcessingResult(
                source=Path("track.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-15.0,
                tags_copied=1,
            )
        ]
        self._run(app, total=1, done=1, results=results)
        assert app._audition_original == Path("snap_track_orig.mp3")
        caption = _audition_caption(app.root)
        assert caption == "Audition ready — track.mp3 (original vs enhanced)"

    def test_audition_in_place_no_source_message(self, app: AudioEnhancerApp) -> None:
        """In-place run with no captured pair falls back to a message."""
        app._in_place = True
        results = [
            ProcessingResult(
                source=Path("track.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-15.0,
                tags_copied=1,
            )
        ]
        self._run(app, total=1, done=1, results=results)
        assert (
            _audition_caption(app.root) == "No supported audio file found for audition."
        )


def _audition_caption(root: Any) -> str:
    """Latest caption scheduled by the audition state machine."""
    for call in root.after.call_args_list:
        args = call[0]
        if len(args) == 3 and args[0] == 0 and isinstance(args[2], str):
            return args[2]
    return ""


# ── start_processing output-resolution tests ─────────────────────────────


class TestStartProcessingOutputResolution:
    """start_processing() resolves the output directory correctly."""

    @staticmethod
    @pytest.fixture
    def app() -> AudioEnhancerApp:
        app = object.__new__(AudioEnhancerApp)
        app.root = MagicMock()
        app.source_path = MagicMock()
        app.output_path = MagicMock()
        app._out_dir = ""
        app._log_path = ""
        app.start_btn = MagicMock()
        app.file_listbox = MagicMock()
        app.progress = MagicMock()
        app.notebook = MagicMock()
        app._tab_processing = MagicMock()
        app.overall_status = MagicMock()
        app.params = MagicMock()
        app.run_mode = MagicMock()
        app.run_mode.get.return_value = "Dry Run"
        app.slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        return app

    def _run_start(self, app: AudioEnhancerApp) -> None:
        """Call start_processing with common patches."""
        with patch.object(threading.Thread, "start"):
            with patch("audio_enhancer.app.messagebox.showwarning"):
                with patch("audio_suite_shared.suite_config.save_last_directory"):
                    app.start_processing()

    # ── Output resolution ─────────────────────────────────────────────────

    def test_output_resolution_dir_source(
        self, app: AudioEnhancerApp, tmp_path: Path
    ) -> None:
        """When output_path is empty and source is a directory, output_dir == source."""
        src_dir = tmp_path / "music"
        src_dir.mkdir()
        app.source_path.get.return_value = str(src_dir)
        app.output_path.get.return_value = ""
        self._run_start(app)
        assert app._out_dir == str(src_dir)
        assert app._log_path == str(src_dir / "enhancement_log.txt")

    def test_output_resolution_file_source(
        self, app: AudioEnhancerApp, tmp_path: Path
    ) -> None:
        """When output_path is empty and source is a file,
        output_dir == source.parent."""
        src_file = tmp_path / "music" / "track.mp3"
        src_file.parent.mkdir(parents=True)
        src_file.touch()
        app.source_path.get.return_value = str(src_file)
        app.output_path.get.return_value = ""
        self._run_start(app)
        assert app._out_dir == str(src_file.parent)
        assert app._log_path == str(src_file.parent / "enhancement_log.txt")

    def test_output_resolution_custom(
        self, app: AudioEnhancerApp, tmp_path: Path
    ) -> None:
        """When output_path is set, output_dir == that path."""
        src_dir = tmp_path / "music"
        src_dir.mkdir()
        out_dir = tmp_path / "enhanced"
        app.source_path.get.return_value = str(src_dir)
        app.output_path.get.return_value = str(out_dir)
        self._run_start(app)
        assert app._out_dir == str(out_dir)
        assert app._log_path == str(out_dir / "enhancement_log.txt")

    # ── Path validation ───────────────────────────────────────────────────

    def test_empty_source_shows_warning(self, app: AudioEnhancerApp) -> None:
        """Empty source path must show a warning and return early."""
        app.source_path.get.return_value = ""
        with patch("audio_enhancer.app.messagebox.showwarning") as mock_warn:
            with patch.object(threading.Thread, "start") as mock_thread:
                app.start_processing()
        mock_warn.assert_called_once()
        mock_thread.assert_not_called()
        assert app._out_dir == ""  # never reached output resolution

    def test_missing_source_shows_warning(
        self, app: AudioEnhancerApp, tmp_path: Path
    ) -> None:
        """Non-existent source path must show a warning and return early."""
        app.source_path.get.return_value = str(tmp_path / "nonexistent")
        with patch("audio_enhancer.app.messagebox.showwarning") as mock_warn:
            with patch.object(threading.Thread, "start") as mock_thread:
                app.start_processing()
        mock_warn.assert_called_once()
        mock_thread.assert_not_called()
        assert app._out_dir == ""

    def test_thread_not_started_for_invalid_source(self, app: AudioEnhancerApp) -> None:
        """No worker thread should be spawned when source is invalid."""
        app.source_path.get.return_value = ""
        with patch.object(threading.Thread, "start") as mock_start:
            with patch("audio_enhancer.app.messagebox.showwarning"):
                app.start_processing()
        mock_start.assert_not_called()
