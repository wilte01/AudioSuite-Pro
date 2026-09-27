"""
Tests for mood_analyzer.app — CLI argument application, run dispatch, and
auto-end closure.

Uses the object.__new__ + MagicMock shell pattern so no real display or
bootstrap is needed.  The machinery this class inherits from
(audio_suite_shared.analysis_app_base) is covered once, in
audio_suite_shared/tests/test_analysis_app_base.py; what is asserted here is
Mood Analyzer's own wiring: its literals and its file_processor call.
"""

import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock, patch

import pytest

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


class TestToolIdentity:
    """The literals the shared scaffold reads back per tool."""

    def test_tool_id_unchanged(self):
        assert MoodAnalyzerApp.TOOL_ID == "mood_analyzer"

    def test_window_and_help_unchanged(self):
        assert MoodAnalyzerApp.WINDOW_NAME == "mood_analyzer_window"
        assert MoodAnalyzerApp.APP_TITLE == "Mood Analyzer & Tagger"
        assert MoodAnalyzerApp.HELP_GUIDE == "Mood_Analyzer_User_Guide.docx"

    def test_config_keys_stay_in_the_mood_namespace(self):
        app = _make_cli_app()
        assert app._setting_key("parallel_mode") == "mood_parallel_mode"
        assert app._setting_key("max_workers") == "mood_max_workers"

    def test_user_visible_strings_are_mood_specific(self):
        assert (
            MoodAnalyzerApp.STARTING_STATUS == "Detecting mood from the audio signal..."
        )
        assert MoodAnalyzerApp.REPORT_HEADER == "MOOD DETECTION REPORT"
        assert MoodAnalyzerApp.SKIPPED_SUMMARY_LABEL == "Skipped (undecodable/silent)"
        assert MoodAnalyzerApp.LIVE_COMPLETION_TEXT == "Mood Tagging Complete!"


def _make_batch_app(tmp_path, run_mode="Dry Run") -> MoodAnalyzerApp:
    """Shell holding every field the run/completion path reads."""
    app = object.__new__(MoodAnalyzerApp)
    app.root = MagicMock()
    app.folder_path = MagicMock(**{"get.return_value": str(tmp_path)})
    app.run_mode = MagicMock(**{"get.return_value": run_mode})
    app.analysis_duration = MagicMock(**{"get.return_value": 45})
    app.parallel_mode = MagicMock(**{"get.return_value": True})
    app.max_workers = MagicMock(**{"get.return_value": 6})
    app.slot_queue = MagicMock()
    app._safe_slot_vars = [MagicMock()]
    app.progress = {}
    app.auto_end = False
    app.auto_end_var = MagicMock(**{"get.return_value": False})
    app.start_btn = MagicMock()
    app.file_listbox = MagicMock()
    app.notebook = MagicMock()
    app.overall_status = MagicMock()
    app._tab_processing = MagicMock()
    app._tab_results = MagicMock()
    app.completion_label = MagicMock()
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    return app


class TestRunDispatch:
    """The one call that is Mood Analyzer's own: file_processor.run_analysis."""

    def test_forwards_every_argument_to_run_analysis(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.active_batch"):
            with patch("mood_analyzer.core.file_processor.run_analysis") as mock_run:
                app._run_batch()

        kwargs = mock_run.call_args.kwargs
        assert kwargs["dir_path"] == str(tmp_path)
        assert kwargs["is_dry_run"] is True
        assert kwargs["analysis_duration"] == 45
        assert kwargs["parallel_mode"] is True
        assert kwargs["max_workers"] == 6
        assert kwargs["slot_vars"] == app._safe_slot_vars
        assert kwargs["slot_queue"] is app.slot_queue
        assert kwargs["on_progress"] == app._on_progress
        assert kwargs["on_error"] == app._on_error

    def test_tag_writes_are_undoable_under_the_mood_batch(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.active_batch") as mock_batch:
            with patch("mood_analyzer.core.file_processor.run_analysis"):
                app._run_batch()

        mock_batch.assert_called_once_with("mood_analyzer", "tag_edit")

    def test_log_file_keeps_the_mood_analyzer_names(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.active_batch"):
            with patch("mood_analyzer.core.file_processor.run_analysis"):
                app._run_batch()
        assert app._log_path == str(tmp_path / "mood_dry_run_log.txt")

    def test_live_run_uses_the_sync_log_name(self, tmp_path):
        app = _make_batch_app(tmp_path, run_mode="Live Update")
        with patch("audio_suite_shared.analysis_app_base.active_batch"):
            with patch("mood_analyzer.core.file_processor.run_analysis") as mock_run:
                app._run_batch()

        assert app._log_path == str(tmp_path / "mood_sync_log.txt")
        assert mock_run.call_args.kwargs["is_dry_run"] is False

    def test_run_delegates_to_the_shared_batch(self, tmp_path):
        """``_run`` exists only to attach the tool's error context."""
        app = _make_batch_app(tmp_path)
        app._run_batch = MagicMock()
        app._run()
        app._run_batch.assert_called_once_with()

    def test_run_swallows_errors_from_the_analysis(self, tmp_path):
        """``reraise=False``: a failure must not kill the thread unhandled."""
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.active_batch"):
            with patch(
                "mood_analyzer.core.file_processor.run_analysis",
                side_effect=RuntimeError("analysis blew up"),
            ):
                app._run()


class TestOnCompleteReport:
    def _complete(self, app, **overrides) -> None:
        kwargs = {
            "header": ["H\n"],
            "total": 3,
            "processed": 3,
            "skipped": 2,
            "errors": 0,
            "duration_secs": 61.0,
            "log_entries": ["song.mp3 -> Energetic;Bright\n"],
        }
        kwargs.update(overrides)
        app._on_complete(**kwargs)

    def _shell(self, tmp_path, run_mode="Dry Run"):
        app = _make_batch_app(tmp_path, run_mode=run_mode)
        app._log_path = str(tmp_path / "mood_dry_run_log.txt")
        return app

    def test_report_opens_with_the_mood_detection_header(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.active_batch"):
            with patch("mood_analyzer.core.file_processor.run_analysis") as mock_run:
                app._run_batch()

        # Drive the completion callback the run actually handed over, so the
        # header the base built is the one that lands in the report.
        mock_run.call_args.kwargs["on_complete"](
            total=3,
            processed=3,
            skipped=2,
            errors=0,
            duration_secs=61.0,
            log_entries=["song.mp3 -> Energetic;Bright\n"],
        )

        with open(app._log_path, encoding="utf-8") as handle:
            report = handle.read()
        assert report.startswith("MOOD DETECTION REPORT")
        assert "Mode: DRY RUN" in report
        assert "song.mp3 -> Energetic;Bright" in report

    def test_skipped_count_is_labelled_as_undecodable(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)

        with open(app._log_path, encoding="utf-8") as handle:
            assert "Skipped (undecodable/silent): 2" in handle.read()

    def test_dry_run_completion_label(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)
        app._update_ui_on_complete(3, 1, 2, 0, 1, 1)

        assert (
            app.completion_label.config.call_args.kwargs["text"] == "Analysis Complete!"
        )

    def test_live_completion_label_is_mood_specific(self, tmp_path):
        app = self._shell(tmp_path, run_mode="Live Update")
        self._complete(app)
        app._update_ui_on_complete(3, 1, 2, 0, 1, 1)

        assert (
            app.completion_label.config.call_args.kwargs["text"]
            == "Mood Tagging Complete!"
        )

    def test_start_button_is_re_enabled_for_the_next_run(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)
        app._update_ui_on_complete(3, 1, 2, 0, 1, 1)

        app.start_btn.config.assert_called_once_with(state="normal")


class TestStartProcessingValidation:
    def test_no_folder_warns(self):
        app = object.__new__(MoodAnalyzerApp)
        app.folder_path = MagicMock(**{"get.return_value": ""})
        with patch("audio_suite_shared.analysis_app_base.messagebox") as mock_box:
            app.start_processing()
        mock_box.showwarning.assert_called_once()

    def test_invalid_path_errors(self):
        app = object.__new__(MoodAnalyzerApp)
        app.folder_path = MagicMock(**{"get.return_value": "C:/nope"})
        with patch(
            "audio_suite_shared.analysis_app_base.os.path.isdir", return_value=False
        ):
            with patch("audio_suite_shared.analysis_app_base.messagebox") as mock_box:
                app.start_processing()
        mock_box.showerror.assert_called_once()

    def test_valid_folder_starts_the_daemon_thread(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.threading") as mock_threading:
            app.start_processing()

        mock_threading.Thread.assert_called_once_with(target=app._run, daemon=True)
        mock_threading.Thread.return_value.start.assert_called_once()

    def test_status_line_is_the_mood_detection_one(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.threading"):
            app.start_processing()

        app.overall_status.set.assert_called_once_with(
            "Detecting mood from the audio signal..."
        )


def test_module_exports_the_app_under_its_historical_name():
    """The launcher imports ``mood_analyzer.MoodAnalyzerApp``."""
    import mood_analyzer

    assert mood_analyzer.MoodAnalyzerApp is MoodAnalyzerApp


@pytest.mark.parametrize(
    "attribute", ["_run_batch", "start_processing", "_on_complete", "_on_progress"]
)
def test_scaffold_methods_are_inherited_not_reimplemented(attribute):
    """Guards against a copy of the shared machinery creeping back in."""
    from audio_suite_shared.analysis_app_base import AnalysisAppBase

    assert getattr(MoodAnalyzerApp, attribute) is getattr(AnalysisAppBase, attribute)


def test_only_the_analysis_call_and_error_context_are_overridden():
    """The two overrides that are genuinely Mood Analyzer's own."""
    from audio_suite_shared.analysis_app_base import AnalysisAppBase

    assert MoodAnalyzerApp._run_analysis is not AnalysisAppBase._run_analysis
    assert MoodAnalyzerApp._run is not AnalysisAppBase._run


@pytest.fixture
def real_app(root):
    """Factory building the real app on the live root, config/CLI stubbed.

    Widgets are torn down after the test so each case starts from the same
    clean root.
    """
    baseline = set(root.winfo_children())

    def _make(parsed=None, last_directory="", load_value=None) -> MoodAnalyzerApp:
        if parsed is None:
            parsed = _make_parsed(folder_path="")
        with patch("audio_suite_shared.app_bootstrap.platform_utils.setup_window"):
            with patch("audio_suite_shared.analysis_app_base._suite_config") as config:
                if load_value is None:
                    config.load_value.side_effect = lambda key, default: default
                else:
                    config.load_value.side_effect = load_value
                config.load_last_directory.return_value = last_directory
                config.list_presets.return_value = []
                with patch("mood_analyzer.utils.cli_args.parse", return_value=parsed):
                    with patch(
                        "mood_analyzer.utils.cli_args.was_launched_from_driver",
                        return_value=bool(parsed.folder_path),
                    ):
                        return MoodAnalyzerApp(root)

    yield _make

    for child in set(root.winfo_children()) - baseline:
        child.destroy()


@pytest.mark.gui
class TestRealConstruction:
    """The whole point of the consolidation: the real GUI still builds.

    Everything else in this file stubs the object out, so without these the
    shared ``__init__``/``_build_ui`` could be broken and the suite stay green.
    """

    def test_builds_all_three_tabs(self, real_app, root) -> None:
        app = real_app()
        assert [app.notebook.tab(i, "text") for i in range(3)] == [
            " 1. Setup ",
            " 2. Processing ",
            " 3. Results ",
        ]

    def test_wires_the_widgets_the_run_path_uses(self, real_app, root) -> None:
        app = real_app()
        assert isinstance(app.start_btn, tk.Button)
        assert isinstance(app.progress, ttk.Progressbar)
        assert isinstance(app.file_listbox, tk.Listbox)
        assert isinstance(app.overall_status, tk.StringVar)
        assert isinstance(app._preset_combo, ttk.Combobox)
        assert isinstance(app.completion_label, tk.Label)
        assert isinstance(app.summary_label, tk.Label)

    def test_worker_slot_pool_starts_idle_and_full(self, real_app, root) -> None:
        app = real_app()
        assert [v.get() for v in app.slot_vars] == ["IDLE"] * 4
        assert sorted(app.slot_queue.queue) == [0, 1, 2, 3]

    def test_slot_updates_are_marshalled_to_the_main_thread(
        self, real_app, root
    ) -> None:
        """The worker pool must never touch a Tk variable off-thread."""
        app = real_app()
        app._safe_slot_vars[0].set("worker 0")
        root.update()
        assert app.slot_vars[0].get() == "worker 0"

    def test_last_used_directory_is_restored_on_a_standalone_launch(
        self, real_app, root
    ) -> None:
        app = real_app(last_directory="C:/last")
        assert app.folder_path.get() == "C:/last"

    def test_a_cli_folder_wins_over_the_saved_directory(self, real_app, root) -> None:
        app = real_app(
            parsed=_make_parsed(folder_path="C:/cli"),
            last_directory="C:/last",
        )
        assert app.folder_path.get() == "C:/cli"

    def test_saved_parallel_settings_are_reloaded(self, real_app, root) -> None:
        """The worker settings survive a restart via the shared config."""

        def _load(key: str, default):
            return {"mood_parallel_mode": True, "mood_max_workers": 8}.get(key, default)

        app = real_app(load_value=_load)
        assert app.parallel_mode.get() is True
        assert app.max_workers.get() == 8
