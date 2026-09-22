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
        app.run_mode.get.return_value = "Dry Run"

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
        app.folder_path = MagicMock()
        app.folder_path.get.return_value = str(tmp_path)
        app.run_mode = MagicMock()
        app.run_mode.get.return_value = "Dry Run"
        app.min_coverage = MagicMock()
        app.min_coverage.get.return_value = 50
        app.progress = MagicMock()
        app.file_listbox = MagicMock()

        mock_active_batch = MagicMock()
        with (
            patch("album_genre_tagger.app.active_batch", mock_active_batch),
            patch("album_genre_tagger.app.consolidator.run_analysis") as mock_run,
        ):
            app._run()

        mock_active_batch.assert_called_once_with("album_genre_tagger", "tag_edit")
        mock_run.assert_called_once()
        assert mock_run.call_args.kwargs["dir_path"] == str(tmp_path)
