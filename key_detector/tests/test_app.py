"""
Tests for key_detector.app — CLI argument application, run dispatch, and
auto-end closure.

Uses the object.__new__ + MagicMock shell pattern so no real display or
bootstrap is needed.  The machinery this class inherits from
(audio_suite_shared.analysis_app_base) is covered once, in
audio_suite_shared/tests/test_analysis_app_base.py; what is asserted here is
Key Detector's own wiring: its literals and its file_processor call.
"""

import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock, patch

import pytest

from key_detector.app import KeyDetectorApp


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


def _make_cli_app() -> KeyDetectorApp:
    root = MagicMock()
    scheduled: list = []
    root.after.side_effect = lambda delay, fn, *a, **kw: scheduled.append((fn, a))
    app = object.__new__(KeyDetectorApp)
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
        with patch("key_detector.utils.cli_args.parse", return_value=parsed):
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
        with patch("key_detector.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        fn, args = app._scheduled[-1]
        assert fn == app.start_processing
        assert args == ()

    def test_auto_end_bool_still_synced(self):
        parsed = _make_parsed(auto_end=True)
        app = _make_cli_app()
        with patch("key_detector.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        assert app.auto_end is True

    def test_tool_specific_settings_applied(self):
        parsed = _make_parsed(analysis_duration=45, parallel_mode=False, max_workers=2)
        app = _make_cli_app()
        with patch("key_detector.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.analysis_duration.set.assert_called_once_with(45)
        app.parallel_mode.set.assert_called_once_with(False)
        app.max_workers.set.assert_called_once_with(2)


class TestApplyCliArgsStandalone:
    """Standalone launch: no folder arg leaves everything untouched."""

    def test_no_folder_path_returns_before_mirroring(self):
        parsed = MagicMock(folder_path="", live_mode=True)
        app = _make_cli_app()
        with patch("key_detector.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
            app.run_mode.set.assert_not_called()
            app.clear_logs_var.set.assert_not_called()
            parsed.folder_path = "C:/music"
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Live Update")

    def test_dry_run_mode_string(self):
        parsed = _make_parsed()
        app = _make_cli_app()
        with patch("key_detector.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Dry Run")

    def test_no_auto_start_no_scheduling(self):
        parsed = _make_parsed(auto_start=False)
        app = _make_cli_app()
        with patch("key_detector.utils.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Dry Run")
        app.root.after.assert_not_called()


class TestToolIdentity:
    """The literals the shared scaffold reads back per tool."""

    def test_tool_id_unchanged(self):
        assert KeyDetectorApp.TOOL_ID == "key_detector"

    def test_window_and_help_unchanged(self):
        assert KeyDetectorApp.WINDOW_NAME == "key_detector_window"
        assert KeyDetectorApp.APP_TITLE == "Key Detector & Tagger"
        assert KeyDetectorApp.HELP_GUIDE == "Key_Detector_User_Guide.docx"

    def test_config_keys_stay_in_the_key_namespace(self):
        app = _make_cli_app()
        assert app._setting_key("parallel_mode") == "key_parallel_mode"
        assert app._setting_key("max_workers") == "key_max_workers"

    def test_user_visible_strings_are_key_specific(self):
        assert KeyDetectorApp.STARTING_STATUS == "Detecting musical keys..."
        assert KeyDetectorApp.REPORT_HEADER == "KEY DETECTION REPORT"
        assert KeyDetectorApp.SKIPPED_SUMMARY_LABEL == "Skipped (already tagged)"
        assert KeyDetectorApp.LIVE_COMPLETION_TEXT == "Key Tagging Complete!"


def _make_batch_app(tmp_path, run_mode="Dry Run") -> KeyDetectorApp:
    """Shell holding every field the run/completion path reads."""
    app = object.__new__(KeyDetectorApp)
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
    """The one call that is Key Detector's own: file_processor.run_analysis."""

    def test_forwards_every_argument_to_run_analysis(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.active_batch"):
            with patch("key_detector.core.file_processor.run_analysis") as mock_run:
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

    def test_tag_writes_are_undoable_under_the_key_detector_batch(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.active_batch") as mock_batch:
            with patch("key_detector.core.file_processor.run_analysis"):
                app._run_batch()

        mock_batch.assert_called_once_with("key_detector", "tag_edit")

    def test_log_file_keeps_the_key_detector_names(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.active_batch"):
            with patch("key_detector.core.file_processor.run_analysis"):
                app._run_batch()
        assert app._log_path == str(tmp_path / "key_dry_run_log.txt")

    def test_live_run_uses_the_sync_log_name(self, tmp_path):
        app = _make_batch_app(tmp_path, run_mode="Live Update")
        with patch("audio_suite_shared.analysis_app_base.active_batch"):
            with patch("key_detector.core.file_processor.run_analysis") as mock_run:
                app._run_batch()

        assert app._log_path == str(tmp_path / "key_sync_log.txt")
        assert mock_run.call_args.kwargs["is_dry_run"] is False

    def test_run_delegates_to_the_shared_batch(self, tmp_path):
        """``_run`` exists only to attach the tool's error context."""
        app = _make_batch_app(tmp_path)
        app._run_batch = MagicMock()
        app._run()
        app._run_batch.assert_called_once_with()

    def test_run_swallows_errors_from_the_analysis(self, tmp_path):
        """The context is ``reraise=False``: a failure must not kill the thread
        with an unhandled exception, and must be logged instead."""
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.active_batch"):
            with patch(
                "key_detector.core.file_processor.run_analysis",
                side_effect=RuntimeError("analysis blew up"),
            ):
                app._run()


class TestOnCompleteReport:
    def _complete(self, app, **overrides) -> None:
        kwargs = {
            "header": ["H\n"],
            "total": 3,
            "processed": 3,
            "skipped": 1,
            "errors": 0,
            "duration_secs": 61.0,
            "log_entries": ["song.mp3 -> C\n"],
        }
        kwargs.update(overrides)
        app._on_complete(**kwargs)

    def _shell(self, tmp_path, run_mode="Dry Run"):
        app = _make_batch_app(tmp_path, run_mode=run_mode)
        app._log_path = str(tmp_path / "key_dry_run_log.txt")
        return app

    def test_report_opens_with_the_key_detection_header(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.active_batch"):
            with patch("key_detector.core.file_processor.run_analysis") as mock_run:
                app._run_batch()

        # Drive the completion callback the run actually handed over, so the
        # header the base built is the one that lands in the report.
        mock_run.call_args.kwargs["on_complete"](
            total=3,
            processed=3,
            skipped=1,
            errors=0,
            duration_secs=61.0,
            log_entries=["song.mp3 -> C\n"],
        )

        with open(app._log_path, encoding="utf-8") as handle:
            report = handle.read()
        assert report.startswith("KEY DETECTION REPORT")
        assert "Mode: DRY RUN" in report
        assert "song.mp3 -> C" in report
        assert "Skipped (already tagged): 1" in report

    def test_skipped_count_is_labelled_as_already_tagged(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)

        with open(app._log_path, encoding="utf-8") as handle:
            assert "Skipped (already tagged): 1" in handle.read()

    def test_dry_run_completion_label(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)

        # The label is applied by the scheduled main-thread callback.
        app._update_ui_on_complete(3, 2, 1, 0, 1, 1)
        assert (
            app.completion_label.config.call_args.kwargs["text"] == "Analysis Complete!"
        )

    def test_live_completion_label_is_key_specific(self, tmp_path):
        app = self._shell(tmp_path, run_mode="Live Update")
        self._complete(app)
        app._update_ui_on_complete(3, 2, 1, 0, 1, 1)

        assert (
            app.completion_label.config.call_args.kwargs["text"]
            == "Key Tagging Complete!"
        )

    def test_results_tab_is_shown_when_the_run_finishes(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)
        app._update_ui_on_complete(3, 2, 1, 0, 1, 1)

        app.notebook.select.assert_called_once_with(app._tab_results)

    def test_start_button_is_re_enabled_for_the_next_run(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)
        app._update_ui_on_complete(3, 2, 1, 0, 1, 1)

        app.start_btn.config.assert_called_once_with(state="normal")


class TestOnCompleteAutoEnd:
    """Regression: the Setup-tab Auto End checkbox must work standalone.

    Key Detector used to consult only ``self.auto_end`` — the bool mirrored
    from the driver's CLI.  On a standalone launch the checkbox the user ticks
    in the Setup tab set ``auto_end_var`` alone, so the window never closed.
    """

    def _shell(self, tmp_path, auto_end, checkbox):
        app = _make_batch_app(tmp_path)
        app._log_path = str(tmp_path / "key_dry_run_log.txt")
        app.auto_end = auto_end
        app.auto_end_var = MagicMock(**{"get.return_value": checkbox})
        return app

    def _complete(self, app) -> None:
        app._on_complete(
            header=["H\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )

    @staticmethod
    def _closes(app) -> bool:
        return any(call_.args[0] == 2000 for call_ in app.root.after.call_args_list)

    def test_checkbox_alone_closes(self, tmp_path):
        app = self._shell(tmp_path, auto_end=False, checkbox=True)
        self._complete(app)
        assert self._closes(app)

    def test_cli_bool_alone_closes(self, tmp_path):
        app = self._shell(tmp_path, auto_end=True, checkbox=False)
        self._complete(app)
        assert self._closes(app)

    def test_neither_leaves_the_window_open(self, tmp_path):
        app = self._shell(tmp_path, auto_end=False, checkbox=False)
        self._complete(app)
        assert not self._closes(app)

    def test_marker_reaches_the_report(self, tmp_path):
        app = self._shell(tmp_path, auto_end=False, checkbox=True)
        self._complete(app)

        with open(app._log_path, encoding="utf-8") as handle:
            assert "Auto End enabled" in handle.read()


class TestStartProcessingValidation:
    def test_no_folder_warns(self):
        app = object.__new__(KeyDetectorApp)
        app.folder_path = MagicMock(**{"get.return_value": ""})
        with patch("audio_suite_shared.analysis_app_base.messagebox") as mock_box:
            app.start_processing()
        mock_box.showwarning.assert_called_once()

    def test_invalid_path_errors(self):
        app = object.__new__(KeyDetectorApp)
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

    def test_status_line_is_the_key_detection_one(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("audio_suite_shared.analysis_app_base.threading"):
            app.start_processing()

        app.overall_status.set.assert_called_once_with("Detecting musical keys...")


def test_module_exports_the_app_under_its_historical_name():
    """The launcher and the driver both import ``key_detector.KeyDetectorApp``."""
    import key_detector

    assert key_detector.KeyDetectorApp is KeyDetectorApp


@pytest.mark.parametrize(
    "attribute", ["_run_batch", "start_processing", "_on_complete", "_on_progress"]
)
def test_scaffold_methods_are_inherited_not_reimplemented(attribute):
    """Guards against a copy of the shared machinery creeping back in."""
    from audio_suite_shared.analysis_app_base import AnalysisAppBase

    assert getattr(KeyDetectorApp, attribute) is getattr(AnalysisAppBase, attribute)


def test_only_the_analysis_call_and_error_context_are_overridden():
    """The two overrides that are genuinely Key Detector's own."""
    from audio_suite_shared.analysis_app_base import AnalysisAppBase

    assert KeyDetectorApp._run_analysis is not AnalysisAppBase._run_analysis
    assert KeyDetectorApp._run is not AnalysisAppBase._run


@pytest.fixture
def real_app(root):
    """Factory building the real app on the live root, config/CLI stubbed.

    Widgets are torn down after the test so each case starts from the same
    clean root.
    """
    baseline = set(root.winfo_children())

    def _make(parsed=None, last_directory="", load_value=None) -> KeyDetectorApp:
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
                with patch("key_detector.utils.cli_args.parse", return_value=parsed):
                    with patch(
                        "key_detector.utils.cli_args.was_launched_from_driver",
                        return_value=bool(parsed.folder_path),
                    ):
                        return KeyDetectorApp(root)

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
            return {"key_parallel_mode": True, "key_max_workers": 8}.get(key, default)

        app = real_app(load_value=_load)
        assert app.parallel_mode.get() is True
        assert app.max_workers.get() == 8
