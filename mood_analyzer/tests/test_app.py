"""
Tests for mood_analyzer.app — CLI argument application and auto-end closure.

Uses the object.__new__ + MagicMock shell pattern so no real display or
bootstrap is needed.
"""

from unittest.mock import MagicMock, patch

from mood_analyzer.app import MoodAnalyzerApp


def _make_parsed(**overrides) -> MagicMock:
    defaults: dict = {
        "folder_path": "C:/music",
        "live_mode": False,
        "auto_start": False,
        "auto_end": False,
        "clear_logs": False,
        "parallel_run": False,
        "analysis_duration": 90,
        "parallel_mode": True,
        "max_workers": 6,
    }
    defaults.update(overrides)
    return MagicMock(**defaults)


def _make_cli_app() -> MoodAnalyzerApp:
    root = MagicMock()
    scheduled: list = []
    root.after.side_effect = lambda delay, fn, *a, **kw: scheduled.append((fn, a))
    app = object.__new__(MoodAnalyzerApp)
    app.root = root
    app._scheduled = scheduled
    app.folder_path = MagicMock()
    app.run_mode = MagicMock()
    app.analysis_duration = MagicMock()
    app.parallel_mode = MagicMock()
    app.max_workers = MagicMock()
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()
    app.auto_end = False
    app.start_processing = MagicMock()
    return app


class TestApplyCliArgsDriven:
    """Driver launch: run controls mirrored onto the Setup tab panel."""

    def test_mirrors_all_run_controls(self):
        parsed = _make_parsed(
            live_mode=True,
            auto_start=True,
            auto_end=True,
            clear_logs=True,
            parallel_run=True,
        )
        app = _make_cli_app()
        with patch("mood_analyzer.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.folder_path.set.assert_called_once_with("C:/music")
        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_auto_start_schedules_processing(self):
        parsed = _make_parsed(auto_start=True)
        app = _make_cli_app()
        with patch("mood_analyzer.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        fn, args = app._scheduled[-1]
        assert fn == app.start_processing
        assert args == ()

    def test_auto_end_bool_still_synced(self):
        parsed = _make_parsed(auto_end=True)
        app = _make_cli_app()
        with patch("mood_analyzer.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        assert app.auto_end is True

    def test_tool_specific_settings_applied(self):
        parsed = _make_parsed(analysis_duration=45, parallel_mode=False, max_workers=2)
        app = _make_cli_app()
        with patch("mood_analyzer.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.analysis_duration.set.assert_called_once_with(45)
        app.parallel_mode.set.assert_called_once_with(False)
        app.max_workers.set.assert_called_once_with(2)


class TestApplyCliArgsStandalone:
    """Standalone launch: no folder arg leaves everything untouched."""

    def test_no_folder_path_returns_before_mirroring(self):
        parsed = MagicMock(folder_path="", live_mode=True)
        app = _make_cli_app()
        with patch("mood_analyzer.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.run_mode.set.assert_not_called()
        app.clear_logs_var.set.assert_not_called()

    def test_dry_run_mode_string(self):
        parsed = _make_parsed()
        app = _make_cli_app()
        with patch("mood_analyzer.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Dry Run")

    def test_no_auto_start_no_scheduling(self):
        parsed = _make_parsed(auto_start=False)
        app = _make_cli_app()
        with patch("mood_analyzer.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.root.after.assert_not_called()


class TestOnCompleteAutoEnd:
    """Auto-end must honor the Setup-tab checkbox var, not just the CLI bool."""

    def _make_app(self, tmp_path, auto_end, auto_end_var):
        root = MagicMock()
        app = object.__new__(MoodAnalyzerApp)
        app.root = root
        app.run_mode = MagicMock()
        app.run_mode.get.return_value = "Dry Run"
        app._log_path = str(tmp_path / "mood_dry_run_log.txt")
        app.auto_end = auto_end
        app.auto_end_var = MagicMock()
        app.auto_end_var.get.return_value = auto_end_var
        app._update_ui_on_complete = MagicMock()
        return app

    def _run_complete(self, app) -> None:
        app._on_complete(
            header=["H\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=["x\n"],
        )

    @staticmethod
    def _destroy_scheduled(app) -> bool:
        return any(call_.args[0] == 2000 for call_ in app.root.after.call_args_list)

    def test_checkbox_alone_triggers_close(self, tmp_path):
        app = self._make_app(tmp_path, auto_end=False, auto_end_var=True)
        self._run_complete(app)
        assert self._destroy_scheduled(app)

    def test_cli_bool_alone_triggers_close(self, tmp_path):
        app = self._make_app(tmp_path, auto_end=True, auto_end_var=False)
        self._run_complete(app)
        assert self._destroy_scheduled(app)

    def test_no_auto_end_keeps_window_open(self, tmp_path):
        app = self._make_app(tmp_path, auto_end=False, auto_end_var=False)
        self._run_complete(app)
        assert not self._destroy_scheduled(app)
