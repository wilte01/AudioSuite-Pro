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

Changed in 1.4.1: adds ``TestCompletionSeam``, which drives the real
``run_enhancement`` into the handler ``app.py`` binds and asserts the
written report.
"""

from __future__ import annotations

import threading
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_enhancer.app import AudioEnhancerApp
from audio_enhancer.core.models import (
    PRESETS,
    AudioFileInfo,
    EnhancementParams,
    JobStatus,
    PresetName,
    ProcessingResult,
)
from audio_enhancer.utils.cli_args import CliArgs


def _make_app(tmp_path: Path) -> AudioEnhancerApp:
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


# ── _on_complete log-formatting tests ─────────────────────────────────────


class TestOnCompleteLogFormatting:
    """_on_complete() constructs correct log lines and updates UI."""

    @staticmethod
    @pytest.fixture
    def app(tmp_path: Path) -> AudioEnhancerApp:
        """Create an AudioEnhancerApp with mocked Tk root for test isolation."""
        return _make_app(tmp_path)

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
            with patch("audio_enhancer.app.messagebox.showwarning") as mock_warn:
                app.start_processing()
        mock_warn.assert_called_once()
        mock_start.assert_not_called()


# ── Preset CRUD tests ────────────────────────────────────────────────────


class TestPresetCRUD:
    """Preset collect/apply/select/save/delete operations."""

    @staticmethod
    @pytest.fixture
    def app() -> AudioEnhancerApp:
        root = MagicMock()
        scheduled: list = []
        root.after.side_effect = lambda delay, fn, *a: scheduled.append(fn)

        app = object.__new__(AudioEnhancerApp)
        app.root = root
        app.source_path = MagicMock()
        app.source_path.get.return_value = "/music/src"
        app.output_path = MagicMock()
        app.output_path.get.return_value = "/music/out"
        app.preset_name = MagicMock()
        app.preset_name.get.return_value = "Moderate"
        app._param_values = {
            "noise_gate_threshold_db": -65.0,
            "compressor_threshold_db": -22.0,
            "compressor_ratio": 3.5,
            "compressor_attack_ms": 8.0,
            "compressor_release_ms": 120.0,
            "low_shelf_gain_db": 2.5,
            "low_shelf_freq_hz": 100.0,
            "presence_gain_db": 2.5,
            "presence_freq_hz": 3500.0,
            "high_shelf_gain_db": 4.0,
            "high_shelf_freq_hz": 7000.0,
            "output_gain_db": 4.0,
            "limiter_threshold_db": -0.5,
        }
        app.params = EnhancementParams()
        app._refresh_preset_list = MagicMock()
        app._preset_combo = MagicMock()
        app._dsp_panel = MagicMock()
        app._scheduled = scheduled
        return app

    # ── _collect_settings ──────────────────────────────────────────────────

    def test_collect_settings_returns_source_output_preset(
        self, app: AudioEnhancerApp
    ) -> None:
        settings = app._collect_settings()
        assert settings["source_path"] == "/music/src"
        assert settings["output_path"] == "/music/out"
        assert settings["preset_name"] == "Moderate"

    def test_collect_settings_includes_param_values(
        self, app: AudioEnhancerApp
    ) -> None:
        settings = app._collect_settings()
        assert settings["compressor_ratio"] == 3.5
        assert settings["output_gain_db"] == 4.0
        assert settings["limiter_threshold_db"] == -0.5

    # ── _apply_preset ─────────────────────────────────────────────────────

    def test_apply_preset_sets_source_output_preset(
        self, app: AudioEnhancerApp
    ) -> None:
        app._apply_preset(
            {
                "source_path": "/new/src",
                "output_path": "/new/out",
                "preset_name": "Mild",
            }
        )
        app.source_path.set.assert_any_call("/new/src")
        app.output_path.set.assert_any_call("/new/out")
        app.preset_name.set.assert_any_call("Mild")

    def test_apply_preset_overrides_params(self, app: AudioEnhancerApp) -> None:
        app._apply_preset({"compressor_ratio": 5.0, "output_gain_db": 6.0})
        assert app.params.compressor_ratio == 5.0
        assert app.params.output_gain_db == 6.0
        # Unchanged fields remain at default
        assert app.params.noise_gate_threshold_db == -65.0

    def test_apply_preset_updates_param_values(self, app: AudioEnhancerApp) -> None:
        # Changed in 1.1.0: regression for the saved-preset defect — the worker
        # reads _param_values, so it must be updated, not just self.params.
        app._apply_preset({"compressor_ratio": 5.0, "output_gain_db": 6.0})
        assert app._param_values["compressor_ratio"] == 5.0
        assert app._param_values["output_gain_db"] == 6.0
        # Untouched keys are preserved
        assert app._param_values["limiter_threshold_db"] == -0.5

    def test_apply_preset_carries_effect_fields_to_param_values(
        self, app: AudioEnhancerApp
    ) -> None:
        app._apply_preset({"reverse": True, "karaoke_strength": 0.4})
        assert app._param_values["reverse"] is True
        assert app._param_values["karaoke_strength"] == 0.4

    def test_apply_preset_syncs_the_custom_dsp_window(
        self, app: AudioEnhancerApp
    ) -> None:
        """A saved preset must move the visible controls, not just the values."""
        app._apply_preset({"compressor_ratio": 5.0})
        app._dsp_panel.apply_values.assert_called_once_with({"compressor_ratio": 5.0})

    def test_apply_preset_no_overrides_keeps_original_params(
        self, app: AudioEnhancerApp
    ) -> None:
        original = app.params
        app._apply_preset({"source_path": "/only/src"})
        # params object should be the same (no replace called)
        assert app.params is original

    def test_apply_preset_ignores_unknown_keys(self, app: AudioEnhancerApp) -> None:
        original = app.params
        app._apply_preset({"unknown_key": 999})
        # No dataclass field matches, so no replace
        assert app.params is original

    # ── _on_preset_selected ───────────────────────────────────────────────

    def test_on_preset_selected_applies_when_settings_found(
        self, app: AudioEnhancerApp
    ) -> None:
        with patch("audio_suite_shared.suite_config.load_preset") as mock_load:
            mock_load.return_value = {
                "compressor_ratio": 2.5,
                "output_gain_db": 2.0,
            }
            app._on_preset_selected("Mild")
        mock_load.assert_called_once_with("audio_enhancer", "Mild")
        assert app.params.compressor_ratio == 2.5
        assert app.params.output_gain_db == 2.0

    def test_on_preset_selected_does_nothing_when_empty(
        self, app: AudioEnhancerApp
    ) -> None:
        original = app.params
        with patch("audio_suite_shared.suite_config.load_preset") as mock_load:
            mock_load.return_value = {}
            app._on_preset_selected("Unknown")
        assert app.params is original

    def test_on_preset_selected_does_nothing_when_none(
        self, app: AudioEnhancerApp
    ) -> None:
        original = app.params
        with patch("audio_suite_shared.suite_config.load_preset") as mock_load:
            mock_load.return_value = None
            app._on_preset_selected("Nonexistent")
        assert app.params is original

    # ── _save_current_as_preset ───────────────────────────────────────────

    def test_save_current_as_preset_calls_suite_config(
        self, app: AudioEnhancerApp
    ) -> None:
        with patch("audio_suite_shared.suite_config.save_preset") as mock_save:
            with patch(
                "audio_suite_shared.suite_config.list_presets",
                return_value=["Custom"],
            ):
                app._save_current_as_preset("Custom")
        mock_save.assert_called_once()
        call_args = mock_save.call_args
        assert call_args[0][0] == "audio_enhancer"
        assert call_args[0][1] == "Custom"
        assert isinstance(call_args[0][2], dict)

    def test_save_current_as_preset_refreshes_list(self, app: AudioEnhancerApp) -> None:
        with patch("audio_suite_shared.suite_config.save_preset"):
            with patch(
                "audio_suite_shared.suite_config.list_presets",
                return_value=["Custom", "Mild"],
            ):
                app._save_current_as_preset("Custom")
        app._refresh_preset_list.assert_called_once_with(["Custom", "Mild"])

    def test_save_current_as_preset_skips_refresh_when_no_callback(
        self, app: AudioEnhancerApp
    ) -> None:
        app._refresh_preset_list = None
        with patch("audio_suite_shared.suite_config.save_preset"):
            with patch(
                "audio_suite_shared.suite_config.list_presets",
                return_value=["Custom"],
            ):
                # Should not raise
                app._save_current_as_preset("Custom")

    # ── _delete_preset ────────────────────────────────────────────────────

    def test_delete_preset_calls_suite_config(self, app: AudioEnhancerApp) -> None:
        with patch("audio_suite_shared.suite_config.delete_preset") as mock_del:
            with patch(
                "audio_suite_shared.suite_config.list_presets",
                return_value=[],
            ):
                app._delete_preset("Old")
        mock_del.assert_called_once_with("audio_enhancer", "Old")

    def test_delete_preset_refreshes_list(self, app: AudioEnhancerApp) -> None:
        with patch("audio_suite_shared.suite_config.delete_preset"):
            with patch(
                "audio_suite_shared.suite_config.list_presets",
                return_value=["Mild"],
            ):
                app._delete_preset("Old")
        app._refresh_preset_list.assert_called_once_with(["Mild"])

    def test_delete_preset_skips_refresh_when_no_callback(
        self, app: AudioEnhancerApp
    ) -> None:
        app._refresh_preset_list = None
        with patch("audio_suite_shared.suite_config.delete_preset"):
            with patch(
                "audio_suite_shared.suite_config.list_presets",
                return_value=[],
            ):
                app._delete_preset("Old")


# ── CLI args tests ───────────────────────────────────────────────────────


class TestApplyCliArgs:
    """_apply_cli_args parses CLI and applies settings."""

    @staticmethod
    @pytest.fixture
    def app() -> AudioEnhancerApp:
        root = MagicMock()
        scheduled: list = []
        root.after.side_effect = lambda delay, fn, *a: scheduled.append(fn)

        app = object.__new__(AudioEnhancerApp)
        app.root = root
        app.source_path = MagicMock()
        app.output_path = MagicMock()
        app.preset_name = MagicMock()
        app.run_mode = MagicMock()
        app.auto_start_var = MagicMock()
        app.auto_end_var = MagicMock()
        app.clear_logs_var = MagicMock()
        app.parallel_var = MagicMock()
        app.auto_end = False
        app._driver_locked = False
        app.start_processing = MagicMock()
        app._dsp_panel = MagicMock()
        app._scheduled = scheduled
        return app

    def test_cli_args_sets_source(self, app: AudioEnhancerApp) -> None:
        args = CliArgs(source="/music/src")
        with patch("audio_enhancer.app.parse_cli", return_value=args):
            app._apply_cli_args()
        app.source_path.set.assert_called_with("/music/src")

    def test_cli_args_sets_preset(self, app: AudioEnhancerApp) -> None:
        args = CliArgs(preset="Aggressive")
        with patch("audio_enhancer.app.parse_cli", return_value=args):
            app._apply_cli_args()
        app.preset_name.set.assert_called_with("Aggressive")

    def test_cli_preset_applies_the_preset_values(self, app: AudioEnhancerApp) -> None:
        """A --preset flag must move the DSP values, not just the combobox."""
        args = CliArgs(preset="Aggressive")
        with patch("audio_enhancer.app.parse_cli", return_value=args):
            app._apply_cli_args()
        app._dsp_panel.apply_values.assert_called_once()
        applied = app._dsp_panel.apply_values.call_args.args[0]
        aggressive = PRESETS[PresetName.AGGRESSIVE]
        assert applied["compressor_ratio"] == aggressive.compressor_ratio
        assert applied["high_shelf_gain_db"] == aggressive.high_shelf_gain_db

    def test_cli_args_sets_run_mode_dry(self, app: AudioEnhancerApp) -> None:
        args = CliArgs(live_mode=False)
        with patch("audio_enhancer.app.parse_cli", return_value=args):
            app._apply_cli_args()
        app.run_mode.set.assert_called_with("Dry Run")

    def test_cli_args_sets_run_mode_live(self, app: AudioEnhancerApp) -> None:
        args = CliArgs(live_mode=True)
        with patch("audio_enhancer.app.parse_cli", return_value=args):
            app._apply_cli_args()
        app.run_mode.set.assert_called_with("Live Update")

    def test_cli_args_live_mode_none_does_not_set_run_mode(
        self, app: AudioEnhancerApp
    ) -> None:
        args = CliArgs(live_mode=None)
        with patch("audio_enhancer.app.parse_cli", return_value=args):
            app._apply_cli_args()
        app.run_mode.set.assert_not_called()

        with patch(
            "audio_enhancer.app.parse_cli", return_value=CliArgs(live_mode=False)
        ):
            app._apply_cli_args()
        app.run_mode.set.assert_called_with("Dry Run")

    def test_cli_args_sets_auto_end(self, app: AudioEnhancerApp) -> None:
        args = CliArgs(auto_end=True)
        with patch("audio_enhancer.app.parse_cli", return_value=args):
            app._apply_cli_args()
        assert app.auto_end is True
        app.auto_end_var.set.assert_called_with(True)

    def test_cli_args_sets_clear_logs_and_parallel(self, app: AudioEnhancerApp) -> None:
        args = CliArgs(clear_logs=True, parallel_run=True)
        with patch("audio_enhancer.app.parse_cli", return_value=args):
            app._apply_cli_args()
        app.clear_logs_var.set.assert_called_with(True)
        app.parallel_var.set.assert_called_with(True)

    def test_cli_args_auto_start_schedules_processing(
        self, app: AudioEnhancerApp
    ) -> None:
        args = CliArgs(source="/music/src", auto_start=True)
        with patch("audio_enhancer.app.parse_cli", return_value=args):
            app._apply_cli_args()
        # root.after(1500, start_processing) should have been called
        app.root.after.assert_called_with(1500, app.start_processing)

    def test_cli_args_no_auto_start_does_not_schedule(
        self, app: AudioEnhancerApp
    ) -> None:
        args = CliArgs(auto_start=False)
        with patch("audio_enhancer.app.parse_cli", return_value=args):
            app._apply_cli_args()
        # No root.after(1500, ...) call
        for call in app.root.after.call_args_list:
            if call[0] and call[0][0] == 1500:
                pytest.fail("Should not schedule auto-start")


# ── _on_progress tests ───────────────────────────────────────────────────


class TestOnProgress:
    """_on_progress schedules a UI update on the main thread."""

    @staticmethod
    @pytest.fixture
    def app() -> AudioEnhancerApp:
        root = MagicMock()
        scheduled: list = []
        root.after.side_effect = lambda delay, fn, *a: scheduled.append(fn)

        app = object.__new__(AudioEnhancerApp)
        app.root = root
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.file_listbox = MagicMock()
        app._scheduled = scheduled
        return app

    def _run_progress(
        self,
        app: AudioEnhancerApp,
        processed: int = 1,
        total: int = 5,
        done: int = 1,
        errors: int = 0,
        display_text: str = "[DONE] track.mp3",
    ) -> None:
        result = ProcessingResult()
        app._on_progress(processed, total, done, errors, result, display_text)
        if app._scheduled:
            app._scheduled[-1]()

    def test_progress_sets_maximum(self, app: AudioEnhancerApp) -> None:
        self._run_progress(app, total=10)
        calls = app.progress.__setitem__.call_args_list
        assert any(c == (("maximum", 10),) for c in calls)

    def test_progress_sets_value(self, app: AudioEnhancerApp) -> None:
        self._run_progress(app, processed=3)
        calls = app.progress.__setitem__.call_args_list
        assert any(c == (("value", 3),) for c in calls)

    def test_progress_updates_stats_label(self, app: AudioEnhancerApp) -> None:
        self._run_progress(app, processed=2, total=5, done=1, errors=1)
        app.stats_label.config.assert_called_with(
            text="Processed: 2/5  |  Enhanced: 1  |  Errors: 1"
        )

    def test_progress_inserts_into_listbox(self, app: AudioEnhancerApp) -> None:
        self._run_progress(app, display_text="[DONE] track.mp3 +6 dB")
        app.file_listbox.insert.assert_called_with("end", "[DONE] track.mp3 +6 dB")

    def test_progress_scrolls_listbox_to_end(self, app: AudioEnhancerApp) -> None:
        self._run_progress(app)
        app.file_listbox.see.assert_called_with("end")


# ── _on_error tests ──────────────────────────────────────────────────────


class TestOnError:
    """_on_error schedules a messagebox and re-enables the start button."""

    @staticmethod
    @pytest.fixture
    def app() -> AudioEnhancerApp:
        root = MagicMock()
        scheduled: list = []
        root.after.side_effect = lambda delay, fn, *a: scheduled.append(fn)

        app = object.__new__(AudioEnhancerApp)
        app.root = root
        app.start_btn = MagicMock()
        app._scheduled = scheduled
        return app

    def test_on_error_shows_messagebox(self, app: AudioEnhancerApp) -> None:
        with patch("audio_enhancer.app.messagebox.showerror") as mock_err:
            app._on_error("Something went wrong")
            app._scheduled[-1]()
        mock_err.assert_called_once_with("Error", "Something went wrong")

    def test_on_error_re_enables_start_button(self, app: AudioEnhancerApp) -> None:
        with patch("audio_enhancer.app.messagebox.showerror"):
            app._on_error("fail")
            app._scheduled[-1]()
        app.start_btn.config.assert_called_with(state="normal")


# ── Dry-run audition tests ───────────────────────────────────────────────


class TestDryRunAudition:
    """When _run_was_dry_run is True, the audition caption is set accordingly."""

    @staticmethod
    @pytest.fixture
    def app(tmp_path: Path) -> AudioEnhancerApp:
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
        app._run_was_dry_run = True
        app.auto_end_var = MagicMock()
        app.auto_end_var.get.return_value = False
        app._scheduled = scheduled
        return app

    def test_dry_run_sets_dry_run_caption(self, app: AudioEnhancerApp) -> None:
        results = [
            ProcessingResult(
                source=Path("track.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-14.0,
                tags_copied=5,
            )
        ]
        app._on_complete(total=1, done=1, errors=0, duration_secs=1.0, results=results)
        # Invoke the scheduled update
        app._scheduled[-1]()
        caption = _audition_caption(app.root)
        assert caption == "Dry Run — nothing written. Play Result is unavailable."

    def test_dry_run_completion_label_says_dry_run(self, app: AudioEnhancerApp) -> None:
        results = [
            ProcessingResult(
                source=Path("track.mp3"),
                status=JobStatus.DONE,
                rms_before_db=-20.0,
                rms_after_db=-14.0,
                tags_copied=1,
            )
        ]
        app._on_complete(total=1, done=1, errors=0, duration_secs=1.0, results=results)
        app._scheduled[-1]()
        app.completion_label.config.assert_called_with(
            text="Enhancement Dry Run Complete!"
        )


# ── Completion seam: the processor payload must reach this handler ────────


class TestCompletionSeam:
    """``run_enhancement`` publishes into the handler app.py actually binds."""

    @staticmethod
    @pytest.fixture
    def app(tmp_path: Path) -> AudioEnhancerApp:
        return _make_app(tmp_path)

    def test_the_real_payload_is_accepted_and_the_report_is_written(
        self, app: AudioEnhancerApp, tmp_path: Path
    ) -> None:
        """Regression: the processor also sends ``processed=`` and ``skipped=``.

        Without the catch-all, binding ``on_complete=self._on_complete`` raised
        ``TypeError: got an unexpected keyword argument 'processed'`` after the
        DSP work had already finished, so the run ended with no report.
        """
        from audio_enhancer.core import file_processor as core

        result = ProcessingResult(
            source=Path("track.mp3"),
            status=JobStatus.DONE,
            rms_before_db=-20.0,
            rms_after_db=-14.0,
            tags_copied=5,
        )
        with (
            patch.object(core, "find_audio_files", return_value=[Path("track.mp3")]),
            patch.object(
                core,
                "inspect",
                side_effect=lambda p: AudioFileInfo(path=p),
            ),
            patch.object(core, "process_file", return_value=result),
        ):
            core.run_enhancement(
                source_path=Path("/fake/source"),
                output_dir=Path("/fake/output"),
                params=EnhancementParams(),
                slot_vars=[MagicMock()],
                slot_queue=Queue(),
                on_progress=MagicMock(),
                on_complete=app._on_complete,
                on_error=MagicMock(),
            )

        # The handler only schedules the log write; flush it like the Tk loop.
        for scheduled in list(app._scheduled):
            scheduled()

        report = (tmp_path / "enhancement_log.txt").read_text(encoding="utf-8")
        assert "SUMMARY" in report
        assert "Total files : 1" in report
        assert "Enhanced    : 1" in report
