"""
tests/test_app.py — unit tests for LyricsManagerApp (GUI orchestrator).

Uses the ``object.__new__`` + ``MagicMock`` shell pattern (no real Tk display).
Module-level dependencies are patched on the ``lyrics_manager.app`` namespace.
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from unittest.mock import MagicMock, patch

from audio_suite_shared.cli_dataclasses import LyricsArgs
from lyrics_manager.app import LyricsManagerApp


def _make_shell_app():
    """Build a LyricsManagerApp shell with mock attributes."""
    app = object.__new__(LyricsManagerApp)
    app.root = MagicMock()
    app.error_logger = MagicMock()
    app.folder_path = MagicMock()
    app.run_mode = MagicMock()
    app.provider = MagicMock()
    app.request_timeout = MagicMock()
    app.skip_existing = MagicMock()
    app.plain_fallback = MagicMock()
    app.parallel_mode = MagicMock()
    app.max_workers = MagicMock()
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()
    app.auto_end = False
    app._log_entries = []
    app._dir_path = ""
    app.overall_status = MagicMock()
    app.progress = MagicMock()
    app.stats_label = MagicMock()
    app.file_listbox = MagicMock()
    app.completion_label = MagicMock()
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.start_btn = MagicMock()
    app.notebook = MagicMock()
    app._tab_processing = MagicMock()
    app._tab_results = MagicMock()
    app._safe_slot_vars = MagicMock()
    app.slot_queue = MagicMock()
    return app


class TestApplyCliArgsDriven:
    def _run(self, parsed):
        app = _make_shell_app()
        handler = MagicMock()
        handler.apply_cli_args.return_value = False
        handler_cls = MagicMock(return_value=handler)
        with (
            patch("lyrics_manager.utils.cli_args.parse", return_value=parsed),
            patch("lyrics_manager.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()
        return app, handler, parsed

    def test_inherited_values_applied_to_panel_vars(self):
        app, _, _ = self._run(
            LyricsArgs(
                folder_path="D:/Music",
                live_mode=True,
                auto_start=True,
                auto_end=True,
                clear_logs=True,
                parallel_run=True,
                provider="lrclib",
                request_timeout=15.0,
                skip_existing=True,
                plain_fallback=True,
            )
        )
        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)
        app.provider.set.assert_called_once_with("lrclib")
        app.request_timeout.set.assert_called_once_with("15.0")
        app.skip_existing.set.assert_called_once_with(True)
        app.plain_fallback.set.assert_called_once_with(True)

    def test_lyrics_options_applied_before_early_return(self):
        """Tool options must be mirrored even with no folder argument."""
        app = _make_shell_app()
        handler = MagicMock()
        handler_cls = MagicMock(return_value=handler)
        parsed = LyricsArgs(
            provider="lrclib",
            request_timeout=20.0,
            skip_existing=False,
            plain_fallback=False,
        )
        with (
            patch("lyrics_manager.utils.cli_args.parse", return_value=parsed),
            patch("lyrics_manager.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()
        app.provider.set.assert_called_once_with("lrclib")
        app.request_timeout.set.assert_called_once_with("20.0")
        app.skip_existing.set.assert_called_once_with(False)
        app.plain_fallback.set.assert_called_once_with(False)
        handler.apply_cli_args.assert_not_called()

    def test_handler_invoked_with_folder_and_auto_start(self):
        app, handler, parsed = self._run(LyricsArgs(folder_path="D:/Music"))
        handler.apply_cli_args.assert_called_once_with(
            parsed,
            folder_var=app.folder_path,
            auto_start_func=app.start_processing,
        )

    def test_auto_start_schedules_processing(self):
        app = _make_shell_app()
        handler = MagicMock()
        handler.apply_cli_args.return_value = True
        handler_cls = MagicMock(return_value=handler)
        with (
            patch(
                "lyrics_manager.utils.cli_args.parse",
                return_value=LyricsArgs(folder_path="D:/Music"),
            ),
            patch("lyrics_manager.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()
        after_delays = [c.args[0] for c in app.root.after.call_args_list]
        assert 1500 in after_delays


class TestApplyCliArgsStandalone:
    def test_defaults_applied_to_panel_vars(self):
        app = _make_shell_app()
        handler_cls = MagicMock(return_value=MagicMock())
        with (
            patch("lyrics_manager.utils.cli_args.parse", return_value=LyricsArgs()),
            patch("lyrics_manager.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Dry Run")
        app.auto_start_var.set.assert_called_once_with(False)
        app.auto_end_var.set.assert_called_once_with(False)
        app.clear_logs_var.set.assert_called_once_with(False)
        app.parallel_var.set.assert_called_once_with(False)
        app.provider.set.assert_called_with("lrclib")

    def test_no_handler_or_scheduling_without_folder(self):
        app = _make_shell_app()
        handler = MagicMock()
        handler_cls = MagicMock(return_value=handler)
        with (
            patch("lyrics_manager.utils.cli_args.parse", return_value=LyricsArgs()),
            patch("lyrics_manager.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Dry Run")
        handler.apply_cli_args.assert_not_called()
        app.root.after.assert_not_called()


class TestSimpleDelegates:
    def test_browse_folder_delegates_to_mixin(self):
        app = _make_shell_app()
        app._browse_folder_standard = MagicMock()
        app._browse_folder()
        app._browse_folder_standard.assert_called_once_with(
            title="Select Music Directory",
            path_variable=app.folder_path,
            save_last_dir=True,
        )

    def test_open_help_uses_guide_name(self):
        app = _make_shell_app()
        app._open_help_standard = MagicMock()
        app._open_help()
        app._open_help_standard.assert_called_once_with(
            "Lyrics_Manager_User_Guide.docx"
        )

    def test_open_log_delegates_to_mixin(self):
        app = _make_shell_app()
        app._open_log_standard = MagicMock()
        app._open_log()
        app._open_log_standard.assert_called_once()

    def test_open_folder_opens_existing_path(self, tmp_path: Path):
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        with patch("lyrics_manager.app.platform_utils.open_path") as open_path:
            app._open_folder()
        open_path.assert_called_once_with(str(tmp_path))

    def test_open_folder_shows_info_when_missing(self):
        app = _make_shell_app()
        app.folder_path.get.return_value = ""
        with patch("lyrics_manager.app.messagebox.showinfo") as showinfo:
            app._open_folder()
        showinfo.assert_called_once()


class TestStartProcessingValidation:
    def test_no_folder_selected(self):
        app = _make_shell_app()
        app.folder_path.get.return_value = ""
        with patch("lyrics_manager.app.messagebox.showerror") as showerror:
            app.start_processing()
        assert "No Directory Selected" in str(showerror.call_args)

    def test_nonexistent_folder(self, tmp_path: Path):
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path / "missing")
        with patch("lyrics_manager.app.messagebox.showerror") as showerror:
            app.start_processing()
        assert "Directory Not Found" in str(showerror.call_args)

    def test_file_instead_of_directory(self, tmp_path: Path):
        f = tmp_path / "file.txt"
        f.write_text("x", encoding="utf-8")
        app = _make_shell_app()
        app.folder_path.get.return_value = str(f)
        with patch("lyrics_manager.app.messagebox.showerror") as showerror:
            app.start_processing()
        assert "Invalid Directory" in str(showerror.call_args)

    def test_no_audio_files(self, tmp_path: Path):
        (tmp_path / "readme.txt").write_text("x", encoding="utf-8")
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        with (
            patch("lyrics_manager.app.is_supported_format", return_value=False),
            patch("lyrics_manager.app.messagebox.showerror") as showerror,
        ):
            app.start_processing()
        assert "No Audio Files" in str(showerror.call_args)

    def test_empty_provider_rejected(self, tmp_path: Path):
        (tmp_path / "track.mp3").touch()
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        app.provider.get.return_value = ""
        with (
            patch("lyrics_manager.app.is_supported_format", return_value=True),
            patch("lyrics_manager.app.messagebox.showerror") as showerror,
        ):
            app.start_processing()
        assert "No Lyric Source" in str(showerror.call_args)

    def test_unknown_provider_rejected(self, tmp_path: Path):
        (tmp_path / "track.mp3").touch()
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        app.provider.get.return_value = "nope"
        from lyrics_manager.core.providers import LyricProviderError

        with (
            patch("lyrics_manager.app.is_supported_format", return_value=True),
            patch(
                "lyrics_manager.app.get_provider",
                side_effect=LyricProviderError("Unknown lyric provider: nope"),
            ),
            patch("lyrics_manager.app.messagebox.showerror") as showerror,
        ):
            app.start_processing()
        assert "Unknown Lyric Source" in str(showerror.call_args)

    def test_invalid_timeout(self, tmp_path: Path):
        (tmp_path / "track.mp3").touch()
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        app.provider.get.return_value = "lrclib"
        app.request_timeout.get.return_value = "abc"
        with (
            patch("lyrics_manager.app.is_supported_format", return_value=True),
            patch("lyrics_manager.app.get_provider"),
            patch("lyrics_manager.app.messagebox.showerror") as showerror,
        ):
            app.start_processing()
        assert "Invalid Timeout" in str(showerror.call_args)

    def test_nonpositive_timeout(self, tmp_path: Path):
        (tmp_path / "track.mp3").touch()
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        app.provider.get.return_value = "lrclib"
        app.request_timeout.get.return_value = "0"
        with (
            patch("lyrics_manager.app.is_supported_format", return_value=True),
            patch("lyrics_manager.app.get_provider"),
            patch("lyrics_manager.app.messagebox.showerror") as showerror,
        ):
            app.start_processing()
        assert "greater than zero" in str(showerror.call_args)

    def test_zero_workers_rejected(self, tmp_path: Path):
        (tmp_path / "track.mp3").touch()
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        app.provider.get.return_value = "lrclib"
        app.request_timeout.get.return_value = "10"
        app.max_workers.get.return_value = 0
        with (
            patch("lyrics_manager.app.is_supported_format", return_value=True),
            patch("lyrics_manager.app.get_provider"),
            patch("lyrics_manager.app.messagebox.showerror") as showerror,
        ):
            app.start_processing()
        assert "Invalid Workers" in str(showerror.call_args)


class TestStartProcessingSuccess:
    def _valid_app(self, tmp_path: Path):
        (tmp_path / "track.mp3").touch()
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        app.run_mode.get.return_value = "Dry Run"
        app.provider.get.return_value = "lrclib"
        app.request_timeout.get.return_value = "10"
        app.skip_existing.get.return_value = True
        app.plain_fallback.get.return_value = True
        app.parallel_mode.get.return_value = False
        app.max_workers.get.return_value = 4
        return app

    def test_persists_settings(self, tmp_path: Path):
        from contextlib import ExitStack

        app = self._valid_app(tmp_path)
        with ExitStack() as stack:
            stack.enter_context(
                patch("lyrics_manager.app.is_supported_format", return_value=True)
            )
            stack.enter_context(patch("lyrics_manager.app.get_provider"))
            save = stack.enter_context(
                patch("lyrics_manager.app._suite_config.save_value")
            )
            stack.enter_context(patch("lyrics_manager.app.threading.Thread"))
            stack.enter_context(patch("lyrics_manager.app.logger"))
            app.start_processing()
        save.assert_any_call("lyrics_provider", "lrclib")
        save.assert_any_call("lyrics_request_timeout", 10.0)
        save.assert_any_call("lyrics_max_workers", 4)

    def test_spawns_background_thread(self, tmp_path: Path):
        from contextlib import ExitStack

        app = self._valid_app(tmp_path)
        with ExitStack() as stack:
            stack.enter_context(
                patch("lyrics_manager.app.is_supported_format", return_value=True)
            )
            stack.enter_context(patch("lyrics_manager.app.get_provider"))
            stack.enter_context(patch("lyrics_manager.app._suite_config.save_value"))
            thread_cls = stack.enter_context(
                patch("lyrics_manager.app.threading.Thread")
            )
            stack.enter_context(patch("lyrics_manager.app.logger"))
            app.start_processing()
        thread_cls.assert_called_once()
        kwargs = thread_cls.call_args.kwargs
        assert kwargs["target"] == app._run_fetch
        args = kwargs["args"]
        assert args[0] == str(tmp_path)
        assert args[1] is True  # Dry Run
        assert args[2] == "lrclib"
        thread_cls.return_value.start.assert_called_once()
        app.start_btn.config.assert_called_once_with(state="disabled")

    def test_selects_processing_tab_and_sets_status(self, tmp_path: Path):
        from contextlib import ExitStack

        app = self._valid_app(tmp_path)
        with ExitStack() as stack:
            stack.enter_context(
                patch("lyrics_manager.app.is_supported_format", return_value=True)
            )
            stack.enter_context(patch("lyrics_manager.app.get_provider"))
            stack.enter_context(patch("lyrics_manager.app._suite_config.save_value"))
            stack.enter_context(patch("lyrics_manager.app.threading.Thread"))
            stack.enter_context(patch("lyrics_manager.app.logger"))
            app.start_processing()
        app.notebook.select.assert_called_once_with(app._tab_processing)
        app.overall_status.set.assert_called_once_with("Looking up lyrics...")


class TestRunFetch:
    def test_uses_dry_run_log_name(self, tmp_path: Path):
        app = _make_shell_app()
        app.root.after = MagicMock()
        with (
            patch("lyrics_manager.app.file_processor.run_fetch") as run_fetch,
            patch("lyrics_manager.app.active_batch"),
        ):
            app._run_fetch(
                dir_path=str(tmp_path),
                is_dry_run=True,
                provider_name="lrclib",
                request_timeout=10.0,
                skip_existing=True,
                plain_fallback=True,
            )
        assert app._log_path == str(tmp_path / "lyrics_dry_run_log.txt")
        call = run_fetch.call_args
        assert call.kwargs["dir_path"] == str(tmp_path)
        assert call.kwargs["provider_name"] == "lrclib"
        assert call.kwargs["request_timeout"] == 10.0
        assert call.kwargs["parallel_mode"] is False

    def test_uses_live_log_name(self, tmp_path: Path):
        app = _make_shell_app()
        app.root.after = MagicMock()
        with (
            patch("lyrics_manager.app.file_processor.run_fetch"),
            patch("lyrics_manager.app.active_batch"),
        ):
            app._run_fetch(
                dir_path=str(tmp_path),
                is_dry_run=False,
                provider_name="lrclib",
                request_timeout=10.0,
                skip_existing=True,
                plain_fallback=True,
            )
        assert app._log_path == str(tmp_path / "lyrics_sync_log.txt")


class TestOnComplete:
    def test_writes_log_and_schedules_ui_update(self, tmp_path: Path):
        app = _make_shell_app()
        app.root.after = MagicMock()
        app._log_path = str(tmp_path / "log.txt")
        app._on_complete(
            header=["HEADER\n"],
            total=5,
            processed=4,
            skipped=3,
            errors=1,
            duration_secs=90.5,
            log_entries=["entry1\n"],
        )
        text = (tmp_path / "log.txt").read_text(encoding="utf-8")
        assert "HEADER\n" in text
        assert "entry1\n" in text
        assert "SUMMARY:" in text
        assert "Tagged/Updated: 0" in text  # processed(4) - skipped(3) - errors(1)
        app.root.after.assert_called_once()
        callback = app.root.after.call_args.args[1]
        assert callback == app._update_ui_on_complete

    def test_unwritable_log_does_not_raise(self, tmp_path: Path, caplog):
        import logging

        app = _make_shell_app()
        app.root.after = MagicMock()
        blocked = tmp_path / "blocked"  # writing over a directory raises OSError
        blocked.mkdir()
        app._log_path = str(blocked)
        with caplog.at_level(logging.ERROR, logger="lyrics_manager.app"):
            app._on_complete(
                header=[],
                total=1,
                processed=1,
                skipped=0,
                errors=0,
                duration_secs=1.0,
                log_entries=[],
            )
        assert caplog.records
        app.root.after.assert_called_once()


class TestUpdateUiOnComplete:
    def test_labels_update_and_tab_switched(self):
        app = _make_shell_app()
        app.run_mode.get.return_value = "Live Update"
        app._update_ui_on_complete(5, 4, 0, 1, 1, 30)
        app.time_label.config.assert_called_once()
        app.summary_label.config.assert_called_once()
        text = str(app.summary_label.config.call_args)
        assert "Total: 5 files" in text
        app.completion_label.config.assert_called_once()
        assert "Lyrics Tagging Complete!" in str(app.completion_label.config.call_args)
        app.notebook.select.assert_called_once_with(app._tab_results)
        app.start_btn.config.assert_called_once_with(state="normal")

    def test_auto_end_destroys_window(self):
        app = _make_shell_app()
        app.auto_end = True
        app._update_ui_on_complete(1, 1, 0, 0, 0, 0)
        saved = [c.args for c in app.root.after.call_args_list]
        assert any(args[0] == 2000 and args[1] == app.root.destroy for args in saved)


class TestPresets:
    def test_collect_settings(self):
        app = _make_shell_app()
        app.provider.get.return_value = "lrclib"
        app.request_timeout.get.return_value = "15"
        app.skip_existing.get.return_value = True
        app.plain_fallback.get.return_value = False
        app.parallel_mode.get.return_value = True
        app.max_workers.get.return_value = 6
        app.run_mode.get.return_value = "Dry Run"
        settings = app._collect_settings()
        assert settings["provider"] == "lrclib"
        assert settings["request_timeout"] == "15"
        assert settings["max_workers"] == 6

    def test_apply_preset_sets_vars(self):
        app = _make_shell_app()
        app._apply_preset(
            {
                "provider": "lrclib",
                "request_timeout": "20",
                "skip_existing": False,
                "plain_fallback": True,
                "parallel_mode": True,
                "max_workers": 8,
                "run_mode": "Live Update",
            }
        )
        app.provider.set.assert_called_once_with("lrclib")
        app.request_timeout.set.assert_called_once_with("20")
        app.skip_existing.set.assert_called_once_with(False)
        app.plain_fallback.set.assert_called_once_with(True)
        app.max_workers.set.assert_called_once_with(8)

    def test_preset_selected_loads_config(self):
        app = _make_shell_app()
        app._apply_preset = MagicMock()
        payload = _json.dumps({"provider": "lrclib", "max_workers": 4})
        with patch(
            "lyrics_manager.app._suite_config.load_value", return_value=payload
        ) as load:
            app._on_preset_selected("My Preset")
        load.assert_called_once_with("lyrics_preset_My Preset", None)
        app._apply_preset.assert_called_once()

    def test_preset_selected_ignores_garbage(self):
        app = _make_shell_app()
        with patch(
            "lyrics_manager.app._suite_config.load_value", return_value="not json"
        ):
            app._on_preset_selected("Broken")  # must not raise

    def test_save_current_as_preset_saves_settings(self):
        app = _make_shell_app()
        app._collect_settings = MagicMock(
            return_value={"provider": "lrclib", "max_workers": 4}
        )
        app._refresh_preset_list = MagicMock()
        with (
            patch("lyrics_manager.app._suite_config.save_value") as save,
            patch("lyrics_manager.app._suite_config.load_value", return_value=None),
        ):
            app._save_current_as_preset("Night Mix")
        save.assert_any_call(
            "lyrics_preset_Night Mix",
            _json.dumps({"provider": "lrclib", "max_workers": 4}),
        )
        save.assert_any_call("lyrics_presets_list", _json.dumps(["Night Mix"]))
        app._refresh_preset_list.assert_called_once()

    def test_delete_preset_removes_from_list(self):
        app = _make_shell_app()
        app._refresh_preset_list = MagicMock()
        with (
            patch(
                "lyrics_manager.app._suite_config.load_value",
                return_value=_json.dumps(["Old", "Keep"]),
            ),
            patch("lyrics_manager.app._suite_config.save_value") as save,
        ):
            app._delete_preset("Old")
        save.assert_any_call("lyrics_presets_list", _json.dumps(["Keep"]))
        app._refresh_preset_list.assert_called_once()


class TestErrorPaths:
    def test_on_error_schedules_dialog(self):
        app = _make_shell_app()
        app.root.after = MagicMock()
        with patch("lyrics_manager.app.logger"):
            app._on_error("boom")
        app.root.after.assert_called_once()
        assert app.root.after.call_args.args[1] == app._show_error_dialog

    def test_show_error_dialog_reenables_start(self):
        app = _make_shell_app()
        with patch("lyrics_manager.app.messagebox.showerror") as showerror:
            app._show_error_dialog("boom")
        showerror.assert_called_once()
        app.start_btn.config.assert_called_once_with(state="normal")


class TestConstruction:
    """__init__ + _build_ui wired together on a real (hidden) Tk root.

    Every external touchpoint (bootstrap, CLI handshake, config file) is
    isolated; the UI tabs themselves are built for real so wiring mistakes
    surface here instead of only at launch.
    """

    @staticmethod
    def _build(root, *, last_dir: str = ""):
        from contextlib import ExitStack

        before = set(root.winfo_children())
        with ExitStack() as stack:
            stack.enter_context(
                patch(
                    "lyrics_manager.app.bootstrap_tool_app",
                    return_value=(MagicMock(), None),
                )
            )
            stack.enter_context(
                patch(
                    "lyrics_manager.utils.cli_args.was_launched_from_driver",
                    return_value=False,
                )
            )
            stack.enter_context(
                patch(
                    "lyrics_manager.utils.cli_args.parse",
                    return_value=LyricsArgs(),
                )
            )
            stack.enter_context(
                patch(
                    "lyrics_manager.app._suite_config.load_value",
                    side_effect=lambda key, default=None: default,
                )
            )
            stack.enter_context(
                patch(
                    "lyrics_manager.app._suite_config.load_last_directory",
                    return_value=last_dir,
                )
            )
            app = LyricsManagerApp(root)
        return app, before

    def test_variables_initialised_from_config_defaults(self, root):
        app, before = self._build(root)
        try:
            assert app.provider.get() == "lrclib"
            assert app.parallel_mode.get() is False
            assert app.max_workers.get() == 4
            assert app.skip_existing.get() is True
            assert app.plain_fallback.get() is True
            assert app.run_mode.get() == "Dry Run"
        finally:
            for w in set(root.winfo_children()) - before:
                w.destroy()

    def test_slot_pool_and_preset_wiring(self, root):
        app, before = self._build(root)
        try:
            assert app.slot_queue.qsize() == 4
            assert [v.get() for v in app.slot_vars] == ["IDLE"] * 4
            assert app._refresh_preset_list is not None
            assert app._preset_combo is not None
            assert app.start_btn is not None
            assert app.overall_status is not None
            assert app.notebook.index("end") == 3
        finally:
            for w in set(root.winfo_children()) - before:
                w.destroy()

    def test_no_cli_folder_restores_last_used_directory(self, root):
        app, before = self._build(root, last_dir="D:/Music")
        try:
            assert app.folder_path.get() == "D:/Music"
        finally:
            for w in set(root.winfo_children()) - before:
                w.destroy()

    def test_standalone_launch_is_not_driver_locked(self, root):
        app, before = self._build(root)
        try:
            assert app._launched_from_driver is False
        finally:
            for w in set(root.winfo_children()) - before:
                w.destroy()


class TestStartProcessingPermissionAndFallthrough:
    def test_permission_error_reading_folder_shows_access_denied(self, tmp_path: Path):
        (tmp_path / "track.mp3").touch()
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        with (
            patch(
                "lyrics_manager.app.os.listdir",
                side_effect=PermissionError("no permission"),
            ),
            patch("lyrics_manager.app.messagebox.showerror") as showerror,
        ):
            app.start_processing()
        assert "Access Denied" in str(showerror.call_args)
        showerror.assert_called_once()

    def test_unexpected_error_falls_through_to_validation_dialog(self, tmp_path: Path):
        (tmp_path / "track.mp3").touch()
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        with (
            patch(
                "lyrics_manager.app.os.listdir",
                side_effect=RuntimeError("boom"),
            ),
            patch("lyrics_manager.app.messagebox.showerror") as showerror,
            patch("lyrics_manager.app.logger"),
        ):
            app.start_processing()
        assert "Validation Error" in str(showerror.call_args)
        showerror.assert_called_once()


class TestPresetEdgeCases:
    def test_preset_selected_unknown_name_does_nothing(self):
        app = _make_shell_app()
        app._apply_preset = MagicMock()
        with patch(
            "lyrics_manager.app._suite_config.load_value", return_value=None
        ) as load:
            app._on_preset_selected("Unknown")
        load.assert_called_once_with("lyrics_preset_Unknown", None)
        app._apply_preset.assert_not_called()

    def test_save_preset_adds_to_names_list(self):
        app = _make_shell_app()
        app._collect_settings = MagicMock(return_value={"provider": "lrclib"})
        app._refresh_preset_list = MagicMock()
        existing = _json.dumps(["Existing"])
        with (
            patch("lyrics_manager.app._suite_config.save_value") as save,
            patch("lyrics_manager.app._suite_config.load_value", return_value=existing),
        ):
            app._save_current_as_preset("New")
        save.assert_any_call("lyrics_presets_list", _json.dumps(["Existing", "New"]))

    def test_save_preset_does_not_duplicate_name(self):
        app = _make_shell_app()
        app._collect_settings = MagicMock(return_value={"provider": "lrclib"})
        app._refresh_preset_list = MagicMock()
        existing = _json.dumps(["Existing"])
        with (
            patch("lyrics_manager.app._suite_config.save_value") as save,
            patch("lyrics_manager.app._suite_config.load_value", return_value=existing),
        ):
            app._save_current_as_preset("Existing")
        save.assert_any_call("lyrics_presets_list", _json.dumps(["Existing"]))

    def test_delete_preset_removes_from_names_list(self):
        app = _make_shell_app()
        app._refresh_preset_list = MagicMock()
        with (
            patch(
                "lyrics_manager.app._suite_config.load_value",
                return_value=_json.dumps(["A", "B", "C"]),
            ),
            patch("lyrics_manager.app._suite_config.save_value") as save,
        ):
            app._delete_preset("B")
        save.assert_any_call("lyrics_presets_list", _json.dumps(["A", "C"]))
