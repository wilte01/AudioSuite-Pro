"""
test_app.py
Tests for app.py — MoodAnalysisBatchTaggerApp orchestration logic.

Uses the object.__new__ + MagicMock pattern (no real Tk window).

Changed in 1.4.0: covers the saved worker-count fallback resolving the shared
default instead of a literal (D67).
Changed in 1.4.0: covers a typed worker count above the slot grid being
capped (with a warning) before it is saved (D66).

Changed in 2.4.3: the two View Log cases patch the shared helper's namespace,
because ``_on_open_log`` now delegates to ``ui_helpers.open_log_file`` (D-19).

Changed in 2.9.0: the window composes ``SuiteApp``, so the tests read the
shell's widget names and its completion, which the stubbed ``root.after`` runs
for the 0 ms writes (C1 stage 2).

Changed in 2.9.0: the run starts through the shell's hand-off, so the message
cases drive ``_poll_ui_updates`` (the real pump) and the start cases patch the
shell's ``threading.Thread`` rather than the window's (D65).
"""

from __future__ import annotations

import queue
import tkinter
from unittest.mock import MagicMock, patch

from mood_analysis_batch_tagger.app import MoodAnalysisBatchTaggerApp

APP = "mood_analysis_batch_tagger.app"


def _after_zero(delay: object, callback: object = None, *args: object) -> object:
    """Run a ``root.after(0, ...)`` write now and leave later timers queued.

    The shell schedules its widget writes at 0 ms and the poller at 100 ms, so
    running only the former lets a test read the rendered completion without
    entering the polling loop.
    """
    if delay == 0 and callable(callback):
        return callback(*args)
    return None


def _make_app() -> MoodAnalysisBatchTaggerApp:
    app = object.__new__(MoodAnalysisBatchTaggerApp)
    app.root = MagicMock()
    app.root.after.side_effect = _after_zero
    app.root_path = MagicMock()
    app.run_mode = MagicMock()
    app.analysis_duration = MagicMock()
    app.parallel_mode = MagicMock()
    app.max_workers = MagicMock()
    app._safe_slot_vars = []
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()
    app._ui_updates = queue.SimpleQueue()
    app._run_root = ""
    app._run_live = False
    app._run_duration = 90
    app._run_parallel = False
    app._run_workers = 1
    app._tagged_count = 0
    app._skipped_count = 0
    app._error_count = 0
    app._folder_count = 0
    app._log_path = ""
    app._out_dir = ""
    app._run_started = 0.0
    # The shell's Processing and Results widgets.
    app.progress = MagicMock()
    app.stats_label = MagicMock()
    app.file_listbox = MagicMock()
    app.overall_status = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.time_label = MagicMock()
    app.start_btn = MagicMock()
    app.notebook = MagicMock()
    app.processing_frame = MagicMock()
    app.results_frame = MagicMock()
    app.slot_vars = []
    app.auto_end = False
    return app


class TestOnDone:
    def _app(self) -> MoodAnalysisBatchTaggerApp:
        return _make_app()

    def test_re_enables_start_button(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        app.start_btn.config.assert_called_with(state="normal")

    def test_sets_progress_to_100(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        app.progress.__setitem__.assert_any_call("value", 100)

    def test_sets_overall_status_complete(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        app.overall_status.set.assert_called_with("Complete.")

    def test_summary_includes_errors(self) -> None:
        app = self._app()
        app._on_done(tagged=10, skipped=3, errors=2, folders=7)
        call_kwargs = app.summary_label.config.call_args
        text = call_kwargs[1]["text"]
        assert "Folders scanned: 7" in text
        assert "Files analysed:  15" in text
        assert "Files tagged:    10" in text
        assert "Files skipped:   3" in text
        assert "Errors:          2" in text

    def test_completion_label_text(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        app.completion_label.config.assert_called_once_with(
            text="Batch Mood Analysis Complete!"
        )

    def test_switches_to_results_tab(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        app.notebook.select.assert_called_once_with(app.results_frame)

    def test_auto_end_schedules_destroy(self) -> None:
        app = self._app()
        app.auto_end_var.get.return_value = True
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        calls = [c.args for c in app.root.after.call_args_list]
        assert (1500, app.root.destroy) in calls

    def test_no_auto_end_no_destroy(self) -> None:
        app = self._app()
        app.auto_end_var.get.return_value = False
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        calls = [c.args for c in app.root.after.call_args_list]
        assert all(c[1] is not app.root.destroy for c in calls)

    def test_auto_end_attribute_schedules_destroy(self) -> None:
        app = self._app()
        app.auto_end = True
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        calls = [c.args for c in app.root.after.call_args_list]
        assert (1500, app.root.destroy) in calls


class TestCollectSettings:
    def test_returns_full_dict(self) -> None:
        app = _make_app()
        app.root_path.get.return_value = "C:/Music"
        app.run_mode.get.return_value = "Live Update"
        app.analysis_duration.get.return_value = 45
        app.parallel_mode.get.return_value = True
        app.max_workers.get.return_value = 8
        assert app._collect_settings() == {
            "root_path": "C:/Music",
            "run_mode": "Live Update",
            "analysis_duration": 45,
            "parallel_mode": True,
            "max_workers": 8,
        }


class TestApplyPreset:
    def test_sets_all_present_keys(self) -> None:
        app = _make_app()
        app._apply_preset(
            {
                "root_path": "C:/Music",
                "run_mode": "Dry Run",
                "analysis_duration": 60,
                "parallel_mode": True,
                "max_workers": 2,
            }
        )
        app.root_path.set.assert_called_once_with("C:/Music")
        app.run_mode.set.assert_called_once_with("Dry Run")
        app.analysis_duration.set.assert_called_once_with(60)
        app.parallel_mode.set.assert_called_once_with(True)
        app.max_workers.set.assert_called_once_with(2)

    def test_ignores_missing_key(self) -> None:
        app = _make_app()
        app._apply_preset({})
        app.root_path.set.assert_not_called()
        app.run_mode.set.assert_not_called()
        app.analysis_duration.set.assert_not_called()
        app.parallel_mode.set.assert_not_called()
        app.max_workers.set.assert_not_called()

        app._apply_preset({"run_mode": "Dry Run"})

        app.run_mode.set.assert_called_once_with("Dry Run")

    def test_extra_keys_ignored(self) -> None:
        app = _make_app()
        app._apply_preset({"run_mode": "Live Update", "unknown": 42})
        app.run_mode.set.assert_called_once_with("Live Update")


class TestUpdateStats:
    def test_zero_counts(self) -> None:
        app = _make_app()
        app._update_stats()
        app.stats_label.config.assert_called_once_with(
            text="Folders: 0 | Tagged: 0 | Skipped: 0 | Errors: 0"
        )

    def test_nonzero_counts(self) -> None:
        app = _make_app()
        app._folder_count = 12
        app._tagged_count = 45
        app._skipped_count = 3
        app._error_count = 2
        app._update_stats()
        app.stats_label.config.assert_called_once_with(
            text="Folders: 12 | Tagged: 45 | Skipped: 3 | Errors: 2"
        )


class TestOnStart:
    def test_no_root_shows_warning(self) -> None:
        app = _make_app()
        app.root_path.get.return_value = ""
        with patch(f"{APP}.platform_utils") as mock_platform:
            app._on_start()
        mock_platform.messagebox.showwarning.assert_called_once()
        app.start_btn.config.assert_not_called()

    def test_missing_directory_shows_error(self, tmp_path) -> None:
        app = _make_app()
        app.root_path.get.return_value = str(tmp_path / "not_here")
        with patch(f"{APP}.platform_utils") as mock_platform:
            app._on_start()
        mock_platform.messagebox.showerror.assert_called_once()
        app.start_btn.config.assert_not_called()

    def test_valid_directory_starts_worker(self, tmp_path) -> None:
        app = _make_app()
        app.root_path.get.return_value = str(tmp_path)
        app.run_mode.get.return_value = "Live Update"
        app.analysis_duration.get.return_value = 90
        app.parallel_mode.get.return_value = False
        app.max_workers.get.return_value = 4

        with (
            patch(f"{APP}.save_run_mode"),
            patch(f"{APP}.suite_config") as mock_config,
            patch(f"{APP}.active_batch") as mock_active_batch,
            patch(f"{APP}.batch_analysis_engine") as mock_engine,
            patch("audio_suite_shared.suite_app.threading.Thread") as mock_thread,
        ):
            app._on_start()

            mock_config.save_last_directory.assert_called_once_with(str(tmp_path))
            app.start_btn.config.assert_called_once_with(state="disabled")
            app.notebook.select.assert_called_once_with(app.processing_frame)

            mock_thread.assert_called_once()
            thread_kwargs = mock_thread.call_args.kwargs
            assert thread_kwargs["daemon"] is True
            assert thread_kwargs["args"] == ()
            worker = thread_kwargs["target"]
            worker(*thread_kwargs["args"])
            mock_active_batch.assert_called_once_with(
                "mood_analysis_batch_tagger", "tag_edit"
            )
            assert mock_engine.run_batch.call_count == 1
            run_kwargs = mock_engine.run_batch.call_args.kwargs
            assert run_kwargs["live"] is True
            assert run_kwargs["root"] == str(tmp_path)
            assert run_kwargs["out_queue"] is app._ui_updates
            app.root.after.assert_called_once_with(100, app._poll_ui_updates)

    def test_dry_run_sets_live_false(self, tmp_path) -> None:
        app = _make_app()
        app.root_path.get.return_value = str(tmp_path)
        app.run_mode.get.return_value = "Dry Run"
        app.analysis_duration.get.return_value = 30
        app.parallel_mode.get.return_value = True
        app.max_workers.get.return_value = 2

        with (
            patch(f"{APP}.save_run_mode"),
            patch(f"{APP}.suite_config"),
            patch(f"{APP}.active_batch"),
            patch(f"{APP}.batch_analysis_engine") as mock_engine,
            patch("audio_suite_shared.suite_app.threading.Thread") as mock_thread,
        ):
            app._on_start()

            thread_kwargs = mock_thread.call_args.kwargs
            thread_kwargs["target"](*thread_kwargs["args"])
            run_kwargs = mock_engine.run_batch.call_args.kwargs
            assert run_kwargs["live"] is False
            assert run_kwargs["analysis_duration"] == 30
            assert run_kwargs["parallel_mode"] is True
            assert run_kwargs["max_workers"] == 2


class TestDispatchUiMessage:
    """One message at a time, rendered through the shell's poller."""

    def _render(self, msgs: list[tuple]) -> MoodAnalysisBatchTaggerApp:
        app = _make_app()
        app._on_done = MagicMock()  # type: ignore[method-assign]
        for msg in msgs:
            app._ui_updates.put(msg)
        app._poll_ui_updates()
        return app

    def test_folder_message(self) -> None:
        app = self._render([("folder", "/music/sub", 3, 2)])
        app.file_listbox.insert.assert_called_with(
            tkinter.END, "\u25b6  /music/sub  (3 files)"
        )
        app.overall_status.set.assert_called_with("Scanning: /music/sub")

    def test_progress_message(self) -> None:
        app = self._render([("progress", 5, 10, "track.mp3")])
        app.progress.__setitem__.assert_any_call("value", 50.0)
        app.overall_status.set.assert_called_with("Processing: track.mp3")

    def test_result_success(self) -> None:
        app = self._render(
            [("result", "/m/a.mp3", "a.mp3", True, "Energetic (conf 0.87)")]
        )
        assert app._tagged_count == 1
        app.file_listbox.insert.assert_called_with(
            tkinter.END, "    OK   a.mp3  ->  Energetic (conf 0.87)"
        )

    def test_result_skip(self) -> None:
        app = self._render([("result", "/m/b.flac", "b.flac", False, "cannot decode")])
        assert app._skipped_count == 1

    def test_slot_message_updates_slot_var(self) -> None:
        app = _make_app()
        app.slot_vars = [MagicMock() for _ in range(4)]
        app._ui_updates.put(("slot", 2, "Analyzing: a.mp3"))
        app._poll_ui_updates()
        app.slot_vars[2].set.assert_called_once_with("Analyzing: a.mp3")

    def test_slot_message_ignores_out_of_range_index(self) -> None:
        app = _make_app()
        app.slot_vars = [MagicMock() for _ in range(4)]
        app._ui_updates.put(("slot", 9, "Analyzing: a.mp3"))
        app._poll_ui_updates()
        for var in app.slot_vars:
            var.set.assert_not_called()

    def test_done_message_renders_the_completion(self) -> None:
        app = self._render([("done", 5, 2, 1, 3, "/m/a.log")])
        app._on_done.assert_called_once_with(5, 2, 1, 3)
        assert app._tagged_count == 5
        assert app._log_path == "/m/a.log"

    def test_error_message_shows_the_failure(self) -> None:
        app = _make_app()
        app._ui_updates.put(("error", "The batch failed."))
        with patch("audio_suite_shared.suite_app.messagebox") as messagebox:
            app._poll_ui_updates()
        messagebox.showerror.assert_called_once_with("Error", "The batch failed.")
        app.start_btn.config.assert_called_with(state="normal")

    def test_mixed_messages_processed_in_order(self) -> None:
        app = self._render(
            [
                ("folder", "/music/sub", 2, 1),
                ("progress", 1, 2, "a.mp3"),
                ("result", "/music/sub/a.mp3", "a.mp3", True, "Calm (conf 0.9)"),
                ("done", 1, 0, 0, 1, "/music/sub/a.log"),
            ]
        )
        app._on_done.assert_called_once_with(1, 0, 0, 1)
        assert app._folder_count == 1
        assert app._tagged_count == 1


class TestRunBatch:
    """The run's thread publishes on the shell's queue and reports a crash."""

    def test_slots_ride_the_shell_queue(self) -> None:
        app = _make_app()
        app._run_root = "C:/Music"
        with (
            patch(f"{APP}.active_batch"),
            patch(f"{APP}.batch_analysis_engine") as mock_engine,
        ):
            app._run_batch()

        kwargs = mock_engine.run_batch.call_args.kwargs
        assert kwargs["root"] == "C:/Music"
        assert kwargs["out_queue"] is app._ui_updates
        kwargs["on_worker_status"](2, "Analyzing: a.mp3")
        assert app._ui_updates.get_nowait() == ("slot", 2, "Analyzing: a.mp3")

    def test_a_finished_run_queues_nothing_else(self) -> None:
        app = _make_app()
        with (
            patch(f"{APP}.active_batch"),
            patch(f"{APP}.batch_analysis_engine") as mock_engine,
        ):
            app._run_batch()
        assert mock_engine.run_batch.called
        assert app._ui_updates.empty()

    def test_a_swallowed_failure_is_reported(self) -> None:
        app = _make_app()
        with (
            patch(f"{APP}.active_batch"),
            patch(f"{APP}.batch_analysis_engine") as mock_engine,
        ):
            mock_engine.run_batch.return_value = None
            app._run_batch()
        assert app._ui_updates.get_nowait() == (
            "error",
            "The batch failed. See the log for details.",
        )


class TestApplyCliArgs:
    def test_applies_parsed_arguments(self, tmp_path) -> None:
        from mood_analysis_batch_tagger.utils.cli_args import (
            MoodAnalysisBatchTaggerArgs,
        )

        parsed = MoodAnalysisBatchTaggerArgs(
            folder_path=str(tmp_path),
            live_mode=True,
            auto_start=False,
            auto_end=True,
            clear_logs=True,
            parallel_run=True,
            analysis_duration=45,
            parallel_mode=True,
            max_workers=8,
        )
        app = _make_app()
        with patch(f"{APP}.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.root_path.set.assert_called_once_with(str(tmp_path))
        app.run_mode.set.assert_any_call("Live Update")
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)
        app.analysis_duration.set.assert_called_once_with(45)
        app.parallel_mode.set.assert_called_once_with(True)
        app.max_workers.set.assert_called_once_with(8)
        assert app.auto_end is True
        app.root.after.assert_not_called()

    def test_no_folder_path_is_noop(self, tmp_path) -> None:
        app = _make_app()
        with patch(f"{APP}.cli_args.parse") as mock_parse:
            mock_parse.return_value.folder_path = ""
            app._apply_cli_args()
            app.root_path.set.assert_not_called()
            app.root.after.assert_not_called()
            mock_parse.return_value.folder_path = str(tmp_path)
            app._apply_cli_args()
        app.root_path.set.assert_called_once_with(str(tmp_path))

    def test_auto_start_schedules_start(self, tmp_path) -> None:
        from mood_analysis_batch_tagger.utils.cli_args import (
            MoodAnalysisBatchTaggerArgs,
        )

        parsed = MoodAnalysisBatchTaggerArgs(folder_path=str(tmp_path), auto_start=True)
        app = _make_app()
        with patch(f"{APP}.cli_args.parse", return_value=parsed):
            app._apply_cli_args()
        app.root.after.assert_called_once_with(1500, app._on_start)


class TestSavedWorkerCount:
    """A corrupt or missing saved worker count falls back to the default."""

    def test_keeps_a_valid_saved_count(self) -> None:
        from mood_analysis_batch_tagger.app import _saved_worker_count

        assert _saved_worker_count(3) == 3

    def test_corrupt_value_resolves_the_shared_default(self) -> None:
        from audio_suite_shared.constants import default_max_workers
        from mood_analysis_batch_tagger.app import _saved_worker_count

        assert _saved_worker_count("junk") == default_max_workers()
        assert _saved_worker_count(None) == default_max_workers()

    def test_non_positive_or_bool_value_resolves_the_default(self) -> None:
        from audio_suite_shared.constants import default_max_workers
        from mood_analysis_batch_tagger.app import _saved_worker_count

        assert _saved_worker_count(0) == default_max_workers()
        assert _saved_worker_count(True) == default_max_workers()


class TestOnDurationChange:
    def test_applies_saved_duration(self) -> None:
        app = _make_app()
        with patch(f"{APP}.suite_config") as mock_config:
            mock_config.load_value.return_value = 60
            app._on_duration_change()
        app.analysis_duration.set.assert_called_once_with(60)

    def test_ignores_non_int_saved_value(self) -> None:
        app = _make_app()
        with patch(f"{APP}.suite_config") as mock_config:
            mock_config.load_value.return_value = "junk"
            app._on_duration_change()
            app.analysis_duration.set.assert_not_called()
        mock_config.load_value.assert_called_once_with(
            "mood_analysis_batch_duration", 90
        )


class _WorkerVarStub:
    """Minimal tk.IntVar stand-in that reflects ``set()`` back into ``get()``."""

    def __init__(self, value: int) -> None:
        self.value = value

    def get(self) -> int:
        return self.value

    def set(self, value: int) -> None:
        self.value = value


class TestTypedWorkersAboveTheSlotGrid:
    """A typed count above the grid is capped before the run is persisted."""

    def test_caps_and_saves_the_slot_count(self, tmp_path) -> None:
        app = _make_app()
        app._safe_slot_vars = [MagicMock() for _ in range(4)]
        app.max_workers = _WorkerVarStub(12)
        app.root_path.get.return_value = str(tmp_path)
        app.run_mode.get.return_value = "Live Update"
        app.analysis_duration.get.return_value = 30
        app.parallel_mode.get.return_value = True

        with (
            patch(f"{APP}.save_run_mode"),
            patch(f"{APP}.suite_config") as mock_config,
            patch(f"{APP}.active_batch"),
            patch(f"{APP}.batch_analysis_engine") as mock_engine,
            patch("audio_suite_shared.suite_app.threading.Thread") as mock_thread,
            patch("audio_suite_shared.ui_common.messagebox") as warnings,
        ):
            app._on_start()

            assert app.max_workers.get() == 4
            mock_config.save_value.assert_any_call("mood_analysis_batch_max_workers", 4)
            warnings.showwarning.assert_called_once()

            thread_kwargs = mock_thread.call_args.kwargs
            thread_kwargs["target"](*thread_kwargs["args"])
            assert mock_engine.run_batch.call_args.kwargs["max_workers"] == 4
