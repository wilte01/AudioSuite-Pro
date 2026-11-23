"""
Tests for album_genre_tagger.app — GenreConsolidatorApp orchestrator.

Focus: CLI-driven Run Controls mirroring and handler wiring, using the
object.__new__ + MagicMock shell pattern (no real display required).
Changed in 2.0.0: adds the ``TestCompletionSeam`` cases driving
``run_analysis`` into the completion handler (PLAN D117).

Changed in 2.9.0: the _open_folder tests patch the shared helper (A1).
Changed in 2.9.0: the window adopts ``SuiteApp`` (C1 stage 3, D50).  The
callbacks queue their payload for the shell's poller instead of scheduling a
main-thread helper with ``root.after``, the coverage check's failure is a queued
completion of its own, and the notebook, the Processing tab and the Results tab
are the shell's — so the tests drive ``_dispatch_ui_message`` and read the
shell's frames instead of the two deleted tab delegates.
"""

import os
import tkinter as tk
from pathlib import Path
from queue import Empty, SimpleQueue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

#: The Processing tab's first list line, posted before the read phase runs.
PHASE1_HEADER = "=== PHASE1: READING TITLEGENRE TAGS ==="


def _make_shell_app(parsed):
    """Build a GenreConsolidatorApp shell with mock attributes."""
    from album_genre_tagger.app import GenreConsolidatorApp

    app = object.__new__(GenreConsolidatorApp)
    app.root = MagicMock()
    app.folder_path = MagicMock()
    app.run_mode = MagicMock()
    app.min_coverage = MagicMock()
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.auto_end_var.get.return_value = False
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()
    # Widgets touched by result callbacks
    app.progress = MagicMock()
    app.file_listbox = MagicMock()
    app.stats_label = MagicMock()
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.genre_label = MagicMock()
    app.notebook = MagicMock()
    app.overall_status = MagicMock()
    app.processing_frame = MagicMock()
    app.results_frame = MagicMock()
    app.start_btn = MagicMock()
    app._cli_args_parsed = parsed
    # Snapshotted by start_processing on the main thread (see _run's
    # thread-safety note); seeded here so callbacks can be driven directly.
    app._dir_path = ""
    app._is_dry_run = False
    app._min_coverage = 50
    app._log_path = ""
    app._ui_updates = SimpleQueue()

    handler = MagicMock()
    handler.apply_cli_args.return_value = False
    handler_cls = MagicMock(return_value=handler)
    return app, handler, handler_cls


def _run_apply(app, handler_cls):
    with patch("album_genre_tagger.app.UniversalCLIHandler", handler_cls):
        app._apply_cli_args()
    return app


def _drain(app: Any) -> list[tuple[Any, ...]]:
    """Render every queued message the way the shell's poller does."""
    rendered: list[tuple[Any, ...]] = []
    while True:
        try:
            message = app._ui_updates.get_nowait()
        except Empty:
            return rendered
        rendered.append(message)
        app._dispatch_ui_message(message)


def _flush_zero_delay(app: Any) -> None:
    """Run the main-thread work ``render_completion`` deferred on the root."""
    for call in app.root.after.call_args_list:
        if call.args[0] == 0:
            call.args[1](*call.args[2:])


class TestApplyCliArgsDriven:
    """A driver launch populates the Run Controls values before applying."""

    def test_inherited_values_applied_to_panel_vars(self, tmp_path):
        from album_genre_tagger.utils.cli_args import GenreTaggerArgs

        parsed = GenreTaggerArgs(
            folder_path=str(tmp_path),
            live_mode=True,
            auto_start=True,
            auto_end=True,
            clear_logs=True,
            parallel_run=True,
        )
        app, _, handler_cls = _make_shell_app(parsed)
        _run_apply(app, handler_cls)

        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_handler_invoked_with_folder(self, tmp_path):
        from album_genre_tagger.utils.cli_args import GenreTaggerArgs

        parsed = GenreTaggerArgs(folder_path=str(tmp_path))
        app, handler, handler_cls = _make_shell_app(parsed)
        _run_apply(app, handler_cls)

        handler.apply_cli_args.assert_called_once_with(
            parsed, folder_var=app.folder_path
        )

    def test_auto_start_schedules_processing(self, tmp_path):
        from album_genre_tagger.utils.cli_args import GenreTaggerArgs

        app, _, handler_cls = _make_shell_app(
            GenreTaggerArgs(folder_path=str(tmp_path))
        )
        handler_cls.return_value.apply_cli_args.return_value = True
        _run_apply(app, handler_cls)

        after_delays = [call.args[0] for call in app.root.after.call_args_list]
        assert 1500 in after_delays


class TestApplyCliArgsStandalone:
    """Standalone start: defaults applied, no handler/after scheduling."""

    def test_defaults_applied_to_panel_vars(self):
        from album_genre_tagger.utils.cli_args import GenreTaggerArgs

        app, _, handler_cls = _make_shell_app(GenreTaggerArgs())
        _run_apply(app, handler_cls)

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.auto_start_var.set.assert_called_once_with(False)
        app.auto_end_var.set.assert_called_once_with(False)
        app.clear_logs_var.set.assert_called_once_with(False)
        app.parallel_var.set.assert_called_once_with(False)

    def test_no_handler_or_scheduling_without_folder(self):
        from album_genre_tagger.utils.cli_args import GenreTaggerArgs

        app, handler, handler_cls = _make_shell_app(GenreTaggerArgs())
        _run_apply(app, handler_cls)

        app.run_mode.set.assert_called_once_with("Dry Run")
        handler.apply_cli_args.assert_not_called()
        app.root.after.assert_not_called()


class TestCallbackSignatureConsistency:
    """Verify callback signatures match between app.py and core/consolidator.py."""

    def test_on_complete_accepts_all_kwargs_from_consolidator(self, tmp_path):
        app, _, _ = _make_shell_app(None)
        app._log_path = str(tmp_path / "genre_log.txt")
        app._is_dry_run = True

        app._on_complete(
            total=10,
            files_with_genre=8,
            coverage_pct=80.0,
            unique_genres=["Rock", "Pop"],
            album_genre_string="Rock; Pop",
            write_count=10,
            write_errors=0,
            read_errors=0,
            duration_secs=1.5,
            log_entries=["line\n"],
        )

    def test_on_coverage_fail_accepts_all_kwargs_from_consolidator(self, tmp_path):
        app, _, _ = _make_shell_app(None)
        app._log_path = str(tmp_path / "genre_log.txt")

        app._on_coverage_fail(
            total=10,
            files_with_genre=3,
            coverage_pct=30.0,
            min_coverage=50,
            duration_secs=1.0,
            log_entries=["line\n"],
        )


class TestRunOpensUndoBatch:
    """Phase 2: _run must wrap the consolidator analysis in an active
    ``tag_edit`` undo batch so writes auto-snapshot."""

    def test_app_run_wraps_analysis_in_active_batch(self, tmp_path):
        from album_genre_tagger.app import GenreConsolidatorApp

        app = object.__new__(GenreConsolidatorApp)
        app.root = MagicMock()
        app._dir_path = str(tmp_path)
        app._is_dry_run = True
        app._min_coverage = 50

        mock_active_batch = MagicMock()
        with (
            patch("album_genre_tagger.app.active_batch", mock_active_batch),
            patch("album_genre_tagger.app.consolidator.run_analysis") as mock_run,
        ):
            app._run()

        mock_active_batch.assert_called_once_with("album_genre_tagger", "tag_edit")
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["dir_path"] == str(tmp_path)
        assert mock_run.call_args.kwargs["min_coverage"] == 50
        assert mock_run.call_args.kwargs["is_dry_run"] is True


class TestQueuedMarshalling:
    """Callbacks fire on the worker thread: every one queues, none writes (H3).

    The payloads are read back from the queue the shell's poller drains, so a
    widget call made from the worker path leaves the queue empty and fails.
    """

    def test_start_processing_snapshots_tk_vars_and_starts_the_worker(self, tmp_path):
        """The worker must never call .get() on a Tk variable."""
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = str(tmp_path)
        app.run_mode.get.return_value = "Live Update"
        app.min_coverage.get.return_value = 72
        app._start_worker = MagicMock()

        app.start_processing()

        assert app._dir_path == str(tmp_path)
        assert app._is_dry_run is False
        assert app._min_coverage == 72
        assert app._log_path == str(tmp_path / "AlbumGenre_Tagger_Log.txt")
        app._start_worker.assert_called_once_with(app._run, ())

    @patch("audio_suite_shared.suite_app.messagebox")
    def test_every_callback_queues_its_payload(self, mock_mb, tmp_path):
        app, _, _ = _make_shell_app(None)
        app._log_path = str(tmp_path / "genre_log.txt")
        app._is_dry_run = True

        app._on_phase1_progress(1, 3, 1, 0, "display", "log")
        app._on_phase2_progress("display2", "log2")
        app._on_coverage_fail(3, 1, 33.0, 50, 1.0, ["line\n"])
        app._on_complete(
            total=3,
            files_with_genre=3,
            coverage_pct=100.0,
            unique_genres=["Rock"],
            album_genre_string="Rock",
            write_count=3,
            write_errors=0,
            read_errors=0,
            duration_secs=1.0,
            log_entries=["line\n"],
        )
        app._on_error("boom")

        queued = [message[0] for message in _drain(app)]
        assert queued == [
            "phase1",
            "phase2",
            "coverage_fail",
            "complete",
            "error",
        ]

    def test_the_run_makes_no_widget_writes_of_its_own(self, tmp_path):
        app, _, _ = _make_shell_app(None)

        app._on_phase1_progress(1, 3, 1, 0, "display", "log")
        app._on_phase2_progress("display2", "log2")

        app.progress.__setitem__.assert_not_called()
        app.file_listbox.insert.assert_not_called()
        app.stats_label.config.assert_not_called()
        app.root.after.assert_not_called()

    def test_log_write_failure_queues_the_dialog(self, tmp_path):
        app, _, _ = _make_shell_app(None)
        app._log_path = str(tmp_path / "missing_dir" / "genre_log.txt")
        app.error_logger = MagicMock()

        app._write_log(["line\n"])

        message = app._ui_updates.get_nowait()
        assert message[0] == "log_error"
        assert "Could not write log file" in message[1]


class TestRealWidgetMarshalling:
    """One queued message reaches a real Tk widget through the dispatcher."""

    def test_dispatched_line_lands_in_a_real_listbox(self, root):
        from album_genre_tagger.app import GenreConsolidatorApp

        top = tk.Toplevel(root)
        try:
            app = object.__new__(GenreConsolidatorApp)
            app.root = top
            app.file_listbox = tk.Listbox(top)
            app._ui_updates = SimpleQueue()
            app._ui_updates.put(("phase2", "real widget line"))

            assert app.file_listbox.size() == 0  # nothing written yet
            _drain(app)
            assert app.file_listbox.get(0, tk.END) == ("real widget line",)
        finally:
            top.destroy()


# ---------------------------------------------------------------------------
# Preset CRUD
# ---------------------------------------------------------------------------


class TestCollectSettings:
    """_collect_settings reads the two Tk vars into a plain dict."""

    def test_returns_run_mode_and_min_coverage(self):
        app, _, _ = _make_shell_app(None)
        app.run_mode.get.return_value = "Live Update"
        app.min_coverage.get.return_value = 72

        result = app._collect_settings()

        assert result == {"run_mode": "Live Update", "min_coverage": 72}

    def test_dry_run_mode(self):
        app, _, _ = _make_shell_app(None)
        app.run_mode.get.return_value = "Dry Run"
        app.min_coverage.get.return_value = 50

        result = app._collect_settings()

        assert result == {"run_mode": "Dry Run", "min_coverage": 50}


class TestApplyPreset:
    """_apply_preset sets Tk vars from a settings dict."""

    def test_sets_both_keys(self):
        app, _, _ = _make_shell_app(None)

        app._apply_preset({"run_mode": "Live Update", "min_coverage": 80})

        app.run_mode.set.assert_called_once_with("Live Update")
        app.min_coverage.set.assert_called_once_with(80)

    def test_partial_dict_only_sets_present_keys(self):
        app, _, _ = _make_shell_app(None)

        app._apply_preset({"min_coverage": 30})

        app.run_mode.set.assert_not_called()
        app.min_coverage.set.assert_called_once_with(30)

    def test_empty_dict_does_nothing(self):
        app, _, _ = _make_shell_app(None)

        app._apply_preset({})

        app.run_mode.set.assert_not_called()
        app.min_coverage.set.assert_not_called()

        app._apply_preset({"run_mode": "Dry Run"})

        app.run_mode.set.assert_called_once_with("Dry Run")

    def test_unknown_keys_ignored(self):
        app, _, _ = _make_shell_app(None)

        app._apply_preset({"run_mode": "Dry Run", "unknown_key": True})

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.min_coverage.set.assert_not_called()


class TestOnPresetSelected:
    """_on_preset_selected loads a preset via suite_config and applies it."""

    @patch("album_genre_tagger.app.suite_config")
    def test_loads_and_applies_when_found(self, mock_sc):
        app, _, _ = _make_shell_app(None)
        mock_sc.load_preset.return_value = {
            "run_mode": "Live Update",
            "min_coverage": 65,
        }

        app._on_preset_selected("My Preset")

        mock_sc.load_preset.assert_called_once_with("album_genre_tagger", "My Preset")
        app.run_mode.set.assert_called_once_with("Live Update")
        app.min_coverage.set.assert_called_once_with(65)

    @patch("album_genre_tagger.app.suite_config")
    def test_empty_settings_does_not_apply(self, mock_sc):
        app, _, _ = _make_shell_app(None)
        mock_sc.load_preset.return_value = {}

        app._on_preset_selected("Empty Preset")

        mock_sc.load_preset.assert_called_once_with(
            "album_genre_tagger", "Empty Preset"
        )
        app.run_mode.set.assert_not_called()
        app.min_coverage.set.assert_not_called()

    @patch("album_genre_tagger.app.suite_config")
    def test_none_return_does_not_apply(self, mock_sc):
        app, _, _ = _make_shell_app(None)
        mock_sc.load_preset.return_value = None

        app._on_preset_selected("Missing Preset")

        mock_sc.load_preset.assert_called_once_with(
            "album_genre_tagger", "Missing Preset"
        )
        app.run_mode.set.assert_not_called()
        app.min_coverage.set.assert_not_called()


class TestSaveCurrentAsPreset:
    """_save_current_as_preset saves collected settings then refreshes."""

    @patch("album_genre_tagger.app.suite_config")
    def test_saves_and_refreshes(self, mock_sc):
        app, _, _ = _make_shell_app(None)
        app.run_mode.get.return_value = "Dry Run"
        app.min_coverage.get.return_value = 50
        app._refresh_preset_list = MagicMock()
        mock_sc.list_presets.return_value = ["Preset A", "New Preset"]

        app._save_current_as_preset("New Preset")

        mock_sc.save_preset.assert_called_once_with(
            "album_genre_tagger",
            "New Preset",
            {"run_mode": "Dry Run", "min_coverage": 50},
        )
        mock_sc.list_presets.assert_called_once_with("album_genre_tagger")
        app._refresh_preset_list.assert_called_once_with(["Preset A", "New Preset"])


class TestDeletePreset:
    """_delete_preset deletes then refreshes the list."""

    @patch("album_genre_tagger.app.suite_config")
    def test_deletes_and_refreshes(self, mock_sc):
        app, _, _ = _make_shell_app(None)
        app._refresh_preset_list = MagicMock()
        mock_sc.list_presets.return_value = ["Remaining"]

        app._delete_preset("Old Preset")

        mock_sc.delete_preset.assert_called_once_with(
            "album_genre_tagger", "Old Preset"
        )
        mock_sc.list_presets.assert_called_once_with("album_genre_tagger")
        app._refresh_preset_list.assert_called_once_with(["Remaining"])


# ---------------------------------------------------------------------------
# Validation in start_processing
# ---------------------------------------------------------------------------


class TestStartProcessingValidation:
    """start_processing guards against bad input before starting the worker."""

    @patch("album_genre_tagger.app.messagebox")
    def test_empty_folder_shows_warning_and_returns(self, mock_mb):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = ""
        app._start_worker = MagicMock()

        app.start_processing()

        mock_mb.showwarning.assert_called_once_with(
            "Warning", "Please select a music directory first."
        )
        app.start_btn.config.assert_not_called()
        app._start_worker.assert_not_called()

    @patch("album_genre_tagger.app.os.path.isdir", return_value=False)
    @patch("album_genre_tagger.app.messagebox")
    def test_nonexistent_directory_shows_error_and_returns(self, mock_mb, mock_isdir):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/not/a/dir"
        app._start_worker = MagicMock()

        app.start_processing()

        mock_mb.showerror.assert_called_once_with(
            "Error", "Selected path is not a valid directory."
        )
        app.start_btn.config.assert_not_called()
        app._start_worker.assert_not_called()

    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_negative_coverage_shows_error(self, mock_mb, mock_isdir):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.min_coverage.get.return_value = -5
        app._start_worker = MagicMock()

        app.start_processing()

        mock_mb.showerror.assert_called_once_with(
            "Error", "Coverage percentage must be between 0 and 100."
        )
        app._start_worker.assert_not_called()

    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_coverage_over_100_shows_error(self, mock_mb, mock_isdir):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.min_coverage.get.return_value = 150
        app._start_worker = MagicMock()

        app.start_processing()

        mock_mb.showerror.assert_called_once_with(
            "Error", "Coverage percentage must be between 0 and 100."
        )
        app._start_worker.assert_not_called()

    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_zero_coverage_is_valid(self, mock_mb, mock_isdir):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.run_mode.get.return_value = "Dry Run"
        app.min_coverage.get.return_value = 0
        app._start_worker = MagicMock()

        app.start_processing()

        mock_mb.showerror.assert_not_called()
        app._start_worker.assert_called_once()

    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_100_coverage_is_valid(self, mock_mb, mock_isdir):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.run_mode.get.return_value = "Dry Run"
        app.min_coverage.get.return_value = 100
        app._start_worker = MagicMock()

        app.start_processing()

        mock_mb.showerror.assert_not_called()
        app._start_worker.assert_called_once()

    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_success_disables_btn_clears_listbox_switches_tab(
        self, mock_mb, mock_isdir
    ):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.run_mode.get.return_value = "Live Update"
        app.min_coverage.get.return_value = 60
        app._start_worker = MagicMock()

        app.start_processing()

        app.start_btn.config.assert_called_once_with(state="disabled")
        app.file_listbox.delete.assert_called_once_with(0, tk.END)
        app.file_listbox.insert.assert_called_once_with(tk.END, PHASE1_HEADER)
        app.notebook.select.assert_called_once_with(app.processing_frame)
        app.overall_status.set.assert_called_once_with("Processing genres...")

    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_success_snapshots_vars_and_starts_the_worker(self, mock_mb, mock_isdir):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/my/music"
        app.run_mode.get.return_value = "Dry Run"
        app.min_coverage.get.return_value = 75
        app._start_worker = MagicMock()

        app.start_processing()

        assert app._dir_path == "/my/music"
        assert app._is_dry_run is True
        assert app._min_coverage == 75
        assert app._log_path == os.path.join("/my/music", "AlbumGenre_Tagger_Log.txt")
        app._start_worker.assert_called_once_with(app._run, ())

    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_live_mode_is_not_dry_run(self, mock_mb, mock_isdir):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.run_mode.get.return_value = "Live Update"
        app.min_coverage.get.return_value = 50
        app._start_worker = MagicMock()

        app.start_processing()

        assert app._is_dry_run is False


# ---------------------------------------------------------------------------
# Rendering: one queued message at a time, on the Tk thread
# ---------------------------------------------------------------------------


class TestPhase1Message:
    """A phase-1 tick reserves the write phase's last bar step."""

    def test_sets_progress_and_inserts_display_text(self):
        app, _, _ = _make_shell_app(None)

        app._dispatch_ui_message(("phase1", 3, 10, 2, 1, "Track 03 - Artist - Title"))

        assert app.progress.__setitem__.call_args_list[0].args == ("maximum", 11)
        assert app.progress.__setitem__.call_args_list[1].args == ("value", 3)
        app.stats_label.config.assert_called_once_with(
            text="Processed: 3 | With Genre: 2 | Errors: 1"
        )
        app.file_listbox.insert.assert_called_once_with(
            tk.END, "Track 03 - Artist - Title"
        )
        app.file_listbox.see.assert_called_once_with(tk.END)

    def test_first_file_zero_errors(self):
        app, _, _ = _make_shell_app(None)

        app._dispatch_ui_message(("phase1", 1, 5, 0, 0, "Track 01"))

        app.stats_label.config.assert_called_once_with(
            text="Processed: 1 | With Genre: 0 | Errors: 0"
        )

    def test_total_plus_one_reserves_write_phase(self):
        app, _, _ = _make_shell_app(None)

        app._dispatch_ui_message(("phase1", 0, 20, 0, 0, "header"))

        assert app.progress.__setitem__.call_args_list[0].args == ("maximum", 21)


class TestCoverageFailMessage:
    """The coverage check's failure renders as a completion of its own."""

    def test_displays_failure_summary(self):
        app, _, _ = _make_shell_app(None)

        app._dispatch_ui_message(("coverage_fail", 10, 3, 30.0, 50, 65.5))
        _flush_zero_delay(app)

        app.summary_label.config.assert_called_once()
        summary_text = app.summary_label.config.call_args.kwargs["text"]
        assert "Total: 10 files" in summary_text
        assert "With TITLEGENRE: 3 (30.0%)" in summary_text
        assert "Required: 50%" in summary_text
        assert "FAILED" in summary_text
        app.genre_label.config.assert_called_once_with(text="")
        app.completion_label.config.assert_called_once_with(
            text="Coverage Check Failed!"
        )
        app.time_label.config.assert_called_once_with(text="Total Time: 01:05")
        app.notebook.select.assert_called_once_with(app.results_frame)
        app.start_btn.config.assert_called_once_with(state="normal")

    def test_auto_end_schedules_destroy(self):
        app, _, _ = _make_shell_app(None)
        app.auto_end_var.get.return_value = True

        app._dispatch_ui_message(("coverage_fail", 5, 1, 20.0, 50, 1.0))

        destroy_calls = [
            c for c in app.root.after.call_args_list if c.args[1] == app.root.destroy
        ]
        assert len(destroy_calls) == 1
        assert destroy_calls[0].args[0] == 2000

    def test_no_auto_end_does_not_schedule_destroy(self):
        app, _, _ = _make_shell_app(None)

        app._dispatch_ui_message(("coverage_fail", 5, 1, 20.0, 50, 1.0))

        destroy_calls = [
            c for c in app.root.after.call_args_list if c.args[1] == app.root.destroy
        ]
        assert len(destroy_calls) == 0


class TestCompleteMessage:
    """The finished run's summary, heading and bar."""

    def test_dry_run_shows_analysis_complete(self):
        app, _, _ = _make_shell_app(None)
        app._is_dry_run = True

        app._dispatch_ui_message(
            (
                "complete",
                8,
                8,
                100.0,
                ["Rock", "Pop"],
                "Rock; Pop",
                8,
                0,
                0,
                122.0,
            )
        )
        _flush_zero_delay(app)

        summary_text = app.summary_label.config.call_args.kwargs["text"]
        assert "Total: 8 files" in summary_text
        assert "With TITLEGENRE: 8 (100.0%)" in summary_text
        assert "Unique genres found: 2" in summary_text
        assert "would be updated: 8" in summary_text
        assert "Errors: 0" in summary_text
        app.genre_label.config.assert_called_once_with(
            text="Consolidated ALBUMGENRE:\nRock; Pop"
        )
        app.completion_label.config.assert_called_once_with(text="Analysis Complete!")
        app.time_label.config.assert_called_once_with(text="Total Time: 02:02")
        app.notebook.select.assert_called_once_with(app.results_frame)
        app.start_btn.config.assert_called_once_with(state="normal")

    def test_live_mode_shows_consolidation_complete(self):
        app, _, _ = _make_shell_app(None)
        app._is_dry_run = False

        app._dispatch_ui_message(
            ("complete", 5, 5, 100.0, ["Jazz"], "Jazz", 5, 1, 0, 5.0)
        )
        _flush_zero_delay(app)

        app.completion_label.config.assert_called_once_with(
            text="Genre Consolidation Complete!"
        )
        summary_text = app.summary_label.config.call_args.kwargs["text"]
        assert "would be" not in summary_text
        assert "Errors: 1" in summary_text

    def test_auto_end_schedules_destroy(self):
        app, _, _ = _make_shell_app(None)
        app.auto_end_var.get.return_value = True
        app._is_dry_run = True

        app._dispatch_ui_message(
            ("complete", 2, 2, 100.0, ["Pop"], "Pop", 2, 0, 0, 1.0)
        )

        destroy_calls = [
            c for c in app.root.after.call_args_list if c.args[1] == app.root.destroy
        ]
        assert len(destroy_calls) == 1
        assert destroy_calls[0].args[0] == 2000
        app.overall_status.set.assert_called_once_with(
            "Auto End enabled - closing in 2 seconds..."
        )

    def test_no_auto_end_does_not_schedule_destroy(self):
        app, _, _ = _make_shell_app(None)
        app._is_dry_run = True

        app._dispatch_ui_message(("complete", 2, 2, 100.0, [], "", 0, 0, 0, 0.5))

        destroy_calls = [
            c for c in app.root.after.call_args_list if c.args[1] == app.root.destroy
        ]
        assert len(destroy_calls) == 0

    def test_progress_value_set_to_total_plus_one(self):
        app, _, _ = _make_shell_app(None)
        app._is_dry_run = True

        app._dispatch_ui_message(
            ("complete", 12, 12, 100.0, ["Rock"], "Rock", 12, 0, 0, 10.0)
        )

        assert app.progress.__setitem__.call_args.args == ("value", 13)

    def test_errors_summed_read_and_write(self):
        app, _, _ = _make_shell_app(None)
        app._is_dry_run = True

        app._dispatch_ui_message(("complete", 10, 10, 100.0, [], "", 10, 3, 2, 1.0))

        summary_text = app.summary_label.config.call_args.kwargs["text"]
        assert "Errors: 5" in summary_text


class TestErrorMessage:
    """A queued run error is the shell's dialog plus a usable start button."""

    @patch("audio_suite_shared.suite_app.messagebox")
    def test_shows_error_and_reenables_start(self, mock_mb):
        app, _, _ = _make_shell_app(None)

        app._dispatch_ui_message(("error", "Something went wrong"))

        mock_mb.showerror.assert_called_once_with("Error", "Something went wrong")
        app.start_btn.config.assert_called_once_with(state="normal")

    @patch("audio_suite_shared.suite_app.messagebox")
    def test_empty_message(self, mock_mb):
        app, _, _ = _make_shell_app(None)

        app._dispatch_ui_message(("error", ""))

        mock_mb.showerror.assert_called_once_with("Error", "")


class TestResetProgressUi:
    """_reset_progress_ui zeros the progress bar and inserts the header."""

    def test_resets_and_inserts_header(self):
        app, _, _ = _make_shell_app(None)

        app._reset_progress_ui()

        assert app.progress.__setitem__.call_args.args == ("value", 0)
        app.file_listbox.insert.assert_called_once_with(tk.END, PHASE1_HEADER)


class TestLogErrorMessage:
    """A failed report write reaches the user through the poller's dialog."""

    @patch("album_genre_tagger.app.messagebox")
    def test_shows_error_dialog(self, mock_mb):
        app, _, _ = _make_shell_app(None)

        app._dispatch_ui_message(
            ("log_error", "Could not write log file:\nPermission denied")
        )

        mock_mb.showerror.assert_called_once_with(
            "Error", "Could not write log file:\nPermission denied"
        )

    @patch("album_genre_tagger.app.messagebox")
    def test_long_message_passed_through(self, mock_mb):
        app, _, _ = _make_shell_app(None)
        long_msg = "Could not write log file:\n" + "x" * 500

        app._dispatch_ui_message(("log_error", long_msg))

        mock_mb.showerror.assert_called_once_with("Error", long_msg)


# ---------------------------------------------------------------------------
# _write_log success path
# ---------------------------------------------------------------------------


class TestWriteLogSuccess:
    """_write_log writes entries to disk when the path is valid."""

    def test_writes_log_entries_to_file(self, tmp_path):
        app, _, _ = _make_shell_app(None)
        log_file = tmp_path / "log.txt"
        app._log_path = str(log_file)
        app.error_logger = MagicMock()

        app._write_log(["line 1\n", "line 2\n"])

        assert log_file.read_text(encoding="utf-8") == "line 1\nline 2\n"
        app.error_logger.log_error.assert_not_called()

    def test_overwrites_existing_log(self, tmp_path):
        app, _, _ = _make_shell_app(None)
        log_file = tmp_path / "log.txt"
        log_file.write_text("old content\n", encoding="utf-8")
        app._log_path = str(log_file)
        app.error_logger = MagicMock()

        app._write_log(["new content\n"])

        assert log_file.read_text(encoding="utf-8") == "new content\n"


# ---------------------------------------------------------------------------
# Completion seam: the processor payload must reach the handler _run binds and
# land in the report the run writes.
# ---------------------------------------------------------------------------


def _completion_shell(directory: Path) -> Any:
    """Shell with only what the completion path touches."""
    from album_genre_tagger.app import GenreConsolidatorApp

    app = object.__new__(GenreConsolidatorApp)
    app.root = MagicMock()
    app._dir_path = str(directory)
    app._is_dry_run = True
    app._min_coverage = 50
    app._log_path = os.path.join(str(directory), "AlbumGenre_Tagger_Log.txt")
    app.error_logger = MagicMock()
    app.auto_end_var = MagicMock()
    app.auto_end_var.get.return_value = False
    app.overall_status = MagicMock()
    app.progress = MagicMock()
    app.file_listbox = MagicMock()
    app.stats_label = MagicMock()
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.genre_label = MagicMock()
    app.notebook = MagicMock()
    app.results_frame = MagicMock()
    app.start_btn = MagicMock()
    app._ui_updates = SimpleQueue()
    return app


class TestCompletionSeam:
    """``run_analysis`` publishes into the handler ``_run`` binds."""

    @staticmethod
    def _fake_read_titlegenre(filepath: str) -> tuple[str, str]:
        """Two files carry a TITLEGENRE, one does not."""
        genres = {
            "a.wav": "Rock",
            "b.wav": "Jazz",
        }
        name = os.path.basename(filepath)
        if name in genres:
            return genres[name], ""
        return "", "no TITLEGENRE tag"

    @staticmethod
    def _fake_write_album_genre(
        filepath: str, album_genre: str, is_dry_run: bool
    ) -> tuple[bool, str]:
        """One write fails, so write_errors is distinct from read_errors."""
        if os.path.basename(filepath) == "b.wav":
            return False, "file is read-only"
        return True, ""

    def _run(self, app: Any, tmp_path: Path) -> None:
        """Drive the real entry point through the wiring ``_run`` uses."""
        from album_genre_tagger.core import consolidator

        for name in ("a.wav", "b.wav", "c.wav"):
            (tmp_path / name).write_bytes(b"")

        with (
            patch.object(
                consolidator,
                "read_titlegenre",
                side_effect=self._fake_read_titlegenre,
            ),
            patch.object(
                consolidator,
                "write_album_genre",
                side_effect=self._fake_write_album_genre,
            ),
        ):
            consolidator.run_analysis(
                dir_path=str(tmp_path),
                is_dry_run=True,
                min_coverage=50,
                on_phase1_progress=app._on_phase1_progress,
                on_coverage_fail=app._on_coverage_fail,
                on_phase2_progress=app._on_phase2_progress,
                on_complete=app._on_complete,
                on_error=MagicMock(),
            )

    def test_the_real_payload_is_written(self, tmp_path: Path) -> None:
        """Every published count reaches the log and the panel this run writes."""
        app = _completion_shell(tmp_path)

        self._run(app, tmp_path)
        _drain(app)
        _flush_zero_delay(app)

        report = (tmp_path / "AlbumGenre_Tagger_Log.txt").read_text(encoding="utf-8")
        assert "Total files: 3" in report
        assert "Files with TITLEGENRE: 2 (66.7%)" in report
        assert "Unique genres: 2" in report
        assert "Files would be updated: 2" in report
        assert "Write errors: 1" in report
        assert "Read errors: 1" in report

        text = app.summary_label.config.call_args.kwargs["text"]
        assert text == (
            "Total: 3 files\n"
            "With TITLEGENRE: 2 (66.7%)\n"
            "Unique genres found: 2\n"
            "Files would be updated: 2\n"
            "Errors: 2"
        )

    @pytest.mark.parametrize(
        "field",
        [
            "total",
            "files_with_genre",
            "coverage_pct",
            "unique_genres",
            "album_genre_string",
            "write_count",
            "write_errors",
            "read_errors",
            "duration_secs",
            "log_entries",
        ],
    )
    def test_a_missing_field_raises_and_writes_no_report(
        self, tmp_path: Path, field: str
    ) -> None:
        """A dropped field names itself and leaves no log behind."""
        app = _completion_shell(tmp_path)
        payload: dict[str, Any] = {
            "total": 3,
            "files_with_genre": 2,
            "coverage_pct": 66.7,
            "unique_genres": ["Jazz", "Rock"],
            "album_genre_string": "Jazz; Rock",
            "write_count": 2,
            "write_errors": 1,
            "read_errors": 1,
            "duration_secs": 1.0,
            "log_entries": ["line\n"],
        }
        payload.pop(field)

        with pytest.raises(TypeError) as caught:
            app._on_complete(**payload)

        assert field in str(caught.value)
        assert not (tmp_path / "AlbumGenre_Tagger_Log.txt").exists()
