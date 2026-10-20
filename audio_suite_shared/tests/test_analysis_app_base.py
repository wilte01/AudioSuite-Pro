"""
Tests for audio_suite_shared.analysis_app_base — the shared GUI scaffold.

The base owns everything the two in-place analysis tools (Key Detector and
Mood Analyzer) used to each carry: the run dispatch, the report writer, the
progress/error callbacks, the preset round-trip and the input validation.
These tests exercise that machinery **once**, against a minimal concrete
subclass, so a change to the shared code cannot break one tool while the
other's tests stay green.

The per-tool wiring (which literals, which ``file_processor``) is asserted in
each tool's own ``tests/test_app.py``.

Changed in 1.4.0: `start_processing` and `_run_batch` cap a typed worker count
at the slot grid (D66).
"""

import logging
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.analysis_app_base import AnalysisAppBase
from audio_suite_shared.constants import default_max_workers

CAPTURED: dict = {}


class _AbstractTool(AnalysisAppBase):
    """Declares the whole per-tool contract but supplies no analysis hook.

    The Tk bootstrap in the real ``__init__`` is not exercised here — the tools'
    own end-to-end launches cover it — so this subclass replaces it with a
    no-arg constructor and leaves ``_run``/``_run_analysis`` unimplemented.
    """

    TOOL_ID = "fake_tool"
    APP_TITLE = "Fake Tool"
    WINDOW_NAME = "fake_tool_window"
    HELP_GUIDE = "Fake_Tool_User_Guide.docx"

    SETTINGS_PREFIX = "fake"
    STARTING_STATUS = "Doing the thing..."
    REPORT_HEADER = "FAKE REPORT"
    SKIPPED_SUMMARY_LABEL = "Skipped (for a fake reason)"
    LIVE_COMPLETION_TEXT = "Fake Tagging Complete!"

    SETUP_TAB = MagicMock()
    PROCESSING_TAB = MagicMock()
    RESULTS_TAB = MagicMock()
    CLI_ARGS = MagicMock()

    def __init__(self) -> None:
        """Skip the real Tk bootstrap; every test drives the shell directly."""


class _FakeTool(_AbstractTool):
    """The complete tool every behavioural test runs against."""

    def _run(self) -> None:
        self._run_batch()

    def _run_analysis(self, run_kwargs: dict) -> None:
        CAPTURED.clear()
        CAPTURED.update(run_kwargs)


@pytest.fixture(autouse=True)
def _reset_capture():
    """Keep the module-level capture dict from leaking between tests."""
    CAPTURED.clear()
    yield
    CAPTURED.clear()


def _make_app(
    run_mode: str = "Dry Run",
    auto_end: bool = False,
    folder: str = "C:/music",
) -> _FakeTool:
    """Build a display-free shell holding every field the base touches."""
    app = _FakeTool()
    app.root = MagicMock()
    app.folder_path = MagicMock(**{"get.return_value": folder})
    app.run_mode = MagicMock(**{"get.return_value": run_mode})
    app.analysis_duration = MagicMock(**{"get.return_value": 45})
    app.parallel_mode = MagicMock(**{"get.return_value": True})
    app.max_workers = MagicMock(**{"get.return_value": default_max_workers()})
    app.slot_queue = MagicMock()
    app._safe_slot_vars = [MagicMock() for _ in range(default_max_workers())]
    app.progress = {}
    app.auto_end = auto_end
    app.auto_end_var = MagicMock(**{"get.return_value": False})
    app.start_btn = MagicMock()
    app.file_listbox = MagicMock()
    app.notebook = MagicMock()
    app.overall_status = MagicMock()
    app._tab_processing = MagicMock()
    app._tab_results = MagicMock()
    return app


def _run_batch(app: AnalysisAppBase) -> None:
    """Drive the batch entry point with the undo-batch context neutralised."""
    with patch("audio_suite_shared.analysis_app_base.active_batch"):
        app._run_batch()


class TestPerToolContract:
    """The base must refuse to guess a tool's analysis entry points."""

    def test_run_analysis_is_abstract(self):
        with pytest.raises(NotImplementedError, match="_run_analysis"):
            _AbstractTool()._run_analysis({})

    def test_abstract_error_names_the_subclass(self):
        with pytest.raises(NotImplementedError, match="_AbstractTool"):
            _AbstractTool()._run_analysis({})

    def test_run_is_abstract_until_a_subclass_overrides_it(self):
        with pytest.raises(NotImplementedError, match="_AbstractTool"):
            _AbstractTool()._run()

    def test_setting_key_is_namespaced_by_prefix(self):
        app = _AbstractTool()
        assert app._setting_key("parallel_mode") == "fake_parallel_mode"
        assert app._setting_key("max_workers") == "fake_max_workers"

    def test_dry_run_completion_text_is_shared(self):
        assert _AbstractTool.DRY_RUN_COMPLETION_TEXT == "Analysis Complete!"


class TestRunBatchWiring:
    """``_run_batch`` assembles the call; ``_run_analysis`` is the only hook."""

    def test_dispatches_every_run_parameter(self):
        app = _make_app()
        _run_batch(app)

        assert CAPTURED["dir_path"] == "C:/music"
        assert CAPTURED["is_dry_run"] is True
        assert CAPTURED["analysis_duration"] == 45
        assert CAPTURED["parallel_mode"] is True
        assert CAPTURED["max_workers"] == default_max_workers()
        assert CAPTURED["slot_vars"] == app._safe_slot_vars
        assert CAPTURED["slot_queue"] is app.slot_queue
        assert CAPTURED["on_progress"] == app._on_progress
        assert CAPTURED["on_error"] == app._on_error

    def test_live_mode_flag_is_inverted(self):
        _run_batch(_make_app(run_mode="Live Update"))
        assert CAPTURED["is_dry_run"] is False

    def test_opens_an_undo_batch_for_the_tool_id(self):
        with patch("audio_suite_shared.analysis_app_base.active_batch") as mock_batch:
            _make_app()._run_batch()
        mock_batch.assert_called_once_with("fake_tool", "tag_edit")

    def test_analysis_runs_inside_the_undo_batch(self):
        """The analysis must be the statement inside the ``active_batch`` block.

        Recording context-manager entry/exit against the analysis call proves
        the batch is not closed before the tags are written, and that a tool
        cannot leak a tag edit outside the undo window.
        """
        order: list[str] = []

        class _OrderedTool(_FakeTool):
            def _run_analysis(self, run_kwargs: dict) -> None:
                order.append("analysis")

        class _OrderRecordingCM:
            def __enter__(self):
                order.append("enter")
                return self

            def __exit__(self, *exc_info: object) -> None:
                order.append("exit")

        tool = _OrderedTool()
        tool.__dict__.update(_make_app().__dict__)
        with patch(
            "audio_suite_shared.analysis_app_base.active_batch",
            return_value=_OrderRecordingCM(),
        ):
            tool._run_batch()

        assert order == ["enter", "analysis", "exit"]

    def test_progress_bar_is_reset(self):
        app = _make_app()
        _run_batch(app)
        assert app.progress["value"] == 0

    def test_log_path_uses_prefixed_dry_run_name(self):
        app = _make_app()
        _run_batch(app)
        assert app._log_path.endswith("fake_dry_run_log.txt")

    def test_log_path_uses_prefixed_sync_name_for_live(self):
        app = _make_app(run_mode="Live Update")
        _run_batch(app)
        assert app._log_path.endswith("fake_sync_log.txt")

    def test_dir_path_is_retained_for_the_results_tab(self):
        app = _make_app()
        _run_batch(app)
        assert app._dir_path == "C:/music"

    def test_completion_callback_carries_the_report_header(self, tmp_path):
        """The base builds the header and injects it, so the report opens with it."""
        app = _make_app(folder=str(tmp_path))
        _run_batch(app)

        CAPTURED["on_complete"](
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )

        with open(app._log_path, encoding="utf-8") as handle:
            report = handle.read()
        assert report.startswith("FAKE REPORT")
        assert "Mode: DRY RUN" in report
        assert "Analysis Duration: 45 seconds" in report


class TestOnCompleteReport:
    """The report writer is the tool's user-visible artefact."""

    def _complete(self, app: AnalysisAppBase, **overrides) -> None:
        kwargs = {
            "header": ["H\n"],
            "total": 4,
            "processed": 4,
            "skipped": 1,
            "errors": 1,
            "duration_secs": 95.0,
            "log_entries": ["entry\n"],
        }
        kwargs.update(overrides)
        app._on_complete(**kwargs)

    def _report(self, app: AnalysisAppBase) -> str:
        with open(app._log_path, encoding="utf-8") as handle:
            return handle.read()

    def test_writes_header_entries_and_summary(self, tmp_path):
        app = _make_app()
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app)

        report = self._report(app)
        assert "H" in report
        assert "entry" in report
        assert "SUMMARY:" in report
        assert "Total files: 4" in report
        assert "Errors: 1" in report

    def test_analysed_excludes_skipped_and_errors(self, tmp_path):
        """``Tagged/Analyzed`` is what actually got touched, not the raw count."""
        app = _make_app()
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app, total=4, processed=4, skipped=1, errors=1)
        assert "Tagged/Analyzed: 2" in self._report(app)

    def test_tool_specific_completion_fields_are_tolerated(self, tmp_path):
        """BPM passes ``skipped_files``; the shared report writer ignores it."""
        app = _make_app()
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app, skipped_files=[{"filename": "noise.wav"}])
        assert "SUMMARY:" in self._report(app)

    def test_uses_the_tools_own_skipped_wording(self, tmp_path):
        """The two tools legitimately disagree on what a skip means."""
        app = _make_app()
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app)
        assert "Skipped (for a fake reason): 1" in self._report(app)

    def test_elapsed_time_is_formatted_as_minutes_and_seconds(self, tmp_path):
        app = _make_app()
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app, duration_secs=95.0)
        assert "Time: 01:35" in self._report(app)

    def test_ui_update_is_scheduled_on_the_main_thread(self, tmp_path):
        app = _make_app()
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app)

        scheduled = [(c_.args[0], c_.args[1]) for c_ in app.root.after.call_args_list]
        assert (0, app._update_ui_on_complete) in scheduled

    def test_ui_receives_the_analysed_count_not_processed(self, tmp_path):
        app = _make_app()
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app, total=4, processed=4, skipped=1, errors=1)

        call_ = next(
            c_
            for c_ in app.root.after.call_args_list
            if c_.args[1] == app._update_ui_on_complete
        )
        assert call_.args[2:5] == (4, 2, 1)

    def test_unwritable_log_path_does_not_kill_the_run(self, tmp_path):
        """A failed report write is logged, never raised on the worker thread."""
        app = _make_app()
        app._log_path = str(tmp_path / "no-such-dir" / "report.txt")
        self._complete(app)

        assert any(
            c_.args[1] == app._update_ui_on_complete
            for c_ in app.root.after.call_args_list
        )


class TestOnCompleteAutoEnd:
    """Auto End fires from the CLI bool *or* the standalone checkbox."""

    def _complete(self, app: AnalysisAppBase) -> None:
        app._on_complete(
            header=["H\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=["x\n"],
        )

    def _closes(self, app: AnalysisAppBase) -> bool:
        return any(c_.args[0] == 2000 for c_ in app.root.after.call_args_list)

    def test_checkbox_alone_closes(self, tmp_path):
        app = _make_app()
        app.auto_end_var.get.return_value = True
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app)
        assert self._closes(app)

    def test_cli_bool_alone_closes(self, tmp_path):
        app = _make_app(auto_end=True)
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app)
        assert self._closes(app)

    def test_neither_leaves_the_window_open(self, tmp_path):
        app = _make_app()
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app)
        assert not self._closes(app)

    def test_marker_is_appended_to_the_report(self, tmp_path):
        app = _make_app()
        app.auto_end_var.get.return_value = True
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app)

        with open(app._log_path, encoding="utf-8") as handle:
            assert "Auto End enabled" in handle.read()

    def test_closing_schedules_root_destroy(self, tmp_path):
        app = _make_app()
        app.auto_end_var.get.return_value = True
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        self._complete(app)

        assert any(
            c_.args[0] == 2000 and c_.args[1] is app.root.destroy
            for c_ in app.root.after.call_args_list
        )


class TestUpdateUiOnComplete:
    """Completion text is the one genuinely per-tool user-visible string."""

    def _shell(self, run_mode: str) -> _FakeTool:
        app = _make_app(run_mode=run_mode)
        app.completion_label = MagicMock()
        app.time_label = MagicMock()
        app.summary_label = MagicMock()
        return app

    def test_dry_run_shows_the_shared_text(self):
        app = self._shell("Dry Run")
        app._update_ui_on_complete(4, 2, 1, 1, 1, 35)
        assert (
            app.completion_label.config.call_args.kwargs["text"] == "Analysis Complete!"
        )

    def test_live_run_shows_the_tools_own_text(self):
        app = self._shell("Live Update")
        app._update_ui_on_complete(4, 2, 1, 1, 1, 35)
        assert (
            app.completion_label.config.call_args.kwargs["text"]
            == "Fake Tagging Complete!"
        )

    def test_summary_is_split_across_lines(self):
        app = self._shell("Dry Run")
        app._update_ui_on_complete(4, 2, 1, 1, 1, 35)

        text = app.summary_label.config.call_args.kwargs["text"]
        assert text.splitlines() == [
            "Total: 4 files",
            "Tagged/Analyzed: 2",
            "Skipped: 1",
            "Errors: 1",
        ]

    def test_time_label_is_zero_padded(self):
        app = self._shell("Dry Run")
        app._update_ui_on_complete(1, 1, 0, 0, 2, 5)
        assert app.time_label.config.call_args.kwargs["text"] == "Total Time: 02:05"

    def test_results_tab_is_selected_and_start_is_re_enabled(self):
        app = self._shell("Dry Run")
        app._update_ui_on_complete(1, 1, 0, 0, 0, 1)

        app.notebook.select.assert_called_once_with(app._tab_results)
        app.start_btn.config.assert_called_once_with(state="normal")


class TestProgressCallback:
    """Progress arrives on worker threads and must be marshalled to Tk."""

    def test_marshals_onto_the_main_thread(self):
        app = _make_app()
        app._update_progress_ui = MagicMock()
        app._on_progress(1, 4, 1, 0, "file.mp3")

        app.root.after.assert_called_once_with(
            0, app._update_progress_ui, 1, 4, 1, 0, "file.mp3"
        )

    def test_updates_stats_and_appends_the_line(self):
        app = _make_app()
        app.stats_label = MagicMock()
        app._update_progress_ui(1, 4, 1, 0, "file.mp3")

        assert app.progress["maximum"] == 4
        assert app.progress["value"] == 1
        assert (
            app.stats_label.config.call_args.kwargs["text"]
            == "Processed: 1 | Skipped: 1 | Errors: 0"
        )
        app.file_listbox.insert.assert_called_once()


class TestErrorCallback:
    """Errors arrive on worker threads and must reach a Tk dialog."""

    def test_marshals_the_dialog_onto_the_main_thread(self):
        app = _make_app()
        app._on_error("boom")

        assert app.root.after.call_args.args[0] == 0
        assert app.root.after.call_args.args[1] == app._show_error

    def test_shows_the_error_and_re_enables_start(self):
        app = _make_app()
        with patch("audio_suite_shared.analysis_app_base.messagebox") as mock_box:
            app._show_error("boom")

        mock_box.showerror.assert_called_once_with("Error", "boom")
        app.start_btn.config.assert_called_once_with(state="normal")


class TestPresets:
    """Preset save/load round-trip is shared by both tools."""

    def test_collected_settings_cover_the_shared_controls(self):
        app = _make_app()
        app.folder_path = MagicMock(**{"get.return_value": "C:/songs"})
        app.run_mode = MagicMock(**{"get.return_value": "Live Update"})
        app.analysis_duration = MagicMock(**{"get.return_value": 30})
        app.parallel_mode = MagicMock(**{"get.return_value": False})
        app.max_workers = MagicMock(**{"get.return_value": 2})

        assert app._collect_settings() == {
            "folder_path": "C:/songs",
            "run_mode": "Live Update",
            "analysis_duration": 30,
            "parallel_mode": False,
            "max_workers": 2,
        }

    def test_applied_settings_are_written_back_to_every_var(self):
        app = _make_app()
        app._apply_preset(
            {
                "folder_path": "D:/other",
                "run_mode": "Live Update",
                "analysis_duration": 30,
                "parallel_mode": False,
                "max_workers": 2,
            }
        )

        app.folder_path.set.assert_called_once_with("D:/other")
        app.run_mode.set.assert_called_once_with("Live Update")
        app.analysis_duration.set.assert_called_once_with(30)
        app.parallel_mode.set.assert_called_once_with(False)
        app.max_workers.set.assert_called_once_with(2)

    def test_partial_preset_leaves_absent_keys_alone(self):
        app = _make_app()
        app._apply_preset({"analysis_duration": 15})

        app.analysis_duration.set.assert_called_once_with(15)
        app.folder_path.set.assert_not_called()

    def test_collect_then_apply_round_trips(self):
        app = _make_app()
        settings = app._collect_settings()
        app._apply_preset(settings)
        assert app._collect_settings() == settings

    def test_save_namespaces_the_preset_by_tool_id(self):
        app = _make_app()
        app._refresh_preset_list = MagicMock()
        with patch("audio_suite_shared.analysis_app_base._suite_config") as mock_cfg:
            app._save_current_as_preset("mine")

        args = mock_cfg.save_preset.call_args.args
        assert args[0] == "fake_tool"
        assert args[1] == "mine"
        assert args[2] == app._collect_settings()
        app._refresh_preset_list.assert_called_once_with(
            mock_cfg.list_presets.return_value
        )

    def test_delete_namespaces_the_preset_by_tool_id(self):
        app = _make_app()
        app._refresh_preset_list = MagicMock()
        with patch("audio_suite_shared.analysis_app_base._suite_config") as mock_cfg:
            app._delete_preset("mine")

        mock_cfg.delete_preset.assert_called_once_with("fake_tool", "mine")
        app._refresh_preset_list.assert_called_once_with(
            mock_cfg.list_presets.return_value
        )

    def test_selecting_a_missing_preset_is_a_no_op(self):
        app = _make_app()
        with patch(
            "audio_suite_shared.analysis_app_base._suite_config.load_preset",
            return_value=None,
        ) as mock_load:
            app._on_preset_selected("nope")
        mock_load.assert_called_once_with("fake_tool", "nope")
        app.folder_path.set.assert_not_called()

    def test_selecting_a_saved_preset_applies_it(self):
        app = _make_app()
        with patch(
            "audio_suite_shared.analysis_app_base._suite_config.load_preset",
            return_value={"analysis_duration": 11},
        ) as mock_load:
            app._on_preset_selected("mine")

        mock_load.assert_called_once_with("fake_tool", "mine")
        app.analysis_duration.set.assert_called_once_with(11)


class TestTypedWorkersAboveTheSlotGrid:
    """A typed count above the grid is capped, and the run stays error-free.

    Regression (D66): the Workers entry is free text while the slot grid is
    fixed at construction.  An uncapped pool handed slot indices past the grid
    to the progress write, so every file past it failed with ``IndexError``.
    """

    def test_start_processing_caps_and_persists_the_capped_count(self, tmp_path):
        app = _make_app(folder=str(tmp_path))
        app._safe_slot_vars = [MagicMock(), MagicMock()]
        app.max_workers = MagicMock(**{"get.return_value": 12})

        with (
            patch("audio_suite_shared.analysis_app_base._suite_config") as mock_cfg,
            patch("audio_suite_shared.analysis_app_base.threading"),
            patch("audio_suite_shared.ui_common.messagebox") as mock_box,
        ):
            app.start_processing()

        mock_box.showwarning.assert_called_once()
        app.max_workers.set.assert_called_once_with(2)
        mock_cfg.save_value.assert_any_call("fake_max_workers", 2)

    def test_driver_launch_caps_without_a_dialog(self, tmp_path, caplog):
        """A Master Driver / auto-start launch must never wait on a dialog."""
        app = _make_app(folder=str(tmp_path))
        app._safe_slot_vars = [MagicMock(), MagicMock()]
        app.max_workers = MagicMock(**{"get.return_value": 12})
        app._launched_from_driver = True

        with (
            patch("audio_suite_shared.analysis_app_base._suite_config") as mock_cfg,
            patch("audio_suite_shared.analysis_app_base.threading"),
            patch("audio_suite_shared.ui_common.messagebox") as mock_box,
            caplog.at_level(logging.WARNING),
        ):
            app.start_processing()

        mock_box.showwarning.assert_not_called()
        assert any("Workers limited" in record.message for record in caplog.records)
        app.max_workers.set.assert_called_once_with(2)
        mock_cfg.save_value.assert_any_call("fake_max_workers", 2)

    def test_a_fitting_count_is_not_warned_about(self, tmp_path):
        app = _make_app(folder=str(tmp_path))
        app._safe_slot_vars = [MagicMock() for _ in range(8)]
        app.max_workers = MagicMock(**{"get.return_value": 4})

        with (
            patch("audio_suite_shared.analysis_app_base._suite_config") as mock_cfg,
            patch("audio_suite_shared.analysis_app_base.threading"),
            patch("audio_suite_shared.ui_common.messagebox") as mock_box,
        ):
            app.start_processing()

        mock_box.showwarning.assert_not_called()
        app.max_workers.set.assert_not_called()
        mock_cfg.save_value.assert_any_call("fake_max_workers", 4)

    def test_run_batch_caps_workers_set_outside_start_processing(self):
        """A preset or CLI value must be capped even without the dialog."""
        app = _make_app()
        app._safe_slot_vars = [MagicMock(), MagicMock()]
        app.max_workers = MagicMock(**{"get.return_value": 9})

        _run_batch(app)

        assert CAPTURED["max_workers"] == 2


class TestStartProcessing:
    """Input validation and the hand-off onto the worker thread."""

    def test_no_folder_warns_and_stops(self):
        app = _make_app()
        app.folder_path = MagicMock(**{"get.return_value": ""})
        with patch("audio_suite_shared.analysis_app_base.messagebox") as mock_box:
            with patch("audio_suite_shared.analysis_app_base.threading") as threading:
                app.start_processing()

        mock_box.showwarning.assert_called_once()
        mock_box.showerror.assert_not_called()
        threading.Thread.assert_not_called()

    def test_non_directory_errors_and_stops(self):
        app = _make_app()
        app.folder_path = MagicMock(**{"get.return_value": "C:/nope"})
        with patch(
            "audio_suite_shared.analysis_app_base.os.path.isdir", return_value=False
        ):
            with patch("audio_suite_shared.analysis_app_base.messagebox") as mock_box:
                with patch(
                    "audio_suite_shared.analysis_app_base.threading"
                ) as threading:
                    app.start_processing()

        mock_box.showerror.assert_called_once()
        threading.Thread.assert_not_called()

    def test_valid_folder_persists_settings_and_starts_a_daemon_thread(self, tmp_path):
        app = _make_app()
        app.folder_path = MagicMock(**{"get.return_value": str(tmp_path)})
        with patch("audio_suite_shared.analysis_app_base._suite_config") as mock_cfg:
            with patch("audio_suite_shared.analysis_app_base.threading") as threading:
                app.start_processing()

        mock_cfg.save_value.assert_any_call("fake_parallel_mode", True)
        mock_cfg.save_value.assert_any_call("fake_max_workers", default_max_workers())
        threading.Thread.assert_called_once_with(target=app._run, daemon=True)
        threading.Thread.return_value.start.assert_called_once()

    def test_start_is_disabled_and_the_processing_tab_is_shown(self, tmp_path):
        app = _make_app()
        app.folder_path = MagicMock(**{"get.return_value": str(tmp_path)})
        with patch("audio_suite_shared.analysis_app_base._suite_config"):
            with patch("audio_suite_shared.analysis_app_base.threading"):
                app.start_processing()

        app.start_btn.config.assert_called_once_with(state="disabled")
        app.file_listbox.delete.assert_called_once_with(0, "end")
        app.notebook.select.assert_called_once_with(app._tab_processing)
        app.overall_status.set.assert_called_once_with("Doing the thing...")


class TestFolderAndHelpActions:
    """These tools process in place, so Open Folder targets the source."""

    def test_open_folder_targets_the_source_directory(self, tmp_path):
        app = _make_app()
        app.folder_path = MagicMock(**{"get.return_value": str(tmp_path)})
        with patch("audio_suite_shared.analysis_app_base.platform_utils") as platform:
            app._open_folder()
        platform.open_path.assert_called_once_with(str(tmp_path))

    def test_open_folder_reports_a_missing_directory(self):
        app = _make_app()
        app.folder_path = MagicMock(**{"get.return_value": "C:/gone"})
        with patch("audio_suite_shared.analysis_app_base.messagebox") as mock_box:
            app._open_folder()
        mock_box.showinfo.assert_called_once_with(
            "Folder", "Source folder not available."
        )

    def test_help_uses_the_tools_guide(self):
        app = _make_app()
        with patch.object(_FakeTool, "_open_help_standard") as mock_help:
            app._open_help()
        mock_help.assert_called_once_with("Fake_Tool_User_Guide.docx")

    def test_browse_folder_saves_the_last_directory(self):
        app = _make_app()
        with patch.object(_AbstractTool, "_browse_folder_standard") as mock_browse:
            app._browse_folder()
        mock_browse.assert_called_once_with(
            title="Select Music Directory",
            path_variable=app.folder_path,
            save_last_dir=True,
        )

    def test_open_log_targets_the_run_log(self, tmp_path):
        app = _make_app()
        app._log_path = str(tmp_path / "fake_dry_run_log.txt")
        with patch.object(_AbstractTool, "_open_log_standard") as mock_log:
            app._open_log()
        assert app._log_path.endswith("fake_dry_run_log.txt")
        mock_log.assert_called_once_with()


class TestAutoEndMarkerWriteFailure:
    """A failed second write must not stop the window from closing."""

    def test_window_still_closes_when_the_marker_cannot_be_written(self, tmp_path):
        app = _make_app()
        app.auto_end_var.get.return_value = True
        app._log_path = str(tmp_path / "no-such-dir" / "report.txt")

        app._on_complete(
            header=["H\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )

        assert any(c_.args[0] == 2000 for c_ in app.root.after.call_args_list)
