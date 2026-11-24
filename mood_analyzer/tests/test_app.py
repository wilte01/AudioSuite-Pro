"""
Tests for mood_analyzer.app — CLI argument application, run dispatch, the
completion report, the run note and Auto End.

Uses the object.__new__ + MagicMock shell pattern so no real display or
bootstrap is needed.  The shell this window composes is covered once, in
``tests/test_suite_app_contract.py``; what is asserted here is Mood Analyzer's
own wiring: its literals, its file_processor call, the run note it records for
the Master Driver, its per-tick stats line and the Auto End condition, which is
this window's own even though the marker and the close are the shell's (D56).

Changed in 1.2.0: covers the run note the batch report shows when the run had
to skip tracks it could not analyse.

Changed in 1.4.0: the worker-slot pool expectations are derived from
``default_max_workers()`` instead of a literal pool of four (PLAN D56).

Changed in 2.9.0: an autouse fixture points the shared ``suite_config`` at
``tmp_path``.  Starting a run calls ``save_last_directory`` - a
read-modify-write of the whole document - so the start-processing cases were
rewriting the developer's real ``audio_suite_config.json``.

Changed in 2.9.0: the window composes ``SuiteApp`` (C1 stage 3, D54), so the
drives name the shell's widgets and poller.  The Auto End, skipped-label and
stats cases go through the ``on_complete`` the run hands to ``run_analysis``
rather than calling a handler directly, so they fail if the port drops either
behaviour.

Changed in 2.9.0: ``start_processing`` is the shell's (D56), so the two
validation cases patch ``messagebox`` where the shell reads it; the
``os.path.isdir`` case needs no move because both modules see one ``os``.
"""

import tkinter as tk
from collections.abc import Callable
from queue import Queue, SimpleQueue
from tkinter import ttk
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared import suite_config
from audio_suite_shared.constants import DEFAULT_ANALYSIS_SECONDS, default_max_workers
from audio_suite_shared.run_outcome import read_outcome
from audio_suite_shared.suite_app import SuiteApp
from mood_analyzer.app import DRIVER_TOOL_ID, MoodAnalyzerApp


@pytest.fixture(autouse=True)
def _isolated_config(tmp_path, monkeypatch):
    """Keep every ``suite_config`` save out of the developer's real file.

    A run that starts persists the last directory, and that save rewrites the
    whole shared document - last directory, palette, font sizes, window
    geometry - so a test that left ``CONFIG_PATH`` alone replaced the
    developer's preferences.
    """
    config_file = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(suite_config, "CONFIG_PATH", config_file)
    monkeypatch.setattr(
        suite_config, "_LOCK_PATH", config_file.with_suffix(".json.lock")
    )
    suite_config._invalidate_cache()
    try:
        yield config_file
    finally:
        suite_config._invalidate_cache()


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


def _make_batch_app(tmp_path, run_mode="Dry Run") -> MoodAnalyzerApp:
    """Shell holding every field the run/completion path reads."""
    is_dry_run = run_mode == "Dry Run"
    app = object.__new__(MoodAnalyzerApp)
    app.root = MagicMock()
    app.folder_path = MagicMock(**{"get.return_value": str(tmp_path)})
    app.run_mode = MagicMock(**{"get.return_value": run_mode})
    app.analysis_duration = MagicMock(**{"get.return_value": 45})
    app.parallel_mode = MagicMock(**{"get.return_value": True})
    app.max_workers = MagicMock(**{"get.return_value": 6})
    app.slot_queue = MagicMock()
    app._safe_slot_vars = [MagicMock() for _ in range(6)]
    app.progress = {}
    app.auto_end = False
    app.auto_end_var = MagicMock(**{"get.return_value": False})
    app.start_btn = MagicMock()
    app.file_listbox = MagicMock()
    app.notebook = MagicMock()
    app.overall_status = MagicMock()
    app.stats_label = MagicMock()
    app.processing_frame = MagicMock()
    app.results_frame = MagicMock()
    app.completion_label = MagicMock()
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app._dir_path = str(tmp_path)
    app._is_dry_run = is_dry_run
    app._analysis_seconds = 45
    app._parallel = True
    app._workers = 6
    app._ui_updates = SimpleQueue()
    return app


def _run_and_capture_completion(app):
    """Drive the real ``_run`` and return the ``on_complete`` it handed over."""
    with patch("mood_analyzer.app.active_batch"):
        with patch("mood_analyzer.core.file_processor.run_analysis") as mock_run:
            app._run()
    return mock_run.call_args.kwargs["on_complete"]


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
        with patch("mood_analyzer.app.parse_cli", return_value=parsed):
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
        with patch("mood_analyzer.app.parse_cli", return_value=parsed):
            app._apply_cli_args()
        fn, args = app._scheduled[-1]
        assert fn == app.start_processing
        assert args == ()

    def test_auto_end_bool_still_synced(self):
        parsed = _make_parsed(auto_end=True)
        app = _make_cli_app()
        with patch("mood_analyzer.app.parse_cli", return_value=parsed):
            app._apply_cli_args()
        assert app.auto_end is True

    def test_tool_specific_settings_applied(self):
        parsed = _make_parsed(analysis_duration=45, parallel_mode=False, max_workers=2)
        app = _make_cli_app()
        with patch("mood_analyzer.app.parse_cli", return_value=parsed):
            app._apply_cli_args()
        app.analysis_duration.set.assert_called_once_with(45)
        app.parallel_mode.set.assert_called_once_with(False)
        app.max_workers.set.assert_called_once_with(2)


class TestApplyCliArgsStandalone:
    """Standalone launch: no folder arg leaves everything untouched."""

    def test_no_folder_path_returns_before_mirroring(self):
        parsed = MagicMock(folder_path="", live_mode=True)
        app = _make_cli_app()
        with patch("mood_analyzer.app.parse_cli", return_value=parsed):
            app._apply_cli_args()
            app.run_mode.set.assert_not_called()
            app.clear_logs_var.set.assert_not_called()
            parsed.folder_path = "C:/music"
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Live Update")

    def test_dry_run_mode_string(self):
        parsed = _make_parsed()
        app = _make_cli_app()
        with patch("mood_analyzer.app.parse_cli", return_value=parsed):
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Dry Run")

    def test_no_auto_start_no_scheduling(self):
        parsed = _make_parsed(auto_start=False)
        app = _make_cli_app()
        with patch("mood_analyzer.app.parse_cli", return_value=parsed):
            app._apply_cli_args()
        app.run_mode.set.assert_called_once_with("Dry Run")
        app.root.after.assert_not_called()


class TestToolIdentity:
    """The literals the shell and the report read back per tool."""

    def test_tool_id_unchanged(self):
        assert MoodAnalyzerApp.TOOL_ID == "mood_analyzer"

    def test_window_and_help_unchanged(self):
        assert MoodAnalyzerApp.window_key == "mood_analyzer_window"
        assert MoodAnalyzerApp.title == "Mood Analyzer & Tagger"
        assert MoodAnalyzerApp.program_name == "mood_analyzer"
        assert MoodAnalyzerApp.HELP_GUIDE == "Mood_Analyzer_User_Guide.docx"
        assert MoodAnalyzerApp.guide_name == MoodAnalyzerApp.HELP_GUIDE

    def test_config_keys_stay_in_the_mood_namespace(self):
        app = _make_cli_app()
        assert app._setting_key("parallel_mode") == "mood_parallel_mode"
        assert app._setting_key("max_workers") == "mood_max_workers"

    def test_user_visible_strings_are_mood_specific(self):
        assert (
            MoodAnalyzerApp.STARTING_STATUS == "Detecting mood from the audio signal..."
        )
        assert MoodAnalyzerApp.REPORT_HEADER == "MOOD DETECTION REPORT"
        assert MoodAnalyzerApp.SKIPPED_LABEL == "Skipped (undecodable/silent)"
        assert MoodAnalyzerApp.TAGGED_LABEL == "Tagged/Analyzed"
        assert MoodAnalyzerApp.LIVE_COMPLETION_TEXT == "Mood Tagging Complete!"
        assert MoodAnalyzerApp.completion_text == "Mood Analysis Complete!"

    def test_the_run_note_keeps_the_driver_tool_id(self):
        assert DRIVER_TOOL_ID == "mood_analyzer"

    def test_the_window_composes_the_shared_shell(self):
        assert issubclass(MoodAnalyzerApp, SuiteApp)


class TestRunDispatch:
    """The one call that is Mood Analyzer's own: file_processor.run_analysis."""

    def test_forwards_every_argument_to_run_analysis(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("mood_analyzer.app.active_batch"):
            with patch("mood_analyzer.core.file_processor.run_analysis") as mock_run:
                app._run()

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
        with patch("mood_analyzer.app.active_batch") as mock_batch:
            with patch("mood_analyzer.core.file_processor.run_analysis"):
                app._run()

        mock_batch.assert_called_once_with("mood_analyzer", "tag_edit")

    def test_log_file_keeps_the_mood_analyzer_names(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch("mood_analyzer.app.active_batch"):
            with patch("mood_analyzer.core.file_processor.run_analysis"):
                app._run()
        assert app._log_path == str(tmp_path / "mood_dry_run_log.txt")

    def test_live_run_uses_the_sync_log_name(self, tmp_path):
        app = _make_batch_app(tmp_path, run_mode="Live Update")
        with patch("mood_analyzer.app.active_batch"):
            with patch("mood_analyzer.core.file_processor.run_analysis") as mock_run:
                app._run()

        assert app._log_path == str(tmp_path / "mood_sync_log.txt")
        assert mock_run.call_args.kwargs["is_dry_run"] is False

    def test_run_swallows_errors_from_the_analysis(self, tmp_path):
        """The context is ``reraise=False``: a failure must not kill the thread
        with an unhandled exception, and must be logged instead."""
        app = _make_batch_app(tmp_path)
        with patch("mood_analyzer.app.active_batch"):
            with patch(
                "mood_analyzer.core.file_processor.run_analysis",
                side_effect=RuntimeError("analysis blew up"),
            ):
                app._run()


class TestCompletionSeam:
    """``run_analysis`` publishes into the handler the window binds to it.

    The publisher is real: its analysis workflow is stood in for where it would
    decode audio, and the payload it emits is handed to the window's own
    handler, so the report is read back from disk instead of from the fields a
    writer just set.
    """

    @staticmethod
    def _fake_workflow(
        _processor: object,
        _dir_path: str,
        _slot_vars: object,
        _slot_queue: object,
        _on_progress: object,
        on_complete: Callable[..., None],
        _on_error: object,
        **_kwargs: object,
    ) -> None:
        """Stand in for the batch and publish the completion it would emit."""
        on_complete(
            total=3,
            processed=3,
            skipped=1,
            errors=0,
            duration_secs=61.0,
            log_entries=["song.mp3 -> Energetic;Bright\n"],
        )

    def test_the_published_payload_reaches_the_written_report(self, tmp_path):
        from mood_analyzer.core import file_processor

        app = _make_batch_app(tmp_path)
        app._log_path = str(tmp_path / "mood_dry_run_log.txt")

        with patch.object(file_processor, "warm_analysis_stack"):
            with patch.object(
                file_processor,
                "run_analysis_workflow",
                side_effect=self._fake_workflow,
            ):
                file_processor.run_analysis(
                    dir_path=str(tmp_path),
                    is_dry_run=True,
                    analysis_duration=45,
                    slot_vars=[MagicMock()],
                    slot_queue=Queue(),
                    on_progress=app._on_progress,
                    # The window's own binding: the header is the run's, so a
                    # direct call would not prove the payload reaches it.
                    on_complete=lambda **kw: app._on_complete(
                        header=["MOOD DETECTION REPORT\n"], **kw
                    ),
                    on_error=app._on_error,
                )
        app._poll_ui_updates()

        with open(app._log_path, encoding="utf-8") as handle:
            report = handle.read()
        assert "SUMMARY:" in report
        assert "Tagged/Analyzed: 2" in report
        assert "Skipped (undecodable/silent): 1" in report
        assert "Time: 01:01" in report
        assert app.summary_label.config.call_args.kwargs["text"].startswith("Total: 3")


class TestOnCompleteReport:
    def _complete(self, app, **overrides) -> None:
        kwargs = {
            "header": ["H\n"],
            "total": 3,
            "processed": 3,
            "skipped": 1,
            "errors": 0,
            "duration_secs": 61.0,
            "log_entries": ["song.mp3 -> Energetic;Bright\n"],
        }
        kwargs.update(overrides)
        app._on_complete(**kwargs)
        app._poll_ui_updates()

    def _shell(self, tmp_path, run_mode="Dry Run"):
        app = _make_batch_app(tmp_path, run_mode=run_mode)
        app._log_path = str(tmp_path / "mood_dry_run_log.txt")
        return app

    def test_report_opens_with_the_mood_detection_header(self, tmp_path):
        app = _make_batch_app(tmp_path)
        on_complete = _run_and_capture_completion(app)
        on_complete(
            total=3,
            processed=3,
            skipped=2,
            errors=0,
            duration_secs=61.0,
            log_entries=["song.mp3 -> Energetic;Bright\n"],
        )
        app._poll_ui_updates()

        with open(app._log_path, encoding="utf-8") as handle:
            report = handle.read()
        assert report.startswith("MOOD DETECTION REPORT")
        assert "Mode: DRY RUN" in report
        assert "song.mp3 -> Energetic;Bright" in report

    def test_skipped_count_is_labelled_as_undecodable(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)

        with open(app._log_path, encoding="utf-8") as handle:
            assert "Skipped (undecodable/silent): 1" in handle.read()

    def test_summary_line_names_all_four_counts(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)

        text = app.summary_label.config.call_args.kwargs["text"]
        assert text == ("Total: 3 files\nTagged/Analyzed: 2\nSkipped: 1\nErrors: 0")

    def test_dry_run_completion_label(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)
        app._render_completion(61.0)

        assert (
            app.completion_label.config.call_args.kwargs["text"] == "Analysis Complete!"
        )

    def test_live_completion_label_is_mood_specific(self, tmp_path):
        app = self._shell(tmp_path, run_mode="Live Update")
        self._complete(app)
        app._render_completion(61.0)

        assert (
            app.completion_label.config.call_args.kwargs["text"]
            == "Mood Tagging Complete!"
        )

    def test_results_tab_is_shown_when_the_run_finishes(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)
        app._render_completion(61.0)

        app.notebook.select.assert_called_once_with(app.results_frame)

    def test_start_button_is_re_enabled_for_the_next_run(self, tmp_path):
        app = self._shell(tmp_path)
        self._complete(app)
        app._render_completion(61.0)

        app.start_btn.config.assert_called_once_with(state="normal")

    def test_the_progress_tick_writes_the_counters_and_the_line(self, tmp_path):
        app = self._shell(tmp_path)
        app._ui_updates.put(("progress", 3, 10, 1, 1, "song.mp3 -> Energetic"))
        app._poll_ui_updates()

        assert app.stats_label.config.call_args.kwargs["text"] == (
            "Processed: 3 | Skipped: 1 | Errors: 1"
        )
        app.file_listbox.insert.assert_called_once()


class TestOnCompleteAutoEnd:
    """The driver's Auto End flag must close the window and mark the report.

    Both halves are honoured — the CLI bool and the Setup-tab checkbox — and
    both are driven through the completion the processor publishes, so the
    port onto the shell cannot drop either.
    """

    def _shell(self, tmp_path, auto_end, checkbox):
        app = _make_batch_app(tmp_path)
        app._log_path = str(tmp_path / "mood_dry_run_log.txt")
        app.auto_end = auto_end
        app.auto_end_var = MagicMock(**{"get.return_value": checkbox})
        return app

    def _complete(self, app) -> None:
        on_complete = _run_and_capture_completion(app)
        on_complete(
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        app._poll_ui_updates()

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

    def test_the_driver_flag_writes_the_marker_too(self, tmp_path):
        """A driver launch never ticks the checkbox; its flag must mark the run."""
        app = self._shell(tmp_path, auto_end=True, checkbox=False)
        self._complete(app)

        with open(app._log_path, encoding="utf-8") as handle:
            report = handle.read()
        assert report.startswith("MOOD DETECTION REPORT")
        assert "Auto End enabled" in report


class TestStartProcessingValidation:
    def test_no_folder_warns(self):
        app = object.__new__(MoodAnalyzerApp)
        app.folder_path = MagicMock(**{"get.return_value": ""})
        with patch("audio_suite_shared.suite_app.messagebox") as mock_box:
            app.start_processing()
        mock_box.showwarning.assert_called_once()

    def test_invalid_path_errors(self):
        app = object.__new__(MoodAnalyzerApp)
        app.folder_path = MagicMock(**{"get.return_value": "C:/nope"})
        with patch("audio_suite_shared.suite_app.os.path.isdir", return_value=False):
            with patch("audio_suite_shared.suite_app.messagebox") as mock_box:
                app.start_processing()
        mock_box.showerror.assert_called_once()

    def test_valid_folder_starts_the_shell_worker(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch.object(MoodAnalyzerApp, "_start_worker") as start:
            app.start_processing()

        start.assert_called_once_with(app._run, ())

    def test_status_line_is_the_mood_detection_one(self, tmp_path):
        app = _make_batch_app(tmp_path)
        with patch.object(MoodAnalyzerApp, "_start_worker"):
            app.start_processing()

        app.overall_status.set.assert_called_once_with(
            "Detecting mood from the audio signal..."
        )

    def test_the_run_settings_are_snapshotted_on_the_tk_thread(self, tmp_path):
        app = _make_batch_app(tmp_path, run_mode="Live Update")
        with patch.object(MoodAnalyzerApp, "_start_worker"):
            app.start_processing()

        assert app._dir_path == str(tmp_path)
        assert app._is_dry_run is False
        assert app._analysis_seconds == 45
        assert app._parallel is True
        assert app._workers == 6


def test_module_exports_the_app_under_its_historical_name():
    """The launcher and the driver both import ``mood_analyzer.MoodAnalyzerApp``."""
    import mood_analyzer

    assert mood_analyzer.MoodAnalyzerApp is MoodAnalyzerApp


@pytest.fixture
def real_app(root):
    """Factory building the real app on the live root, config/CLI stubbed.

    The shell parents the Help bar and the notebook on the shared root, so the
    fixture destroys exactly those two after each test.
    """
    baseline = set(root.winfo_children())

    def _make(parsed=None, last_directory="", load_value=None) -> MoodAnalyzerApp:
        if parsed is None:
            parsed = _make_parsed(folder_path="")
        with patch("audio_suite_shared.suite_app.bootstrap_tool_app") as bootstrap:
            bootstrap.return_value = (MagicMock(), None)

            def _load_default(_key: str, default: object) -> object:
                return default

            load = load_value if load_value is not None else _load_default
            with patch("mood_analyzer.app.suite_config") as config:
                config.load_value.side_effect = load
                config.load_last_directory.return_value = last_directory
                config.list_presets.return_value = []
                with patch("mood_analyzer.app.parse_cli", return_value=parsed):
                    with patch(
                        "mood_analyzer.app.was_launched_from_driver",
                        return_value=bool(parsed.folder_path),
                    ):
                        return MoodAnalyzerApp(root)

    yield _make

    for child in set(root.winfo_children()) - baseline:
        child.destroy()


@pytest.mark.gui
class TestRealConstruction:
    """The real window still builds on the shell, with its own panel."""

    def test_builds_all_three_tabs(self, real_app, root) -> None:
        app = real_app()
        assert [app.notebook.tab(i, "text") for i in range(3)] == list(app.tab_labels)

    def test_wires_the_widgets_the_run_path_uses(self, real_app, root) -> None:
        app = real_app()
        assert isinstance(app.start_btn, tk.Button)
        assert isinstance(app.progress, ttk.Progressbar)
        assert isinstance(app.file_listbox, tk.Listbox)
        assert isinstance(app.overall_status, tk.StringVar)
        assert isinstance(app.stats_label, tk.Label)
        assert isinstance(app.completion_label, tk.Label)
        assert isinstance(app.summary_label, tk.Label)
        assert app.controls_panel is not None

    def test_worker_slot_pool_starts_idle_and_full(self, real_app, root) -> None:
        app = real_app()
        workers = default_max_workers()
        assert [v.get() for v in app.slot_vars] == ["IDLE"] * workers
        assert sorted(app.slot_queue.queue) == list(range(workers))

    def test_the_duration_widget_starts_at_the_shared_value(self, real_app, root):
        app = real_app()
        assert app.analysis_duration.get() == DEFAULT_ANALYSIS_SECONDS

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


# ---------------------------------------------------------------------------
# Run note: the batch report's Mood step says how many tracks the run could
# not analyse, instead of leaving that only in the tool's own log.
# ---------------------------------------------------------------------------


def _make_run_note_app(log_path) -> MoodAnalyzerApp:
    """Shell with only what the completion path touches."""
    app = object.__new__(MoodAnalyzerApp)
    app.root = MagicMock()
    app._log_path = str(log_path)
    app.auto_end = False
    app.auto_end_var = MagicMock(**{"get.return_value": False})
    app._ui_updates = SimpleQueue()
    app._dir_path = str(log_path.parent)
    return app


def _complete(
    app: MoodAnalyzerApp, *, total: int, skipped: int = 0, errors: int = 0
) -> None:
    """Drive the completion callback the analysis actually hands over."""
    app._on_complete(
        header=["MOOD DETECTION REPORT\n"],
        total=total,
        processed=total,
        skipped=skipped,
        errors=errors,
        duration_secs=1.0,
        log_entries=["line\n"],
    )


class TestRunNote:
    """``_on_complete`` records the tracks the run could not analyse."""

    def test_skipped_tracks_are_reported(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "mood_log.txt")

        _complete(app, total=40, skipped=2)

        assert read_outcome("mood_analyzer") == (
            "2 of 40 tracks had no usable audio (undecodable or silent)"
        )

    def test_errors_are_reported_alongside_the_skips(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "mood_log.txt")

        _complete(app, total=40, skipped=2, errors=1)

        assert read_outcome("mood_analyzer") == (
            "2 of 40 tracks had no usable audio (undecodable or silent); "
            "1 of 40 tracks could not be analyzed"
        )

    def test_a_clean_run_reports_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "mood_log.txt")

        _complete(app, total=40)

        assert read_outcome("mood_analyzer") == ""

    def test_a_later_clean_run_clears_an_earlier_note(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_run_note_app(tmp_path / "mood_log.txt")
        _complete(app, total=4, skipped=1)
        assert read_outcome("mood_analyzer") == (
            "1 of 4 tracks had no usable audio (undecodable or silent)"
        )

        _complete(app, total=4)

        assert read_outcome("mood_analyzer") == ""


def test_no_widget_is_touched_from_the_worker_thread() -> None:
    """The three callbacks queue; the run writes no widget and no Tk variable.

    The port replaced ``root.after`` in every callback with a queue put, so a
    scan for a widget write in those bodies is what keeps it that way.
    """
    import inspect

    for name in ("_on_progress", "_on_complete", "_on_error"):
        source = inspect.getsource(getattr(MoodAnalyzerApp, name))
        assert "root.after" not in source, name
        assert ".config(" not in source, name
        assert ".set(" not in source, name
