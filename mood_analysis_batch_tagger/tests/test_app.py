"""
test_app.py
Tests for app.py — MoodAnalysisBatchTaggerApp orchestration logic.

Uses the object.__new__ + MagicMock pattern (no real Tk window).

Changed in 1.4.0: covers the saved worker-count fallback resolving the shared
default instead of a literal (D67).
Changed in 1.4.0: covers a typed worker count above the slot grid being
capped (with a warning) before it is saved (D66).
"""

from __future__ import annotations

import queue
import tkinter
from unittest.mock import MagicMock, patch

from mood_analysis_batch_tagger.app import MoodAnalysisBatchTaggerApp

APP = "mood_analysis_batch_tagger.app"


def _make_app() -> MoodAnalysisBatchTaggerApp:
    app = object.__new__(MoodAnalysisBatchTaggerApp)
    app.root = MagicMock()
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
    app._queue = queue.Queue()
    app._running = False
    app._tagged_count = 0
    app._skipped_count = 0
    app._error_count = 0
    app._folder_count = 0
    app._log_path = ""
    app._start_btn = MagicMock()
    app._notebook = MagicMock()
    app._proc = {
        "file_listbox": MagicMock(),
        "progress": MagicMock(),
        "overall_status": MagicMock(),
        "stats_label": MagicMock(),
    }
    app._res = {
        "summary_label": MagicMock(),
        "completion_label": MagicMock(),
    }
    app.slot_vars = []
    app.auto_end = False
    return app


class TestOnDone:
    def _app(self) -> MoodAnalysisBatchTaggerApp:
        app = _make_app()
        app._running = True
        return app

    def test_sets_running_false(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        assert app._running is False

    def test_re_enables_start_button(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        app._start_btn.config.assert_called_with(state="normal")

    def test_sets_progress_to_100(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        app._proc["progress"].__setitem__.assert_any_call("value", 100)

    def test_sets_overall_status_complete(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        app._proc["overall_status"].set.assert_called_with("Complete.")

    def test_summary_includes_errors(self) -> None:
        app = self._app()
        app._on_done(tagged=10, skipped=3, errors=2, folders=7)
        call_kwargs = app._res["summary_label"].config.call_args
        text = call_kwargs[1]["text"]
        assert "Folders scanned: 7" in text
        assert "Files analysed:  15" in text
        assert "Files tagged:    10" in text
        assert "Files skipped:   3" in text
        assert "Errors:          2" in text

    def test_completion_label_text(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        app._res["completion_label"].config.assert_called_once_with(
            text="Batch Mood Analysis Complete!"
        )

    def test_switches_to_results_tab(self) -> None:
        app = self._app()
        app._on_done(tagged=5, skipped=2, errors=1, folders=3)
        app._notebook.select.assert_called_once_with(2)

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
        app._proc["stats_label"].config.assert_called_once_with(
            text="Folders: 0 | Tagged: 0 | Skipped: 0 | Errors: 0"
        )

    def test_nonzero_counts(self) -> None:
        app = _make_app()
        app._folder_count = 12
        app._tagged_count = 45
        app._skipped_count = 3
        app._error_count = 2
        app._update_stats()
        app._proc["stats_label"].config.assert_called_once_with(
            text="Folders: 12 | Tagged: 45 | Skipped: 3 | Errors: 2"
        )


class TestOnStart:
    def test_no_root_shows_warning(self) -> None:
        app = _make_app()
        app.root_path.get.return_value = ""
        with patch(f"{APP}.platform_utils") as mock_platform:
            app._on_start()
        mock_platform.messagebox.showwarning.assert_called_once()
        assert app._running is False

    def test_missing_directory_shows_error(self, tmp_path) -> None:
        app = _make_app()
        app.root_path.get.return_value = str(tmp_path / "not_here")
        with patch(f"{APP}.platform_utils") as mock_platform:
            app._on_start()
        mock_platform.messagebox.showerror.assert_called_once()
        assert app._running is False

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
            patch(f"{APP}.threading.Thread") as mock_thread,
            patch(f"{APP}.batch_analysis_engine") as mock_engine,
        ):
            app._on_start()

            mock_config.save_last_directory.assert_called_once_with(str(tmp_path))
            assert app._running is True
            app._start_btn.config.assert_called_once_with(state="disabled")
            app._notebook.select.assert_called_once_with(1)

            mock_thread.assert_called_once()
            thread_kwargs = mock_thread.call_args.kwargs
            assert thread_kwargs["daemon"] is True
            worker = thread_kwargs["target"]
            worker()
            mock_active_batch.assert_called_once_with(
                "mood_analysis_batch_tagger", "tag_edit"
            )
            assert mock_engine.run_batch.call_count == 1
            run_kwargs = mock_engine.run_batch.call_args.kwargs
            assert run_kwargs["live"] is True
            assert run_kwargs["root"] == str(tmp_path)
            app.root.after.assert_called_once_with(100, app._poll_queue)

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
            patch(f"{APP}.threading.Thread") as mock_thread,
            patch(f"{APP}.batch_analysis_engine") as mock_engine,
        ):
            app._on_start()

            worker = mock_thread.call_args.kwargs["target"]
            worker()
            run_kwargs = mock_engine.run_batch.call_args.kwargs
            assert run_kwargs["live"] is False
            assert run_kwargs["analysis_duration"] == 30
            assert run_kwargs["parallel_mode"] is True
            assert run_kwargs["max_workers"] == 2


class TestPollQueue:
    def _app_with_msgs(self, msgs: list[tuple]) -> MoodAnalysisBatchTaggerApp:
        app = _make_app()
        app._running = True
        app._on_done = MagicMock()  # type: ignore[method-assign]
        for msg in msgs:
            app._queue.put(msg)
        return app

    def test_folder_message(self) -> None:
        app = self._app_with_msgs([("folder", "/music/sub", 3, 2)])
        app._poll_queue()
        app._proc["file_listbox"].insert.assert_called_with(
            tkinter.END, "\u25b6  /music/sub  (3 files)"
        )
        app._proc["overall_status"].set.assert_called_with("Scanning: /music/sub")

    def test_progress_message(self) -> None:
        app = self._app_with_msgs([("progress", 5, 10, "track.mp3")])
        app._poll_queue()
        app._proc["progress"].__setitem__.assert_any_call("value", 50.0)
        app._proc["overall_status"].set.assert_called_with("Processing: track.mp3")

    def test_result_success(self) -> None:
        app = self._app_with_msgs(
            [("result", "/m/a.mp3", "a.mp3", True, "Energetic (conf 0.87)")]
        )
        app._poll_queue()
        assert app._tagged_count == 1
        app._proc["file_listbox"].insert.assert_called_with(
            tkinter.END, "    OK   a.mp3  ->  Energetic (conf 0.87)"
        )

    def test_result_skip(self) -> None:
        app = self._app_with_msgs(
            [("result", "/m/b.flac", "b.flac", False, "cannot decode")]
        )
        app._poll_queue()
        assert app._skipped_count == 1

    def test_slot_message_updates_slot_var(self) -> None:
        app = self._app_with_msgs([("slot", 2, "Analyzing: a.mp3")])
        app.slot_vars = [MagicMock() for _ in range(4)]
        app._poll_queue()
        app.slot_vars[2].set.assert_called_once_with("Analyzing: a.mp3")

    def test_slot_message_ignores_out_of_range_index(self) -> None:
        app = self._app_with_msgs([("slot", 9, "Analyzing: a.mp3")])
        app.slot_vars = [MagicMock() for _ in range(4)]
        app._poll_queue()
        for var in app.slot_vars:
            var.set.assert_not_called()
        app.root.after.assert_called_once_with(100, app._poll_queue)

    def test_done_message_calls_on_done_and_stops(self) -> None:
        app = self._app_with_msgs([("done", 5, 2, 1, 3, "/m/a.log")])
        app._poll_queue()
        app._on_done.assert_called_once_with(5, 2, 1, 3)
        assert app._tagged_count == 5
        assert app._log_path == "/m/a.log"
        assert app.root.after.call_count == 0

    def test_no_messages_reschedules(self) -> None:
        app = _make_app()
        app._running = True
        app._poll_queue()
        app.root.after.assert_called_once_with(100, app._poll_queue)

    def test_mixed_messages_processed_in_order(self) -> None:
        app = self._app_with_msgs(
            [
                ("folder", "/music/sub", 2, 1),
                ("progress", 1, 2, "a.mp3"),
                ("result", "/music/sub/a.mp3", "a.mp3", True, "Calm (conf 0.9)"),
                ("done", 1, 0, 0, 1, "/music/sub/a.log"),
            ]
        )
        app._poll_queue()
        app._on_done.assert_called_once_with(1, 0, 0, 1)
        assert app._folder_count == 1
        assert app._tagged_count == 1


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


class TestOpenLogAndFolder:
    def test_open_log_calls_open_path_when_exists(self, tmp_path) -> None:
        app = _make_app()
        log_file = tmp_path / "mood_analysis_batch_log.txt"
        log_file.write_text("log")
        app._log_path = str(log_file)
        with patch(f"{APP}.platform_utils") as mock_platform:
            app._on_open_log()
        mock_platform.open_path.assert_called_once_with(str(log_file))

    def test_open_log_shows_info_when_missing(self) -> None:
        app = _make_app()
        app._log_path = ""
        with patch(f"{APP}.platform_utils") as mock_platform:
            app._on_open_log()
        mock_platform.open_path.assert_not_called()
        mock_platform.messagebox.showinfo.assert_called_once()

    def test_open_folder_calls_open_path_when_valid(self, tmp_path) -> None:
        app = _make_app()
        app.root_path.get.return_value = str(tmp_path)
        with patch(f"{APP}.platform_utils") as mock_platform:
            app._on_open_folder()
        mock_platform.open_path.assert_called_once_with(str(tmp_path))

    def test_open_folder_shows_info_when_invalid(self) -> None:
        app = _make_app()
        app.root_path.get.return_value = "Z:/no/such"
        with patch(f"{APP}.platform_utils") as mock_platform:
            app._on_open_folder()
        mock_platform.open_path.assert_not_called()
        mock_platform.messagebox.showinfo.assert_called_once()


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
            patch(f"{APP}.threading.Thread") as mock_thread,
            patch(f"{APP}.batch_analysis_engine") as mock_engine,
            patch("audio_suite_shared.ui_common.messagebox") as warnings,
        ):
            app._on_start()

            assert app.max_workers.get() == 4
            mock_config.save_value.assert_any_call("mood_analysis_batch_max_workers", 4)
            warnings.showwarning.assert_called_once()

            worker = mock_thread.call_args.kwargs["target"]
            worker()
            assert mock_engine.run_batch.call_args.kwargs["max_workers"] == 4
