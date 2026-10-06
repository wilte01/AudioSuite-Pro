"""
Tests for album_genre_tagger.app — GenreConsolidatorApp orchestrator.

Focus: CLI-driven Run Controls mirroring and handler wiring, using the
object.__new__ + MagicMock shell pattern (no real display required).
"""

import os
import tkinter as tk
from unittest.mock import MagicMock, patch


def _make_shell_app(parsed):
    """Build a GenreConsolidatorApp shell with mock attributes."""
    from album_genre_tagger.app import GenreConsolidatorApp

    app = object.__new__(GenreConsolidatorApp)
    app.root = MagicMock()
    app.folder_path = MagicMock()
    app.run_mode = MagicMock()
    app.min_coverage = MagicMock()
    app.auto_end = False
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
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
    app._tab_processing = MagicMock()
    app._tab_results = MagicMock()
    app.start_btn = MagicMock()
    app._cli_args_parsed = parsed
    # Snapshotted by start_processing on the main thread (see _run's
    # thread-safety note); seeded here so callbacks can be driven directly.
    app._dir_path = ""
    app._is_dry_run = False
    app._min_coverage = 50
    app._log_path = ""

    handler = MagicMock()
    handler.apply_cli_args.return_value = False
    handler_cls = MagicMock(return_value=handler)
    return app, handler, handler_cls


def _run_apply(app, handler_cls):
    with patch("album_genre_tagger.app.UniversalCLIHandler", handler_cls):
        app._apply_cli_args()
    return app


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
        app.progress = MagicMock()
        app.file_listbox = MagicMock()
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


class TestWorkerThreadMarshalling:
    """Callbacks fire on a worker thread: every Tk write is deferred (audit H3).

    ``root.after`` records the scheduling instead of running it, so a direct
    widget call from the worker path would leave the recorded lists empty.
    """

    def _scheduled(self, app):
        return [tuple(call_.args) for call_ in app.root.after.call_args_list]

    def test_start_processing_snapshots_tk_vars_and_starts_daemon_thread(
        self, tmp_path
    ):
        """The worker must never call .get() on a Tk variable."""
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = str(tmp_path)
        app.run_mode.get.return_value = "Live Update"
        app.min_coverage.get.return_value = 72
        app.overall_status = MagicMock()

        with patch("album_genre_tagger.app.threading.Thread") as mock_thread:
            app.start_processing()

        assert app._dir_path == str(tmp_path)
        assert app._is_dry_run is False
        assert app._min_coverage == 72
        assert app._log_path == str(tmp_path / "AlbumGenre_Tagger_Log.txt")
        assert mock_thread.call_args.kwargs["daemon"] is True
        assert mock_thread.call_args.kwargs["target"] == app._run

    def test_run_schedules_its_header_instead_of_writing_widgets(self, tmp_path):
        app, _, _ = _make_shell_app(None)
        app._dir_path = str(tmp_path)
        app._is_dry_run = True
        app._min_coverage = 50

        with (
            patch("album_genre_tagger.app.active_batch"),
            patch("album_genre_tagger.app.consolidator.run_analysis"),
        ):
            app._run()

        assert self._scheduled(app) == [(0, app._reset_progress_ui)]
        app.progress.__setitem__.assert_not_called()
        app.file_listbox.insert.assert_not_called()
        # No Tk variable was read on the worker thread.
        app.folder_path.get.assert_not_called()
        app.run_mode.get.assert_not_called()
        app.min_coverage.get.assert_not_called()

    def test_every_callback_schedules_its_main_thread_helper(self, tmp_path):
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

        zero_delay = [entry for entry in self._scheduled(app) if entry[0] == 0]
        callbacks = [entry[1] for entry in zero_delay]
        assert callbacks == [
            app._update_phase1_ui,
            app._append_phase2_text,
            app._show_coverage_fail,
            app._show_complete,
            app._show_error,
        ]
        assert zero_delay[0][2:] == (1, 3, 1, 0, "display")
        assert zero_delay[1][2:] == ("display2",)
        assert zero_delay[4][2:] == ("boom",)
        # Nothing was written straight from the worker callback.
        app.progress.__setitem__.assert_not_called()
        app.file_listbox.insert.assert_not_called()
        app.summary_label.config.assert_not_called()
        app.notebook.select.assert_not_called()
        app.start_btn.config.assert_not_called()

    def test_log_write_failure_schedules_the_dialog(self, tmp_path):
        app, _, _ = _make_shell_app(None)
        app._log_path = str(tmp_path / "missing_dir" / "genre_log.txt")
        app.error_logger = MagicMock()

        app._write_log(["line\n"])

        zero_delay = [entry for entry in self._scheduled(app) if entry[0] == 0]
        assert [entry[1] for entry in zero_delay] == [app._show_log_error]
        assert "Could not write log file" in zero_delay[0][2]


class TestRealWidgetMarshalling:
    """The after(0, ...) bridge against real Tk widgets.

    A per-test withdrawn Toplevel off the session-scoped shared root is used
    so nothing lasting past the test is interned on the shared root.
    """

    def test_scheduled_callback_updates_a_real_listbox(self, root):
        import tkinter as tk

        from album_genre_tagger.app import GenreConsolidatorApp

        top = tk.Toplevel(root)
        try:
            app = object.__new__(GenreConsolidatorApp)
            app.root = top
            app.file_listbox = tk.Listbox(top)

            app._on_phase2_progress("real widget line", "log")

            assert app.file_listbox.size() == 0  # deferred, not written yet
            top.update()
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
# User actions — _open_folder
# ---------------------------------------------------------------------------


class TestOpenFolder:
    """_open_folder opens the folder or shows an info dialog."""

    @patch("album_genre_tagger.app.messagebox")
    @patch("album_genre_tagger.app.platform_utils")
    @patch("album_genre_tagger.app.os.path.exists", return_value=True)
    def test_existing_folder_opens_path(self, mock_exists, mock_pu, mock_mb):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/music/dir"

        app._open_folder()

        mock_pu.open_path.assert_called_once_with("/some/music/dir")
        mock_mb.showinfo.assert_not_called()

    @patch("album_genre_tagger.app.messagebox")
    @patch("album_genre_tagger.app.platform_utils")
    @patch("album_genre_tagger.app.os.path.exists", return_value=False)
    def test_missing_folder_shows_info(self, mock_exists, mock_pu, mock_mb):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/nonexistent"

        app._open_folder()

        mock_pu.open_path.assert_not_called()
        mock_mb.showinfo.assert_called_once_with(
            "Folder", "Source folder not available."
        )

    @patch("album_genre_tagger.app.messagebox")
    @patch("album_genre_tagger.app.platform_utils")
    def test_empty_path_shows_info(self, mock_pu, mock_mb):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = ""

        app._open_folder()

        mock_pu.open_path.assert_not_called()
        mock_mb.showinfo.assert_called_once_with(
            "Folder", "Source folder not available."
        )

    @patch("album_genre_tagger.app.messagebox")
    @patch("album_genre_tagger.app.platform_utils")
    @patch("album_genre_tagger.app.os.path.exists", return_value=True)
    def test_existing_folder_with_spaces(self, mock_exists, mock_pu, mock_mb):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "C:\\My Music\\Collection"

        app._open_folder()

        mock_pu.open_path.assert_called_once_with("C:\\My Music\\Collection")


# ---------------------------------------------------------------------------
# Validation in start_processing
# ---------------------------------------------------------------------------


class TestStartProcessingValidation:
    """start_processing guards against bad input before spawning a thread."""

    @patch("album_genre_tagger.app.messagebox")
    def test_empty_folder_shows_warning_and_returns(self, mock_mb):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = ""

        app.start_processing()

        mock_mb.showwarning.assert_called_once_with(
            "Warning", "Please select a music directory first."
        )
        app.start_btn.config.assert_not_called()

    @patch("album_genre_tagger.app.os.path.isdir", return_value=False)
    @patch("album_genre_tagger.app.messagebox")
    def test_nonexistent_directory_shows_error_and_returns(self, mock_mb, mock_isdir):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/not/a/dir"

        app.start_processing()

        mock_mb.showerror.assert_called_once_with(
            "Error", "Selected path is not a valid directory."
        )
        app.start_btn.config.assert_not_called()

    @patch("album_genre_tagger.app.threading.Thread")
    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_negative_coverage_shows_error(self, mock_mb, mock_isdir, mock_thread):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.min_coverage.get.return_value = -5
        app.overall_status = MagicMock()

        app.start_processing()

        mock_mb.showerror.assert_called_once_with(
            "Error", "Coverage percentage must be between 0 and 100."
        )
        mock_thread.assert_not_called()

    @patch("album_genre_tagger.app.threading.Thread")
    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_coverage_over_100_shows_error(self, mock_mb, mock_isdir, mock_thread):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.min_coverage.get.return_value = 150
        app.overall_status = MagicMock()

        app.start_processing()

        mock_mb.showerror.assert_called_once_with(
            "Error", "Coverage percentage must be between 0 and 100."
        )
        mock_thread.assert_not_called()

    @patch("album_genre_tagger.app.threading.Thread")
    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_zero_coverage_is_valid(self, mock_mb, mock_isdir, mock_thread):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.run_mode.get.return_value = "Dry Run"
        app.min_coverage.get.return_value = 0
        app.overall_status = MagicMock()

        app.start_processing()

        mock_mb.showerror.assert_not_called()
        mock_thread.assert_called_once()

    @patch("album_genre_tagger.app.threading.Thread")
    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_100_coverage_is_valid(self, mock_mb, mock_isdir, mock_thread):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.run_mode.get.return_value = "Dry Run"
        app.min_coverage.get.return_value = 100
        app.overall_status = MagicMock()

        app.start_processing()

        mock_mb.showerror.assert_not_called()
        mock_thread.assert_called_once()

    @patch("album_genre_tagger.app.threading.Thread")
    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_success_disables_btn_clears_listbox_switches_tab(
        self, mock_mb, mock_isdir, mock_thread
    ):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.run_mode.get.return_value = "Live Update"
        app.min_coverage.get.return_value = 60
        app.overall_status = MagicMock()

        app.start_processing()

        app.start_btn.config.assert_called_once_with(state="disabled")
        app.file_listbox.delete.assert_called_once_with(0, tk.END)
        app.notebook.select.assert_called_once_with(app._tab_processing)
        app.overall_status.set.assert_called_once_with("Processing genres...")

    @patch("album_genre_tagger.app.threading.Thread")
    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_success_snapshots_vars_and_starts_thread(
        self, mock_mb, mock_isdir, mock_thread
    ):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/my/music"
        app.run_mode.get.return_value = "Dry Run"
        app.min_coverage.get.return_value = 75
        app.overall_status = MagicMock()

        app.start_processing()

        assert app._dir_path == "/my/music"
        assert app._is_dry_run is True
        assert app._min_coverage == 75
        assert app._log_path == os.path.join("/my/music", "AlbumGenre_Tagger_Log.txt")
        mock_thread.assert_called_once_with(target=app._run, daemon=True)
        mock_thread.return_value.start.assert_called_once()

    @patch("album_genre_tagger.app.threading.Thread")
    @patch("album_genre_tagger.app.os.path.isdir", return_value=True)
    @patch("album_genre_tagger.app.messagebox")
    def test_live_mode_is_not_dry_run(self, mock_mb, mock_isdir, mock_thread):
        app, _, _ = _make_shell_app(None)
        app.folder_path.get.return_value = "/some/dir"
        app.run_mode.get.return_value = "Live Update"
        app.min_coverage.get.return_value = 50
        app.overall_status = MagicMock()

        app.start_processing()

        assert app._is_dry_run is False


# ---------------------------------------------------------------------------
# Main-thread helpers
# ---------------------------------------------------------------------------


class TestUpdatePhase1Ui:
    """_update_phase1_ui updates progress bar, stats label, and listbox."""

    def test_sets_progress_and_inserts_display_text(self):
        app, _, _ = _make_shell_app(None)

        app._update_phase1_ui(3, 10, 2, 1, "Track 03 - Artist - Title")

        assert app.progress.__setitem__.call_args_list[0].args == ("maximum", 11)
        assert app.progress.__setitem__.call_args_list[1].args == ("value", 3)
        app.stats_label.config.assert_called_once_with(
            text="Processed: 3 | With Genre: 2 | Errors: 1"
        )
        app.file_listbox.insert.assert_called_once_with(
            tk.END, "Track 03 - Artist - Title"
        )
        app.file_listbox.see.assert_called_once_with(tk.END)
        app.root.update_idletasks.assert_called_once()

    def test_first_file_zero_errors(self):
        app, _, _ = _make_shell_app(None)

        app._update_phase1_ui(1, 5, 0, 0, "Track 01")

        app.stats_label.config.assert_called_once_with(
            text="Processed: 1 | With Genre: 0 | Errors: 0"
        )

    def test_total_plus_one_reserves_write_phase(self):
        app, _, _ = _make_shell_app(None)

        app._update_phase1_ui(0, 20, 0, 0, "header")

        assert app.progress.__setitem__.call_args_list[0].args == ("maximum", 21)


class TestShowCoverageFail:
    """_show_coverage_fail displays failure summary and re-enables start."""

    def test_displays_failure_summary(self):
        app, _, _ = _make_shell_app(None)

        app._show_coverage_fail(
            total=10,
            files_with_genre=3,
            coverage_pct=30.0,
            min_coverage=50,
            duration_secs=65.5,
        )

        app.time_label.config.assert_called_once_with(text="Total Time: 01:05")
        app.summary_label.config.assert_called_once()
        summary_text = app.summary_label.config.call_args.kwargs["text"]
        assert "Total: 10 files" in summary_text
        assert "With TITLEGENRE: 3 (30.0%)" in summary_text
        assert "Required: 50%" in summary_text
        assert "FAILED" in summary_text
        app.completion_label.config.assert_called_once_with(
            text="Coverage Check Failed!"
        )
        app.genre_label.config.assert_called_once_with(text="")
        app.notebook.select.assert_called_once_with(app._tab_results)
        app.start_btn.config.assert_called_once_with(state="normal")

    def test_auto_end_schedules_destroy(self):
        app, _, _ = _make_shell_app(None)
        app.auto_end = True

        app._show_coverage_fail(5, 1, 20.0, 50, 1.0)

        destroy_calls = [
            c for c in app.root.after.call_args_list if c.args[1] == app.root.destroy
        ]
        assert len(destroy_calls) == 1
        assert destroy_calls[0].args[0] == 2000

    def test_no_auto_end_does_not_schedule_destroy(self):
        app, _, _ = _make_shell_app(None)
        app.auto_end = False

        app._show_coverage_fail(5, 1, 20.0, 50, 1.0)

        destroy_calls = [
            c for c in app.root.after.call_args_list if c.args[1] == app.root.destroy
        ]
        assert len(destroy_calls) == 0


class TestShowComplete:
    """_show_complete displays the final summary."""

    def test_dry_run_shows_analysis_complete(self):
        app, _, _ = _make_shell_app(None)
        app._is_dry_run = True

        app._show_complete(
            total=8,
            files_with_genre=8,
            coverage_pct=100.0,
            unique_genres=["Rock", "Pop"],
            album_genre_string="Rock; Pop",
            write_count=8,
            write_errors=0,
            read_errors=0,
            duration_secs=122.0,
            log_entries=["line\n"],
        )

        app.time_label.config.assert_called_once_with(text="Total Time: 02:02")
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
        app.notebook.select.assert_called_once_with(app._tab_results)
        app.start_btn.config.assert_called_once_with(state="normal")

    def test_live_mode_shows_consolidation_complete(self):
        app, _, _ = _make_shell_app(None)
        app._is_dry_run = False

        app._show_complete(
            total=5,
            files_with_genre=5,
            coverage_pct=100.0,
            unique_genres=["Jazz"],
            album_genre_string="Jazz",
            write_count=5,
            write_errors=1,
            read_errors=0,
            duration_secs=5.0,
            log_entries=[],
        )

        app.completion_label.config.assert_called_once_with(
            text="Genre Consolidation Complete!"
        )
        summary_text = app.summary_label.config.call_args.kwargs["text"]
        assert "would be" not in summary_text
        assert "Errors: 1" in summary_text

    def test_auto_end_schedules_destroy_and_writes_log(self, tmp_path):
        app, _, _ = _make_shell_app(None)
        app.auto_end = True
        app._is_dry_run = True
        app._log_path = str(tmp_path / "log.txt")
        app.error_logger = MagicMock()

        log = ["entry\n"]
        app._show_complete(
            total=2,
            files_with_genre=2,
            coverage_pct=100.0,
            unique_genres=["Pop"],
            album_genre_string="Pop",
            write_count=2,
            write_errors=0,
            read_errors=0,
            duration_secs=1.0,
            log_entries=log,
        )

        destroy_calls = [
            c for c in app.root.after.call_args_list if c.args[1] == app.root.destroy
        ]
        assert len(destroy_calls) == 1
        assert destroy_calls[0].args[0] == 2000
        app.root.update_idletasks.assert_called_once()
        # The auto-end block appends to the log list.
        assert any("Auto End" in entry for entry in log)

    def test_no_auto_end_does_not_schedule_destroy(self):
        app, _, _ = _make_shell_app(None)
        app.auto_end = False
        app._is_dry_run = True

        app._show_complete(
            total=2,
            files_with_genre=2,
            coverage_pct=100.0,
            unique_genres=[],
            album_genre_string="",
            write_count=0,
            write_errors=0,
            read_errors=0,
            duration_secs=0.5,
            log_entries=[],
        )

        destroy_calls = [
            c for c in app.root.after.call_args_list if c.args[1] == app.root.destroy
        ]
        assert len(destroy_calls) == 0

    def test_progress_value_set_to_total_plus_one(self):
        app, _, _ = _make_shell_app(None)
        app._is_dry_run = True

        app._show_complete(
            total=12,
            files_with_genre=12,
            coverage_pct=100.0,
            unique_genres=["Rock"],
            album_genre_string="Rock",
            write_count=12,
            write_errors=0,
            read_errors=0,
            duration_secs=10.0,
            log_entries=[],
        )

        assert app.progress.__setitem__.call_args.args == ("value", 13)

    def test_errors_summed_read_and_write(self):
        app, _, _ = _make_shell_app(None)
        app._is_dry_run = True

        app._show_complete(
            total=10,
            files_with_genre=10,
            coverage_pct=100.0,
            unique_genres=[],
            album_genre_string="",
            write_count=10,
            write_errors=3,
            read_errors=2,
            duration_secs=1.0,
            log_entries=[],
        )

        summary_text = app.summary_label.config.call_args.kwargs["text"]
        assert "Errors: 5" in summary_text


class TestShowError:
    """_show_error shows an error dialog and re-enables the start button."""

    @patch("album_genre_tagger.app.messagebox")
    def test_shows_error_and_reenables_start(self, mock_mb):
        app, _, _ = _make_shell_app(None)

        app._show_error("Something went wrong")

        mock_mb.showerror.assert_called_once_with("Error", "Something went wrong")
        app.start_btn.config.assert_called_once_with(state="normal")

    @patch("album_genre_tagger.app.messagebox")
    def test_empty_message(self, mock_mb):
        app, _, _ = _make_shell_app(None)

        app._show_error("")

        mock_mb.showerror.assert_called_once_with("Error", "")


class TestResetProgressUi:
    """_reset_progress_ui zeros the progress bar and inserts the header."""

    def test_resets_and_inserts_header(self):
        app, _, _ = _make_shell_app(None)

        app._reset_progress_ui()

        assert app.progress.__setitem__.call_args.args == ("value", 0)
        app.file_listbox.insert.assert_called_once_with(
            tk.END, "=== PHASE 1: READING TITLEGENRE TAGS ==="
        )
        app.root.update_idletasks.assert_called_once()


class TestShowLogError:
    """_show_log_error shows an error dialog for log write failures."""

    @patch("album_genre_tagger.app.messagebox")
    def test_shows_error_dialog(self, mock_mb):
        app, _, _ = _make_shell_app(None)

        app._show_log_error("Could not write log file:\nPermission denied")

        mock_mb.showerror.assert_called_once_with(
            "Error", "Could not write log file:\nPermission denied"
        )

    @patch("album_genre_tagger.app.messagebox")
    def test_long_message_passed_through(self, mock_mb):
        app, _, _ = _make_shell_app(None)
        long_msg = "Could not write log file:\n" + "x" * 500

        app._show_log_error(long_msg)

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
