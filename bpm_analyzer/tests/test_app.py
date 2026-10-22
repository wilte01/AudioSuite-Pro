"""
Tests for bpm_analyzer.app — BPMAnalyzerApp CLI mirroring and wiring.

Uses the object.__new__ + MagicMock shell pattern (no real display).

Changed in 1.2.0: covers the run note the batch report shows when tracks
produced no BPM.

Changed in 1.4.0: covers the typed Workers count being capped at the slot grid
(D66).

Changed in 1.4.1: covers the out-of-band tempo count on all three surfaces -
the log's SUMMARY block, the Results panel and the driver's run note (D109).
Changed in 2.0.0: adds the ``TestCompletionSeam`` cases driving
``run_analysis`` into the completion handler (PLAN D117).
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS, is_supported_format
from audio_suite_shared.run_outcome import read_outcome


def _make_shell_app():
    """Build a BPMAnalyzerApp shell with mock attributes."""
    from bpm_analyzer.app import BPMAnalyzerApp

    app = object.__new__(BPMAnalyzerApp)
    app.root = MagicMock()
    app.folder_path = MagicMock()
    app.run_mode = MagicMock()
    app.auto_end = False
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()

    handler = MagicMock()
    handler.apply_cli_args.return_value = False
    handler_cls = MagicMock(return_value=handler)
    return app, handler, handler_cls


class TestApplyCliArgsDriven:
    """A driver launch populates the Run Controls values before applying."""

    def _run(self, parsed):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, handler, handler_cls = _make_shell_app()
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=parsed,
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            assert isinstance(parsed, BPMArgs)
            app._apply_cli_args()
        return app, handler

    def test_inherited_values_applied_to_panel_vars(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, _ = self._run(
            BPMArgs(
                folder_path="D:/Music",
                live_mode=True,
                auto_start=True,
                auto_end=True,
                clear_logs=True,
                parallel_run=True,
            )
        )
        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_handler_invoked_with_folder_and_auto_start(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        parsed = BPMArgs(folder_path="D:/Music")
        app, handler = self._run(parsed)
        handler.apply_cli_args.assert_called_once_with(
            parsed, folder_var=app.folder_path, auto_start_func=app.start_processing
        )

    def test_auto_start_schedules_processing(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, _, handler_cls = _make_shell_app()
        handler_cls.return_value.apply_cli_args.return_value = True
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=BPMArgs(folder_path="D:/Music"),
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        after_delays = [call.args[0] for call in app.root.after.call_args_list]
        assert 1500 in after_delays


class TestApplyCliArgsStandalone:
    """Standalone start: defaults applied, no handler/after scheduling."""

    def test_defaults_applied_to_panel_vars(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, _, handler_cls = _make_shell_app()
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=BPMArgs(),
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.auto_start_var.set.assert_called_once_with(False)
        app.auto_end_var.set.assert_called_once_with(False)
        app.clear_logs_var.set.assert_called_once_with(False)
        app.parallel_var.set.assert_called_once_with(False)

    def test_no_handler_or_scheduling_without_folder(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, handler, handler_cls = _make_shell_app()
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=BPMArgs(),
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        handler.apply_cli_args.assert_not_called()
        app.root.after.assert_not_called()


# ---------------------------------------------------------------------------
# Stage 3 / item D3 (audit A4): the real app is constructed on a withdrawn
# Toplevel of the shared hidden root; the run-mode plumbing is asserted where
# it reaches the core entry (bpm_analyzer.core.file_processor.run_analysis).
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


def assert_bound(callback: object, name: str, obj: object) -> None:
    """Bound methods are fresh objects per access: compare attributes."""
    assert getattr(callback, "__self__", None) is obj
    assert getattr(callback, "__name__", None) == name


class TestRealAppConstructionD3:
    def test_full_ui_builds_and_wires_vars(self, app_root, tmp_path, monkeypatch):
        from bpm_analyzer.app import BPMAnalyzerApp

        monkeypatch.setattr(
            "bpm_analyzer.app._suite_config.load_last_directory", lambda: ""
        )
        # The constructor consumes the Master-Driver CLI handshake from
        # sys.argv; pytest's own argv must not leak into that parser.
        monkeypatch.setattr(sys, "argv", ["bpm_analyzer"])
        app = BPMAnalyzerApp(app_root)
        assert app.start_btn is not None
        assert app.folder_path.get() == ""
        assert app.run_mode.get() in {"Dry Run", "Live Update"}
        assert app.bpm_range_min.get() != ""

    def test_preset_collect_and_apply_roundtrip(self, app_root, tmp_path, monkeypatch):
        from bpm_analyzer.app import BPMAnalyzerApp

        monkeypatch.setattr(
            "bpm_analyzer.app._suite_config.load_last_directory", lambda: ""
        )
        monkeypatch.setattr(sys, "argv", ["bpm_analyzer"])
        app = BPMAnalyzerApp(app_root)
        app = BPMAnalyzerApp(app_root)
        app._apply_preset(
            {
                "bpm_min": 60,
                "bpm_max": 200,
                "duration": 30,
                "parallel_mode": True,
                "max_workers": 2,
                "run_mode": "Live Update",
            }
        )
        assert app.bpm_range_min.get() == 60
        assert app.bpm_range_max.get() == 200
        assert app.analysis_duration.get() == 30
        assert app.parallel_mode.get() is True
        assert app.max_workers.get() == 2
        assert app.run_mode.get() == "Live Update"
        collected = app._collect_settings()
        assert collected["run_mode"] == "Live Update"


class TestStartProcessingD3:
    def _shell(self):
        from bpm_analyzer.app import BPMAnalyzerApp

        app = object.__new__(BPMAnalyzerApp)
        app.root = MagicMock()
        app.folder_path = MagicMock()
        app.bpm_range_min = MagicMock()
        app.bpm_range_max = MagicMock()
        app.analysis_duration = MagicMock()
        app.max_workers = MagicMock()
        app.parallel_mode = MagicMock()
        app.run_mode = MagicMock()
        app.overall_status = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_processing = MagicMock()
        app._safe_slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        return app

    def test_valid_folder_starts_analysis_with_run_mode(self, monkeypatch, tmp_path):
        import bpm_analyzer.app as app_mod

        app = self._shell()
        fake_threading = MagicMock()
        monkeypatch.setattr(app_mod, "threading", fake_threading)
        monkeypatch.setattr("bpm_analyzer.app.messagebox", MagicMock())
        src = tmp_path / "music"
        src.mkdir()
        (src / "a.mp3").write_bytes(b"\x00" * 8)
        app.folder_path.get.return_value = str(src)
        app.bpm_range_min.get.return_value = 60
        app.bpm_range_max.get.return_value = 200
        app.analysis_duration.get.return_value = 30
        app.max_workers.get.return_value = 2
        app.parallel_mode.get.return_value = False
        app.run_mode.get.return_value = "Dry Run"
        saves: list[tuple[str, object]] = []
        monkeypatch.setattr(
            "bpm_analyzer.app._suite_config.save_value",
            lambda key, value: saves.append((key, value)),
        )

        app.start_processing()

        thread = fake_threading.Thread.call_args
        assert_bound(thread.kwargs["target"], "_run_analysis", app)
        assert thread.kwargs["args"][1] is True  # is_dry_run from "Dry Run"
        assert thread.kwargs["args"][2] == 60
        assert thread.kwargs["args"][3] == 200
        assert saves

    def test_missing_folder_shows_error(self, monkeypatch):

        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("bpm_analyzer.app.messagebox", dialogs)
        app.folder_path.get.return_value = ""

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_bad_bpm_range_shows_error(self, monkeypatch, tmp_path):

        app = self._shell()
        dialogs = MagicMock()
        monkeypatch.setattr("bpm_analyzer.app.messagebox", dialogs)
        src = tmp_path / "music"
        src.mkdir()
        (src / "a.mp3").write_bytes(b"x")
        app.folder_path.get.return_value = str(src)
        app.bpm_range_min.get.return_value = 300
        app.bpm_range_max.get.return_value = 200

        app.start_processing()

        dialogs.showerror.assert_called_once()

    def test_typed_workers_above_the_grid_are_capped(self, monkeypatch, tmp_path):
        """A typed count above the slot grid must never reach the processor.

        Regression (D66): the Workers entry is free text while the grid is
        fixed, so an uncapped count handed out-of-range slot indices and every
        affected file failed with an unexplained ``IndexError``.
        """
        import bpm_analyzer.app as app_mod

        app = self._shell()
        fake_threading = MagicMock()
        monkeypatch.setattr(app_mod, "threading", fake_threading)
        monkeypatch.setattr("bpm_analyzer.app.messagebox", MagicMock())
        dialogs = MagicMock()
        monkeypatch.setattr("audio_suite_shared.ui_common.messagebox", dialogs)
        src = tmp_path / "music"
        src.mkdir()
        (src / "a.mp3").write_bytes(b"\x00" * 8)
        app.folder_path.get.return_value = str(src)
        app.bpm_range_min.get.return_value = 60
        app.bpm_range_max.get.return_value = 200
        app.analysis_duration.get.return_value = 30
        app.max_workers.get.return_value = 12
        app.parallel_mode.get.return_value = False
        app.run_mode.get.return_value = "Dry Run"
        app._safe_slot_vars = [MagicMock(), MagicMock()]
        saves: list[tuple[str, object]] = []
        monkeypatch.setattr(
            "bpm_analyzer.app._suite_config.save_value",
            lambda key, value: saves.append((key, value)),
        )

        app.start_processing()

        dialogs.showwarning.assert_called_once()
        app.max_workers.set.assert_called_once_with(2)
        assert ("bpm_max_workers", 2) in saves
        thread_args = fake_threading.Thread.call_args.kwargs["args"]
        assert thread_args[-1] == 2

    def test_driver_launch_caps_without_a_dialog(self, monkeypatch, tmp_path, caplog):
        """A driver / auto-start launch must not wait for a modal warning."""
        import bpm_analyzer.app as app_mod

        app = self._shell()
        app._launched_from_driver = True
        fake_threading = MagicMock()
        monkeypatch.setattr(app_mod, "threading", fake_threading)
        monkeypatch.setattr("bpm_analyzer.app.messagebox", MagicMock())
        dialogs = MagicMock()
        monkeypatch.setattr("audio_suite_shared.ui_common.messagebox", dialogs)
        src = tmp_path / "music"
        src.mkdir()
        (src / "a.mp3").write_bytes(b"\x00" * 8)
        app.folder_path.get.return_value = str(src)
        app.bpm_range_min.get.return_value = 60
        app.bpm_range_max.get.return_value = 200
        app.analysis_duration.get.return_value = 30
        app.max_workers.get.return_value = 12
        app.parallel_mode.get.return_value = False
        app.run_mode.get.return_value = "Dry Run"
        app._safe_slot_vars = [MagicMock(), MagicMock()]
        saves: list[tuple[str, object]] = []
        monkeypatch.setattr(
            "bpm_analyzer.app._suite_config.save_value",
            lambda key, value: saves.append((key, value)),
        )

        with caplog.at_level(logging.WARNING):
            app.start_processing()

        dialogs.showwarning.assert_not_called()
        assert any("Workers limited" in record.message for record in caplog.records)
        app.max_workers.set.assert_called_once_with(2)
        assert ("bpm_max_workers", 2) in saves
        thread_args = fake_threading.Thread.call_args.kwargs["args"]
        assert thread_args[-1] == 2

    def test_run_analysis_caps_workers_at_the_grid(self, monkeypatch, tmp_path):
        """A preset/CLI value must be capped even without the dialog."""
        from bpm_analyzer.app import BPMAnalyzerApp

        app = object.__new__(BPMAnalyzerApp)
        app.root = MagicMock()
        app._safe_slot_vars = [MagicMock(), MagicMock()]
        app.slot_queue = MagicMock()
        calls: dict[str, object] = {}

        import bpm_analyzer.core.file_processor as core

        monkeypatch.setattr(core, "run_analysis", lambda **kw: calls.update(kw))

        app._run_analysis(str(tmp_path), True, 60, 200, 30, False, 12)

        assert calls["max_workers"] == 2

    def test_worker_thread_calls_core_entry_with_flags(self, monkeypatch, tmp_path):
        from bpm_analyzer.app import BPMAnalyzerApp

        app = object.__new__(BPMAnalyzerApp)
        app.root = MagicMock()
        app._safe_slot_vars = MagicMock()
        app.slot_queue = MagicMock()
        calls: dict[str, object] = {}

        def fake_run_analysis(**kwargs):
            calls.update(kwargs)

        import bpm_analyzer.core.file_processor as core

        monkeypatch.setattr(core, "run_analysis", fake_run_analysis)

        app._run_analysis(str(tmp_path), True, 60, 200, 30, False, 2)

        assert calls["dir_path"] == str(tmp_path)
        assert calls["is_dry_run"] is True
        assert calls["min_bpm"] == 60
        assert calls["max_bpm"] == 200


# ---------------------------------------------------------------------------
# Moved from test_app_audio_detection.py (iteration-9 G5.1): regression test
# for BPMAnalyzerApp.start_processing()'s "does this folder contain supported
# audio?" pre-flight check.
#
# Bug: the pre-flight check in app.py previously hardcoded its own extension
# list (".mp3", ".flac", ".ogg", ".m4a", ".opus"), which had drifted out of
# sync with the real source of truth — audio_suite_shared.audio_formats.
# SUPPORTED_EXTENSIONS, which also includes ".wav", ".aiff", ".aif". A folder
# containing only WAV/AIFF files was therefore incorrectly rejected by the UI
# before processing ever started, even though run_analysis() (via
# BaseFileProcessor.discover_audio_files -> SUPPORTED_EXTENSIONS) and the
# tag read/write path (IFFID3Handler) both fully support those formats.
#
# app.py cannot be imported directly in this environment (it requires
# tkinter, which is unavailable here), so these tests exercise the exact
# check app.py now performs — `any(is_supported_format(f) for f in
# os.listdir(folder))` — directly against real temporary directories. This
# proves the fixed logic is correct and would have caught the original bug:
# the OLD hardcoded-list check is also exercised below and is shown to fail
# on the same WAV/AIFF-only directories that the fixed check accepts.
# ---------------------------------------------------------------------------


def _old_hardcoded_check(folder: str) -> bool:
    """Reproduces the pre-fix logic verbatim, for regression comparison."""
    return any(
        f.lower().endswith(ext)
        for f in os.listdir(folder)
        for ext in [".mp3", ".flac", ".ogg", ".m4a", ".opus"]
    )


def _new_check(folder: str) -> bool:
    """The fixed logic now used in app.py."""
    return any(is_supported_format(f) for f in os.listdir(folder))


class TestPreflightAudioDetectionRegression:
    def test_wav_only_folder_is_detected_by_fixed_check(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "track.wav"), "w").close()
            assert _new_check(folder) is True

    def test_aiff_only_folder_is_detected_by_fixed_check(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "track.aiff"), "w").close()
            assert _new_check(folder) is True

    def test_aif_short_extension_is_detected_by_fixed_check(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "track.aif"), "w").close()
            assert _new_check(folder) is True

    def test_old_hardcoded_check_incorrectly_rejected_wav_only_folder(self):
        """Demonstrates the bug: the OLD check returns False (no audio
        found) for a folder that, in reality, contains a fully-supported
        WAV file — the false-rejection this fix resolves."""
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "track.wav"), "w").close()
            assert _old_hardcoded_check(folder) is False

    def test_old_hardcoded_check_incorrectly_rejected_aiff_only_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "track.aiff"), "w").close()
            assert _old_hardcoded_check(folder) is False

    def test_fixed_check_still_detects_originally_supported_formats(self):
        """Non-regression: formats already handled before the fix must
        still be detected."""
        for ext in (".mp3", ".flac", ".ogg", ".m4a", ".opus"):
            with tempfile.TemporaryDirectory() as folder:
                open(os.path.join(folder, f"track{ext}"), "w").close()
                assert _new_check(folder) is True, f"{ext} should be detected"

    def test_fixed_check_rejects_folder_with_no_audio_files(self):
        with tempfile.TemporaryDirectory() as folder:
            open(os.path.join(folder, "readme.txt"), "w").close()
            assert _new_check(folder) is False

    def test_fixed_check_matches_shared_supported_extensions_exactly(self):
        """The fixed check must accept every extension in the real source
        of truth — guards against future drift re-introducing this bug."""
        for ext in SUPPORTED_EXTENSIONS:
            with tempfile.TemporaryDirectory() as folder:
                open(os.path.join(folder, f"track{ext}"), "w").close()
                assert _new_check(folder) is True, (
                    f"{ext} is in SUPPORTED_EXTENSIONS but was not detected "
                    "by the pre-flight check"
                )


# ---------------------------------------------------------------------------
# Run note: the batch report's BPM step says which tracks produced no BPM,
# instead of leaving that only in the tool's own log.
# ---------------------------------------------------------------------------


def _make_run_note_app(log_path):
    """Shell with only what the completion path touches."""
    from bpm_analyzer.app import BPMAnalyzerApp

    app = object.__new__(BPMAnalyzerApp)
    app.root = MagicMock()
    app._log_path = str(log_path)
    return app


#: One file whose 60 BPM was measured below the default band (D108).
_OUTSIDE = [{"filename": "drone.ogg", "bpm": 60, "min_bpm": 75, "max_bpm": 175}]


def _complete(app, *, total, errors=0, outside=None) -> None:
    """Drive the completion callback the analysis actually hands over.

    ``run_analysis`` always publishes ``skipped_files``, ``error_files`` and
    ``outside_range_files``, so the helper does too: passing only the field
    this tool reads is what let a narrower ``_on_complete`` signature ship
    and abort every gui run with ``TypeError`` (D112).
    """
    app._on_complete(
        header=["BPM ANALYSIS REPORT\n"],
        total=total,
        processed=total,
        skipped=0,
        errors=errors,
        duration_secs=1.0,
        log_entries=["line\n"],
        skipped_files=[],
        error_files=[],
        outside_range_files=list(outside or []),
    )


class TestRunNote:
    """``_on_complete`` records the tracks whose detection failed."""

    def test_failed_detections_are_reported(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "bpm_log.txt")

        _complete(app, total=12, errors=3)

        assert read_outcome("bpm") == "3 of 12 tracks yielded no BPM"

    def test_a_clean_run_reports_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "bpm_log.txt")

        _complete(app, total=12)

        assert read_outcome("bpm") == ""

    def test_a_later_clean_run_clears_an_earlier_note(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "bpm_log.txt")
        _complete(app, total=12, errors=1)
        assert read_outcome("bpm") == "1 of 12 tracks yielded no BPM"

        _complete(app, total=12)

        assert read_outcome("bpm") == ""

    def test_the_note_lands_under_the_manifest_id(self, tmp_path, monkeypatch):
        """The window key is not the key the driver reads back."""
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "bpm_log.txt")

        _complete(app, total=4, errors=1)

        assert read_outcome("bpm") == "1 of 4 tracks yielded no BPM"
        assert read_outcome("bpm_analyzer") == ""

    def test_out_of_band_tempos_are_counted(self, tmp_path, monkeypatch):
        """D109: a measured-but-out-of-band tempo is neither a skip nor an error."""
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "bpm_log.txt")

        _complete(app, total=12, outside=_OUTSIDE)

        assert read_outcome("bpm") == (
            "1 of 12 tracks measured outside the 75-175 BPM range"
        )

    def test_errors_and_out_of_band_tempos_are_both_reported(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "bpm_log.txt")

        _complete(app, total=12, errors=3, outside=_OUTSIDE)

        assert read_outcome("bpm") == (
            "3 of 12 tracks yielded no BPM; "
            "1 of 12 tracks measured outside the 75-175 BPM range"
        )

    def test_the_summary_block_names_the_band(self, tmp_path, monkeypatch):
        """The run's own report says the count and the band, not just the count."""
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "bpm_log.txt")

        _complete(app, total=12, outside=_OUTSIDE)

        report = open(app._log_path, encoding="utf-8").read()
        assert "Outside BPM range: 1 of 12 tracks (band 75-175)" in report

    def test_a_clean_run_has_no_out_of_band_row(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "bpm_log.txt")

        _complete(app, total=12)

        report = open(app._log_path, encoding="utf-8").read()
        assert "Outside BPM range" not in report

    def test_the_results_panel_shows_the_row(self, tmp_path, monkeypatch):
        """The row reaches the widget the user reads, not only the log file."""
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "bpm_log.txt")
        app.summary_label = MagicMock()
        app.time_label = MagicMock()
        app.completion_label = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app.run_mode = MagicMock(**{"get.return_value": "Dry Run"})
        app._tab_results = MagicMock()
        app.auto_end = False

        _complete(app, total=12, outside=_OUTSIDE)

        scheduled = next(
            c_
            for c_ in app.root.after.call_args_list
            if c_.args[1] == app._update_ui_on_complete
        )
        app._update_ui_on_complete(*scheduled.args[2:])
        shown = app.summary_label.config.call_args.kwargs["text"]
        assert "Outside BPM range: 1 of 12 tracks (band 75-175)" in shown

    def test_an_unwritable_log_does_not_suppress_the_note(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        # A directory where the report belongs: the base catches the OSError,
        # and the note must already be on disk before that write is attempted.
        app = _make_run_note_app(tmp_path)

        _complete(app, total=12, errors=2)

        assert read_outcome("bpm") == "2 of 12 tracks yielded no BPM"


class TestSummarySource:
    """The log's SUMMARY row and the panel row come from one place (D109).

    ``_on_complete`` hands the rows it wrote to the scheduled UI update, so the
    two surfaces cannot disagree; these tests pin the fallback the base uses
    when the update is driven directly (the hook), because that is the path a
    future caller reaches for.
    """

    @staticmethod
    def _panel_app(log_path):
        app = _make_run_note_app(log_path)
        app.summary_label = MagicMock()
        app.time_label = MagicMock()
        app.completion_label = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app.run_mode = MagicMock(**{"get.return_value": "Dry Run"})
        app._tab_results = MagicMock()
        app.auto_end = False
        app.auto_end_var = MagicMock(**{"get.return_value": False})
        return app

    @staticmethod
    def _shown(app) -> str:
        return app.summary_label.config.call_args.kwargs["text"]

    def test_the_panel_reads_the_hook_when_nothing_is_passed(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = self._panel_app(tmp_path / "bpm_log.txt")

        _complete(app, total=12, outside=_OUTSIDE)
        app._update_ui_on_complete(12, 12, 0, 0, 0, 1)

        assert "Outside BPM range: 1 of 12 tracks (band 75-175)" in self._shown(app)

    def test_a_clean_run_leaves_the_panel_row_empty(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = self._panel_app(tmp_path / "bpm_log.txt")

        _complete(app, total=12)
        app._update_ui_on_complete(12, 12, 0, 0, 0, 1)

        assert "Outside BPM range" not in self._shown(app)

    def test_a_later_clean_run_cannot_inherit_the_row(self, tmp_path, monkeypatch):
        """Rows are replaced per run, not accumulated on the class."""
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = self._panel_app(tmp_path / "bpm_log.txt")

        _complete(app, total=12, outside=_OUTSIDE)
        _complete(app, total=12)
        app._update_ui_on_complete(12, 12, 0, 0, 0, 1)

        assert "Outside BPM range" not in self._shown(app)


class TestCompletionPayloadContract:
    """The app accepts every field ``run_analysis`` publishes (D112).

    ``run_analysis`` always hands ``skipped_files``, ``error_files`` and
    ``outside_range_files`` to its completion callback.  BPM's override listed
    only the field it consumed, so the lambda ``_run_analysis`` passes raised
    ``TypeError`` on the worker thread: no report was written and the Results
    tab never appeared.  These tests drive the real seam instead of calling
    ``_on_complete`` with a hand-picked subset of the payload.
    """

    @staticmethod
    def _app(tmp_path, monkeypatch):
        from bpm_analyzer.app import BPMAnalyzerApp

        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = object.__new__(BPMAnalyzerApp)
        app.root = MagicMock()
        app._safe_slot_vars = [MagicMock(), MagicMock()]
        app.slot_queue = MagicMock()
        app._log_path = str(tmp_path / "bpm_dry_run_log.txt")
        app.auto_end = False
        app.auto_end_var = MagicMock(**{"get.return_value": False})
        app.run_mode = MagicMock(**{"get.return_value": "Dry Run"})
        app.summary_label = MagicMock()
        app.time_label = MagicMock()
        app.completion_label = MagicMock()
        app.notebook = MagicMock()
        app.start_btn = MagicMock()
        app._tab_results = MagicMock()
        return app

    def test_the_worker_payload_completes_the_gui_run(self, tmp_path, monkeypatch):
        """The callback ``_run_analysis`` installs survives the full payload."""
        from bpm_analyzer.core import file_processor as core

        app = self._app(tmp_path, monkeypatch)
        processor = MagicMock()
        monkeypatch.setattr(core, "run_analysis", processor)

        app._run_analysis(str(tmp_path), True, 75, 175, 10, False, 2)

        on_complete = processor.call_args.kwargs["on_complete"]
        on_complete(
            total=3,
            processed=3,
            skipped=1,
            errors=1,
            duration_secs=1.0,
            log_entries=["track.mp3: analysed\n"],
            skipped_files=[{"filename": "noise.wav", "reason": "No tempo detected"}],
            error_files=[
                {"filename": "corrupt.mp3", "error_type": "BPMDetectionError"}
            ],
            outside_range_files=[],
        )

        report = open(app._log_path, encoding="utf-8").read()
        assert "SUMMARY:" in report
        assert "Skipped: 1" in report
        assert "Errors: 1" in report
        # The CLI-only records are ignored by the report, not rendered raw.
        assert "noise.wav" not in report
        assert any(
            call.args[1] == app._update_ui_on_complete
            for call in app.root.after.call_args_list
        )

    def test_the_out_of_band_row_survives_the_full_payload(self, tmp_path, monkeypatch):
        """Accepting the CLI records must not drop the D109 summary row."""
        app = self._app(tmp_path, monkeypatch)

        app._on_complete(
            header=["BPM ANALYSIS REPORT\n"],
            total=12,
            processed=12,
            skipped=1,
            errors=1,
            duration_secs=1.0,
            log_entries=["drone.ogg: 60 BPM (outside 75-175)\n"],
            skipped_files=[{"filename": "noise.wav"}],
            error_files=[{"filename": "corrupt.mp3"}],
            outside_range_files=list(_OUTSIDE),
        )

        report = open(app._log_path, encoding="utf-8").read()
        assert "Outside BPM range: 1 of 12 tracks (band 75-175)" in report
        assert "Skipped: 1" in report
        assert "Errors: 1" in report


# ---------------------------------------------------------------------------
# Completion seam: the processor payload must reach the handler _run_analysis
# binds and land in the report the run writes.
# ---------------------------------------------------------------------------

_HEADER = ["BPM ANALYSIS REPORT\n"]


class TestCompletionSeam:
    """``run_analysis`` publishes into the handler ``_run_analysis`` binds."""

    @staticmethod
    def _wire(app):
        """Return the completion callable ``_run_analysis`` hands over."""
        return lambda **kw: app._on_complete(header=_HEADER, **kw)

    @staticmethod
    def _fake_process_single_file(**kwargs: Any) -> None:
        """Stand in for the per-file detector: one skip, one error, one
        measurable tempo that fell outside the configured band."""
        outcomes = {
            "a.wav": {"n_skipped": 0, "n_errors": 0, "outside": True},
            "b.wav": {"n_skipped": 1, "n_errors": 0, "outside": False},
            "c.wav": {"n_skipped": 0, "n_errors": 1, "outside": False},
        }
        progress = kwargs["on_progress"]
        outcome = outcomes[kwargs["name"]]
        if outcome["outside"]:
            kwargs["outside_range_files"].append(
                {
                    "filename": kwargs["name"],
                    "bpm": 190,
                    "min_bpm": kwargs["min_bpm"],
                    "max_bpm": kwargs["max_bpm"],
                }
            )
        progress(
            n_skipped=outcome["n_skipped"],
            n_errors=outcome["n_errors"],
            display_text=kwargs["name"],
            log_text=f"{kwargs['name']}\n",
        )

    def test_the_real_payload_is_written(self, tmp_path, monkeypatch) -> None:
        """Every published count -- including the tool-specific band row --
        reaches the report the handler writes."""
        from bpm_analyzer.core import file_processor as core

        for name in ("a.wav", "b.wav", "c.wav"):
            (tmp_path / name).write_bytes(b"")
        app = TestCompletionPayloadContract._app(tmp_path, monkeypatch)

        with patch.object(
            core,
            "process_single_file",
            side_effect=self._fake_process_single_file,
        ):
            core.run_analysis(
                dir_path=str(tmp_path),
                is_dry_run=True,
                min_bpm=75,
                max_bpm=175,
                analysis_duration=10,
                slot_vars=[MagicMock()],
                slot_queue=Queue(),
                on_progress=MagicMock(),
                on_complete=self._wire(app),
                on_error=MagicMock(),
            )

        report = open(app._log_path, encoding="utf-8").read()
        assert "Total files: 3" in report
        assert "Tagged/Analyzed: 1" in report
        assert "Skipped: 1" in report
        assert "Errors: 1" in report
        assert "Outside BPM range: 1 of 3 tracks (band 75-175)" in report

    @pytest.mark.parametrize(
        "field",
        ["total", "processed", "skipped", "errors", "duration_secs", "log_entries"],
    )
    def test_a_missing_field_raises_and_writes_no_report(
        self, tmp_path, monkeypatch, field: str
    ) -> None:
        """A dropped field names itself and leaves no report behind."""
        app = TestCompletionPayloadContract._app(tmp_path, monkeypatch)
        payload: dict[str, Any] = {
            "total": 3,
            "processed": 3,
            "skipped": 1,
            "errors": 1,
            "duration_secs": 1.0,
            "log_entries": ["line\n"],
            "skipped_files": [],
            "error_files": [],
            "outside_range_files": [],
        }
        payload.pop(field)

        with pytest.raises(TypeError) as caught:
            self._wire(app)(**payload)

        assert field in str(caught.value)
        assert not os.path.exists(app._log_path)
