"""
Tests for album_genre_tagger.app — GenreConsolidatorApp orchestrator.

Focus: CLI-driven Run Controls mirroring and handler wiring, using the
object.__new__ + MagicMock shell pattern (no real display required).
"""

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
