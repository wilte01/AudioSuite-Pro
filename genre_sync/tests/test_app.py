"""
Tests for genre_sync.app — GenreSetterApp orchestrator.

Strategy: mock all tkinter / shared-library dependencies so we
exercise the wiring and callback logic without a real GUI.
Changed in 1.4.0: the slot grid is sized from DEFAULT_MAX_WORKERS.
Changed in 2.0.0: adds the ``TestCompletionSeam`` cases driving
``run_processing`` into the completion handler (PLAN D117).
"""

from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


class TestGenreSetterAppInit:
    def test_constructor_sets_default_state(self, mock_tk_app):
        assert mock_tk_app._log_path == ""
        assert mock_tk_app._dir_path == ""
        assert mock_tk_app.auto_end is False

    def test_constructor_creates_slot_pool(self, mock_tk_app):
        from audio_suite_shared.constants import DEFAULT_MAX_WORKERS

        assert len(mock_tk_app.slot_vars) == DEFAULT_MAX_WORKERS
        assert mock_tk_app.slot_queue.qsize() == DEFAULT_MAX_WORKERS

    def test_constructor_initializes_tk_vars(self, mock_tk_app):
        assert mock_tk_app.run_mode.get() == "Dry Run"

    def test_constructor_loads_last_directory(self):
        import audio_suite_shared.ui_common

        def mock_stringvar(value=None, master=None, name=None):
            sv = MagicMock()
            sv.get.return_value = value if value is not None else ""
            sv_set = None

            def sv_setter(val):
                nonlocal sv_set
                sv_set = val
                sv.get.return_value = val

            sv.set = sv_setter
            return sv

        with (
            patch("genre_sync.app.tk") as mock_tk,
            patch("genre_sync.app.ttk"),
            patch("genre_sync.app.bootstrap_tool_app") as mock_bootstrap,
            patch("genre_sync.app.suite_config") as mock_config,
            patch("genre_sync.app.cli_args") as mock_cli,
            patch("genre_sync.app.messagebox"),
            patch("genre_sync.app.UniversalCLIHandler"),
            patch("genre_sync.app.logger"),
            patch.object(audio_suite_shared.ui_common, "tk", mock_tk),
        ):
            mock_tk.StringVar = mock_stringvar
            mock_tk.Tk.return_value = MagicMock()
            mock_tk.Frame.return_value = MagicMock()
            mock_tk.Label.return_value = MagicMock()
            mock_tk.Button.return_value = MagicMock()
            mock_tk.Entry.return_value = MagicMock()
            mock_tk.Listbox.return_value = MagicMock()
            mock_tk.ttk = MagicMock()
            mock_tk.END = "end"

            mock_bootstrap.return_value = (MagicMock(), MagicMock())
            mock_config.load_last_directory.return_value = "/previous/dir"
            mock_cli.parse.return_value = MagicMock(folder_path=None)

            from genre_sync.app import GenreSetterApp

            app = GenreSetterApp(MagicMock())
            assert app.folder_path.get() == "/previous/dir"
            mock_config.load_last_directory.assert_called_once()


class TestGenreSetterAppStartProcessing:
    def test_start_processing_without_folder_shows_warning(self, mock_tk_app):
        mock_tk_app.folder_path.set("")
        with patch("genre_sync.app.messagebox") as mock_msg:
            mock_tk_app.start_processing()
            mock_msg.showwarning.assert_called_once()

    def test_start_processing_with_invalid_folder_shows_error(self, mock_tk_app):
        mock_tk_app.folder_path.set("/nonexistent/path/xyz123")
        with patch("genre_sync.app.messagebox") as mock_msg:
            mock_tk_app.start_processing()
            mock_msg.showerror.assert_called_once()

    def test_start_processing_valid_folder_starts_thread(self, mock_tk_app, tmp_path):
        d = tmp_path / "music"
        d.mkdir()
        mock_tk_app.folder_path.set(str(d))
        with patch("genre_sync.app.threading.Thread") as mock_thread:
            mock_tk_app.start_processing()
            mock_thread.assert_called_once()
            mock_thread.return_value.start.assert_called_once()

    def test_start_processing_disables_start_button(self, mock_tk_app, tmp_path):
        d = tmp_path / "music"
        d.mkdir()
        mock_tk_app.folder_path.set(str(d))
        with patch("genre_sync.app.threading.Thread"):
            mock_tk_app.start_processing()
            mock_tk_app.start_btn.config.assert_called()


class TestGenreSetterAppCallbackSignatures:
    """Verify every callback signature matches between app.py and
    core/file_processor.py to prevent kwarg mismatch bugs."""

    def test_on_complete_accepts_processed_kwarg(self, mock_tk_app, tmp_path):
        """_on_complete must accept 'processed' which run_processing() passes."""
        mock_tk_app._dir_path = str(tmp_path)
        mock_tk_app._log_path = str(tmp_path / "genre_sync_log.txt")
        mock_tk_app.run_mode.set("Dry Run")
        with patch("genre_sync.app.log_builder.build_log_lines") as mock_build:
            mock_build.return_value = []
            mock_tk_app._on_complete(
                total=10,
                processed=10,  # extra kwarg from file_processor.run_processing()
                updated=5,
                skipped=3,
                no_genre=2,
                errors=0,
                duration_secs=30.0,
                log_entries=[],  # extra kwarg from file_processor.run_processing()
                log_updated=[],
                log_skipped=[],
                log_no_genre=[],
                log_errors=[],
            )

    def test_on_complete_rejects_nothing(self, mock_tk_app, tmp_path):
        """_on_complete must tolerate any extra kwargs via **kwargs."""
        mock_tk_app._dir_path = str(tmp_path)
        mock_tk_app._log_path = str(tmp_path / "genre_sync_log.txt")
        mock_tk_app.run_mode.set("Dry Run")
        with patch("genre_sync.app.log_builder.build_log_lines") as mock_build:
            mock_build.return_value = []
            mock_tk_app._on_complete(
                total=1,
                updated=1,
                skipped=0,
                no_genre=0,
                errors=0,
                duration_secs=1.0,
                log_updated=[],
                log_skipped=[],
                log_no_genre=[],
                log_errors=[],
                processed=1,  # must be tolerated
                log_entries=[],  # must be tolerated
                unexpected_extra="should not crash",  # must be tolerated
            )


class TestGenreSetterAppCallbacks:
    def test_on_progress_updates_progress_bar(self, mock_tk_app):
        mock_tk_app._on_progress(
            processed=5,
            total=10,
            updated=3,
            skipped=1,
            no_genre=1,
            errors=0,
            display_text="[DRY_RUN] track.mp3 \u2192 Would set: Rock",
        )
        assert mock_tk_app.progress.__setitem__.called

    def test_on_progress_inserts_display_text(self, mock_tk_app):
        mock_tk_app._on_progress(
            processed=1,
            total=1,
            updated=1,
            skipped=0,
            no_genre=0,
            errors=0,
            display_text="[UPDATED] track.mp3 \u2192 Set to: Rock",
        )
        mock_tk_app.file_listbox.insert.assert_called_once()

    def test_on_progress_updates_stats_label(self, mock_tk_app):
        mock_tk_app._on_progress(
            processed=3,
            total=5,
            updated=2,
            skipped=1,
            no_genre=0,
            errors=0,
            display_text="test",
        )
        mock_tk_app.stats_label.config.assert_called()

    def test_on_complete_writes_log_and_updates_ui(self, mock_tk_app, tmp_path):
        mock_tk_app._dir_path = str(tmp_path)
        mock_tk_app._log_path = str(tmp_path / "genre_sync_log.txt")
        mock_tk_app.run_mode.set("Dry Run")

        with patch("genre_sync.app.log_builder.build_log_lines") as mock_build:
            mock_build.return_value = ["line1\n", "line2\n"]
            mock_tk_app._on_complete(
                total=10,
                updated=5,
                skipped=3,
                no_genre=2,
                errors=0,
                duration_secs=30.0,
                log_updated=[],
                log_skipped=[],
                log_no_genre=[],
                log_errors=[],
            )
            log_content = (tmp_path / "genre_sync_log.txt").read_text(encoding="utf-8")
            assert log_content == "line1\nline2\n"
            mock_tk_app.completion_label.config.assert_called()

    def test_on_complete_with_auto_end_logs_append_and_schedules_close(
        self, mock_tk_app, tmp_path
    ):
        mock_tk_app._dir_path = str(tmp_path)
        mock_tk_app._log_path = str(tmp_path / "genre_sync_log.txt")
        mock_tk_app.run_mode.set("Dry Run")
        mock_tk_app.auto_end = True

        with patch("genre_sync.app.log_builder.build_log_lines") as mock_build:
            mock_build.return_value = ["line1\n"]
            mock_tk_app._on_complete(
                total=1,
                updated=1,
                skipped=0,
                no_genre=0,
                errors=0,
                duration_secs=1.0,
                log_updated=[],
                log_skipped=[],
                log_no_genre=[],
                log_errors=[],
            )
            log_content = (tmp_path / "genre_sync_log.txt").read_text(encoding="utf-8")
            assert "Auto End" in log_content
            mock_tk_app.root.after.assert_called()

    def test_on_complete_handles_log_write_error(self, mock_tk_app):
        mock_tk_app._log_path = "/nonexistent/folder/log.txt"
        mock_tk_app.run_mode.set("Dry Run")

        with patch("genre_sync.app.log_builder.build_log_lines") as mock_build:
            mock_build.return_value = ["line1\n"]
            with patch("genre_sync.app.messagebox") as mock_msg:
                mock_tk_app._on_complete(
                    total=1,
                    updated=1,
                    skipped=0,
                    no_genre=0,
                    errors=0,
                    duration_secs=1.0,
                    log_updated=[],
                    log_skipped=[],
                    log_no_genre=[],
                    log_errors=[],
                )
                mock_msg.showerror.assert_called_once()

    def test_on_error_shows_error_and_reenables_button(self, mock_tk_app):
        with patch("genre_sync.app.messagebox") as mock_msg:
            mock_tk_app._on_error("Something went wrong")
            mock_msg.showerror.assert_called_once()
            mock_tk_app.start_btn.config.assert_called()


class TestGenreSetterAppApplyCliArgs:
    def test_apply_cli_args_delegates_to_universal_handler(self, mock_tk_app):
        with patch("genre_sync.app.cli_args") as mock_cli:
            parsed = MagicMock(folder_path="/cli/music")
            mock_cli.parse.return_value = parsed
            with patch("genre_sync.app.UniversalCLIHandler") as mock_handler_cls:
                mock_handler = MagicMock()
                mock_handler.apply_cli_args.return_value = False
                mock_handler_cls.return_value = mock_handler
                mock_tk_app._apply_cli_args()
                mock_handler_cls.assert_called_once_with(mock_tk_app)
                mock_handler.apply_cli_args.assert_called_once_with(
                    parsed,
                    folder_var=mock_tk_app.folder_path,
                    auto_start_func=mock_tk_app.start_processing,
                )

    def test_apply_cli_args_triggers_auto_start(self, mock_tk_app):
        with patch("genre_sync.app.cli_args") as mock_cli:
            parsed = MagicMock(folder_path="/cli/music")
            mock_cli.parse.return_value = parsed
            with patch("genre_sync.app.UniversalCLIHandler") as mock_handler_cls:
                mock_handler = MagicMock()
                mock_handler.apply_cli_args.return_value = True
                mock_handler_cls.return_value = mock_handler
                with patch.object(mock_tk_app.root, "after") as mock_after:
                    mock_tk_app._apply_cli_args()
                    mock_after.assert_called_once_with(
                        1500, mock_tk_app.start_processing
                    )


class TestGenreSetterAppActions:
    def test_browse_folder_calls_helper(self, mock_tk_app):
        mock_tk_app._browse_folder()
        mock_tk_app._browse_folder_standard.assert_called_once_with(
            title="Select Music Directory",
            path_variable=mock_tk_app.folder_path,
            save_last_dir=True,
        )

    def test_open_folder_with_valid_path(self, mock_tk_app):
        mock_tk_app.folder_path.set("/some/valid/path")
        with patch("genre_sync.app.os.path.exists", return_value=True):
            with patch("genre_sync.app.platform_utils.open_path") as mock_open:
                mock_tk_app._open_folder()
                mock_open.assert_called_once_with("/some/valid/path")

    def test_open_folder_with_invalid_path_shows_info(self, mock_tk_app):
        mock_tk_app.folder_path.set("/invalid/path")
        with patch("genre_sync.app.os.path.exists", return_value=False):
            with patch("genre_sync.app.messagebox") as mock_msg:
                mock_tk_app._open_folder()
                mock_msg.showinfo.assert_called_once()

    def test_open_help_calls_helper(self, mock_tk_app):
        mock_tk_app._open_help()
        mock_tk_app._open_help_standard.assert_called_once_with(
            "Genre_Sync_User_Guide.docx"
        )

    def test_open_log_calls_helper(self, mock_tk_app):
        mock_tk_app._open_log()
        mock_tk_app._open_log_standard.assert_called_once()

    def test_reset_ui_clears_list_and_resets_progress(self, mock_tk_app):
        mock_tk_app._reset_ui()
        mock_tk_app.file_listbox.delete.assert_called_with(0, "end")


def _make_shell_app():
    """Build a GenreSetterApp shell with mock attributes."""
    from genre_sync.app import GenreSetterApp

    app = object.__new__(GenreSetterApp)
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

    def _run(self, parsed, driven=True):
        from genre_sync.utils.cli_args import was_launched_from_driver  # noqa: F401

        app, handler, handler_cls = _make_shell_app()
        with (
            patch("genre_sync.utils.cli_args.parse", return_value=parsed),
            patch(
                "genre_sync.utils.cli_args.was_launched_from_driver",
                return_value=driven,
            ),
            patch("genre_sync.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()
        return app, handler

    def test_inherited_values_applied_to_panel_vars(self):
        from genre_sync.utils.cli_args import GenreSyncArgs

        parsed = GenreSyncArgs(
            folder_path="D:/Music",
            live_mode=True,
            auto_start=True,
            auto_end=True,
            clear_logs=True,
            parallel_run=True,
        )
        app, _ = self._run(parsed)
        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_handler_invoked_with_folder_and_auto_start(self):
        from genre_sync.utils.cli_args import GenreSyncArgs

        parsed = GenreSyncArgs(folder_path="D:/Music")
        app, handler = self._run(parsed)
        handler.apply_cli_args.assert_called_once_with(
            parsed, folder_var=app.folder_path, auto_start_func=app.start_processing
        )

    def test_auto_start_schedules_processing(self):
        from genre_sync.utils.cli_args import GenreSyncArgs

        app, _, handler_cls = _make_shell_app()
        handler_cls.return_value.apply_cli_args.return_value = True
        with (
            patch(
                "genre_sync.utils.cli_args.parse",
                return_value=GenreSyncArgs(folder_path="D:/Music"),
            ),
            patch(
                "genre_sync.utils.cli_args.was_launched_from_driver",
                return_value=True,
            ),
            patch("genre_sync.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        after_delays = [call.args[0] for call in app.root.after.call_args_list]
        assert 1500 in after_delays


class TestApplyCliArgsStandalone:
    """Standalone start: defaults applied, no handler/after scheduling."""

    def test_defaults_applied_to_panel_vars(self):
        from genre_sync.utils.cli_args import GenreSyncArgs

        app, _, handler_cls = _make_shell_app()
        with (
            patch(
                "genre_sync.utils.cli_args.parse",
                return_value=GenreSyncArgs(),
            ),
            patch(
                "genre_sync.utils.cli_args.was_launched_from_driver",
                return_value=False,
            ),
            patch("genre_sync.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.auto_start_var.set.assert_called_once_with(False)
        app.auto_end_var.set.assert_called_once_with(False)
        app.clear_logs_var.set.assert_called_once_with(False)
        app.parallel_var.set.assert_called_once_with(False)

    def test_no_handler_or_scheduling_without_folder(self):
        from genre_sync.utils.cli_args import GenreSyncArgs

        app, handler, handler_cls = _make_shell_app()
        with (
            patch(
                "genre_sync.utils.cli_args.parse",
                return_value=GenreSyncArgs(),
            ),
            patch(
                "genre_sync.utils.cli_args.was_launched_from_driver",
                return_value=False,
            ),
            patch("genre_sync.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        handler.apply_cli_args.assert_not_called()
        app.root.after.assert_not_called()


# ---------------------------------------------------------------------------
# Completion seam: the processor payload must reach the handler _run binds and
# land in the report the run writes.
# ---------------------------------------------------------------------------


def _completion_shell(tmp_path: Path) -> Any:
    """Shell with only what the completion path touches."""
    from genre_sync.app import GenreSetterApp

    app = object.__new__(GenreSetterApp)
    app.root = MagicMock()
    app._log_path = str(tmp_path / "genre_dry_run_log.txt")
    app.run_mode = MagicMock()
    app.run_mode.get.return_value = "Dry Run"
    app.auto_end = False
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.notebook = MagicMock()
    app._tab_results = MagicMock()
    app.start_btn = MagicMock()
    return app


class TestCompletionSeam:
    """``run_processing`` publishes into the handler ``_run`` binds."""

    @staticmethod
    def _fake_process_single_file(
        name: str,
        dir_path: str,
        is_dry_run: bool,
        slot_vars: Any,
        slot_queue: Any,
        lock: Any,
        on_progress: Any,
    ) -> None:
        """Stand in for the per-file pass, one outcome per file."""
        outcomes = {
            "a.mp3": {"updated": 1, "skipped": 0, "no_genre": 0, "errors": 0},
            "b.mp3": {"updated": 0, "skipped": 1, "no_genre": 0, "errors": 0},
            "c.mp3": {"updated": 0, "skipped": 0, "no_genre": 1, "errors": 0},
            "d.mp3": {"updated": 0, "skipped": 0, "no_genre": 0, "errors": 1},
        }
        outcome = outcomes[name]
        on_progress(
            n_updated=outcome["updated"],
            n_skipped=outcome["skipped"],
            n_no_genre=outcome["no_genre"],
            n_errors=outcome["errors"],
            display_text=name,
            log_updated=f"{name}\n" if outcome["updated"] else "",
            log_skipped=f"{name}\n" if outcome["skipped"] else "",
            log_no_genre=f"{name}\n" if outcome["no_genre"] else "",
            log_errors=f"{name}\n" if outcome["errors"] else "",
        )

    def test_the_real_payload_is_written(self, tmp_path: Path) -> None:
        """Every published count reaches the report the handler writes."""
        from genre_sync.core import file_processor

        for name in ("a.mp3", "b.mp3", "c.mp3", "d.mp3"):
            (tmp_path / name).write_bytes(b"")
        app = _completion_shell(tmp_path)

        with patch.object(
            file_processor,
            "process_single_file",
            side_effect=self._fake_process_single_file,
        ):
            file_processor.run_processing(
                dir_path=str(tmp_path),
                is_dry_run=True,
                slot_vars=[MagicMock()],
                slot_queue=Queue(),
                on_progress=MagicMock(),
                on_complete=app._on_complete,
                on_error=MagicMock(),
            )

        report = (tmp_path / "genre_dry_run_log.txt").read_text(encoding="utf-8")
        assert "Total files: 4" in report
        assert "Would update: 1" in report
        assert "Skipped (already correct): 1" in report
        assert "No genre fields: 1" in report
        assert "Errors: 1" in report

    @pytest.mark.parametrize(
        "field",
        [
            "total",
            "updated",
            "skipped",
            "no_genre",
            "errors",
            "duration_secs",
            "log_updated",
            "log_skipped",
            "log_no_genre",
            "log_errors",
        ],
    )
    def test_a_missing_field_raises_and_writes_no_report(
        self, tmp_path: Path, field: str
    ) -> None:
        """A dropped field names itself and leaves no report behind."""
        app = _completion_shell(tmp_path)
        payload: dict[str, Any] = {
            "total": 4,
            "updated": 1,
            "skipped": 1,
            "no_genre": 1,
            "errors": 1,
            "duration_secs": 1.0,
            "log_updated": ["a.mp3\n"],
            "log_skipped": ["b.mp3\n"],
            "log_no_genre": ["c.mp3\n"],
            "log_errors": ["d.mp3\n"],
        }
        payload.pop(field)

        with pytest.raises(TypeError) as caught:
            app._on_complete(**payload)

        assert field in str(caught.value)
        assert not (tmp_path / "genre_dry_run_log.txt").exists()
