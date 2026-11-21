"""
Tests for replaygain_analyzer.app — ReplayGainAnalyzerApp orchestrator.

Validates that callback signatures between app.py and
core/file_processor.py match, preventing kwarg mismatch bugs.

Changed in 1.4.1: ``TestCompletionSeam`` drives the real ``run_analysis``
through the lambda wiring ``_run`` installs and reads the report it writes; the
success count was ``processed - errors`` while ``processed`` already counted
successes, so a mixed batch under-reported (and a lone failure read as -1), and
the completion counts that used to default are now required payload fields.
Changed in 2.1.2: the measurement mock returns the third metric (duration),
which album gain now needs (audit R-01).

Changed in 2.9.0: the window is a ``SuiteApp`` (C1 stage 2), so the tests build
shells with ``object.__new__`` instead of mocking a whole hand-built window, the
completion renders through the shell's results frame, the error handler is the
shell's, and the run's inputs are the snapshot ``start_processing`` takes on the
main thread.
"""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest

from replaygain_analyzer.app import ReplayGainAnalyzerApp


def _completion_shell(log_path: Path) -> ReplayGainAnalyzerApp:
    """Build a ReplayGainAnalyzerApp shell carrying only what _on_complete reads."""
    app = object.__new__(ReplayGainAnalyzerApp)
    app.root = MagicMock()
    app._run_mode = "Dry Run"
    app._run_path = str(log_path.parent)
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.notebook = MagicMock()
    app.results_frame = MagicMock()
    app.start_btn = MagicMock()
    app.auto_end = False
    app._log_path = str(log_path)
    return app


def _write_silent_wav(folder: Path) -> None:
    """Write one analysable file; measurement is stubbed in these tests."""
    from pydub import AudioSegment

    AudioSegment.silent(duration=100).export(str(folder / "track.wav"), format="wav")


def _flush(root: MagicMock) -> None:
    """Run the widget updates the handler marshalled through ``root.after``."""
    for call in root.after.call_args_list:
        if len(call.args) > 1 and callable(call.args[1]):
            call.args[1](*call.args[2:])


# ── Completion seam: the processor payload must reach this handler ───────


class TestCompletionSeam:
    """``run_analysis`` publishes into the handler app.py actually binds."""

    def test_the_real_payload_reaches_the_report(self, tmp_path: Path) -> None:
        """Regression: the counts defaulted, so a run could print zeros.

        ``errors`` and the rest were optional, so a payload that omitted the
        error count wrote ``Errors: 0`` and ``Time: 00:00`` into a finished
        report.  Drive the real orchestrator through the same lambda wiring
        ``_run`` uses and read the file it wrote.
        """
        from replaygain_analyzer.core import file_processor

        _write_silent_wav(tmp_path)
        app = _completion_shell(tmp_path / "replaygain_dry_run_log.txt")
        slot_queue: Queue = Queue()
        slot_queue.put(0)

        with patch.object(
            file_processor, "get_metrics", return_value=(None, 0.0, None)
        ):
            file_processor.run_analysis(
                dir_path=str(tmp_path),
                target_lufs=-16.0,
                is_dry_run=True,
                slot_vars=[MagicMock()],
                slot_queue=slot_queue,
                on_progress=MagicMock(),
                on_folder_complete=MagicMock(),
                on_complete=lambda **kw: app._on_complete(header=["REPORT\n"], **kw),
                on_error=MagicMock(),
            )

        report = Path(app._log_path).read_text(encoding="utf-8")
        assert "Total files: 1" in report
        assert "Errors: 1" in report

        _flush(app.root)
        app.summary_label.config.assert_called_with(
            text="Total: 1 files\nSuccessfully processed: 0\nErrors: 1"
        )

    def test_successes_are_not_reduced_by_the_error_count(self, tmp_path: Path) -> None:
        """Regression: the summary subtracted errors from an already-clean count.

        ``processed`` only counts files that measured successfully, so
        ``processed - errors`` understated every mixed batch and went negative
        once errors outnumbered successes.
        """
        app = _completion_shell(tmp_path / "log.txt")

        app._on_complete(
            header=["REPORT\n"],
            total=3,
            processed=2,
            skipped=0,
            errors=1,
            duration_secs=75.0,
            log_entries=["[DONE] a.wav\n", "[DONE] b.wav\n"],
        )

        report = (tmp_path / "log.txt").read_text(encoding="utf-8")
        assert "Total files: 3" in report
        assert "Successfully processed: 2" in report
        assert "Errors: 1" in report
        assert "Time: 01:15" in report

    @pytest.mark.parametrize(
        "field", ["skipped", "errors", "duration_secs", "log_entries"]
    )
    def test_a_missing_count_raises_instead_of_rendering_zero(
        self, tmp_path: Path, field: str
    ) -> None:
        """Each count is required, so its absence names itself in the error."""
        app = _completion_shell(tmp_path / "log.txt")
        payload = {
            "header": ["REPORT\n"],
            "total": 3,
            "processed": 2,
            "skipped": 0,
            "errors": 2,
            "duration_secs": 75.0,
            "log_entries": ["[DONE] track.mp3\n"],
        }
        del payload[field]

        with pytest.raises(TypeError) as caught:
            app._on_complete(**payload)
        assert field in str(caught.value)
        assert not (tmp_path / "log.txt").exists()


# ── The completion renders through the shell ─────────────────────────────


class TestCompletionRender:
    """A finished run points the shell at this run's heading and results."""

    def test_a_dry_run_labels_itself_analysis(self, tmp_path: Path) -> None:
        app = _completion_shell(tmp_path / "log.txt")

        app._on_complete(
            header=["REPORT\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        _flush(app.root)

        app.completion_label.config.assert_called_with(text="Analysis Complete!")
        app.notebook.select.assert_called_with(app.results_frame)
        app.start_btn.config.assert_called_with(state="normal")

    def test_a_live_run_labels_itself_tagging(self, tmp_path: Path) -> None:
        app = _completion_shell(tmp_path / "log.txt")
        app._run_mode = "Live Update"

        app._on_complete(
            header=["REPORT\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        _flush(app.root)

        app.completion_label.config.assert_called_with(
            text="ReplayGain Tagging Complete!"
        )

    def test_auto_end_closes_the_window(self, tmp_path: Path) -> None:
        app = _completion_shell(tmp_path / "log.txt")
        app.auto_end = True

        app._on_complete(
            header=["REPORT\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
        )
        _flush(app.root)

        destroy_calls = [
            call
            for call in app.root.after.call_args_list
            if len(call.args) >= 2 and call.args[1] == app.root.destroy
        ]
        assert len(destroy_calls) == 1

    def test_a_failed_report_write_is_logged_not_raised(self, tmp_path: Path) -> None:
        app = _completion_shell(tmp_path / "log.txt")

        with patch("builtins.open", side_effect=OSError(13, "denied")):
            app._on_complete(
                header=["REPORT\n"],
                total=1,
                processed=1,
                skipped=0,
                errors=0,
                duration_secs=1.0,
                log_entries=[],
            )


# ── Progress and per-file lines ──────────────────────────────────────────


class TestProgressCallbacks:
    """The progress seam and the per-file lines the run publishes."""

    @staticmethod
    @pytest.fixture
    def app() -> ReplayGainAnalyzerApp:
        root = MagicMock()
        scheduled: list = []
        root.after.side_effect = lambda delay, fn, *a, **kw: scheduled.append((fn, a))
        app = object.__new__(ReplayGainAnalyzerApp)
        app.root = root
        app._scheduled = scheduled
        app.progress = MagicMock()
        app.stats_label = MagicMock()
        app.file_listbox = MagicMock()
        return app

    def test_on_progress_schedules_the_tick(self, app: ReplayGainAnalyzerApp) -> None:
        app._on_progress(3, 10, 1)
        fn, args = app._scheduled[0]
        assert fn == app._update_progress_ui
        assert args == (3, 10, 1)

    def test_the_tick_moves_the_bar_and_the_counters(
        self, app: ReplayGainAnalyzerApp
    ) -> None:
        app._update_progress_ui(4, 9, 1)
        assert app.progress.__setitem__.call_args_list[0] == (("maximum", 9),)
        assert app.progress.__setitem__.call_args_list[1] == (("value", 4),)
        app.stats_label.config.assert_called_once_with(text="Processed: 4 | Errors: 1")

    def test_a_tick_publishes_no_per_file_line(
        self, app: ReplayGainAnalyzerApp
    ) -> None:
        """This processor's progress payload has no line, so none is written."""
        app._update_progress_ui(1, 1, 0)
        app.file_listbox.insert.assert_not_called()

    def test_a_folder_line_carries_its_measurements(
        self, app: ReplayGainAnalyzerApp
    ) -> None:
        app._on_folder_complete(
            folder_path="/music",
            files_data=[],
            album_gain_str="-1.80 dB",
            album_peak_str="0.987654",
            tag_results=[
                (
                    {"name": "a.mp3", "lufs": -14.234},
                    "TAGGED",
                    "+2.10 dB",
                    "0.950000",
                )
            ],
            log_header="FOLDER: /music\n",
        )
        _flush(app.root)

        app.file_listbox.insert.assert_called_once_with(
            "end", "a.mp3 | LUFS -14.23 | Track +2.10 dB | Album -1.80 dB | TAGGED"
        )


# ── Shell seams ──────────────────────────────────────────────────────────


class TestShellSeams:
    """Help, View Log and Browse reach the shell's helpers."""

    def test_browse_folder_calls_helper(self) -> None:
        app = object.__new__(ReplayGainAnalyzerApp)
        app.folder_path = MagicMock()
        app._browse_folder_standard = MagicMock()
        app._browse_folder()
        app._browse_folder_standard.assert_called_once()

    def test_open_help_opens_the_tools_guide(self) -> None:
        app = object.__new__(ReplayGainAnalyzerApp)
        app._open_help_standard = MagicMock()
        app._open_help()
        app._open_help_standard.assert_called_once_with(
            "ReplayGain_Analyzer_User_Guide.docx"
        )

    def test_open_log_calls_helper(self) -> None:
        app = object.__new__(ReplayGainAnalyzerApp)
        app._open_log_standard = MagicMock()
        app._open_log()
        app._open_log_standard.assert_called_once()

    def test_on_error_shows_error_and_reenables_button(self) -> None:
        """The error seam is the shell's; this window inherits it."""
        app = object.__new__(ReplayGainAnalyzerApp)
        app.start_btn = MagicMock()
        with patch("audio_suite_shared.suite_app.messagebox") as mock_mb:
            app._on_error("something broke")
        mock_mb.showerror.assert_called_once_with("Error", "something broke")
        app.start_btn.config.assert_called_once_with(state="normal")


# ── Run Controls panel wiring ────────────────────────────────────────────
# Shell instances via object.__new__ + MagicMock (AGENTS.md GUI pattern).


def _make_shell_app() -> ReplayGainAnalyzerApp:
    """Build a ReplayGainAnalyzerApp shell with mock attributes."""
    app = object.__new__(ReplayGainAnalyzerApp)
    app.root = MagicMock()
    app.folder_path = MagicMock()
    app.run_mode = MagicMock()
    app.target_lufs = MagicMock()
    app.auto_end = False
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()
    app.apply_lossless_gain_var = MagicMock()
    return app


class TestApplyCliArgsDriven:
    """A driver launch populates the Run Controls values before applying."""

    def _run(self, parsed, driven=True):
        app = _make_shell_app()
        handler = MagicMock()
        handler.apply_cli_args.return_value = False
        handler_cls = MagicMock(return_value=handler)
        with (
            patch("replaygain_analyzer.utils.cli_args.parse", return_value=parsed),
            patch(
                "replaygain_analyzer.utils.cli_args.was_launched_from_driver",
                return_value=driven,
            ),
            patch(
                "replaygain_analyzer.app.UniversalCLIHandler",
                handler_cls,
            ),
        ):
            app._apply_cli_args()
        return app, handler

    def test_inherited_values_applied_to_panel_vars(self):
        from replaygain_analyzer.utils.cli_args import ReplayGainArgs

        app, _ = self._run(
            ReplayGainArgs(
                folder_path="D:/Music",
                live_mode=True,
                auto_start=True,
                auto_end=True,
                clear_logs=True,
                parallel_run=True,
                apply_lossless_gain=True,
            )
        )
        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)
        app.apply_lossless_gain_var.set.assert_called_once_with(True)

    def test_handler_invoked_with_folder(self):
        from replaygain_analyzer.utils.cli_args import ReplayGainArgs

        parsed = ReplayGainArgs(folder_path="D:/Music")
        app, handler = self._run(parsed)
        handler.apply_cli_args.assert_called_once_with(
            parsed,
            folder_var=app.folder_path,
            auto_start_func=app.start_processing,
        )

    def test_auto_start_schedules_processing(self):
        from replaygain_analyzer.utils.cli_args import ReplayGainArgs

        app = _make_shell_app()
        handler = MagicMock()
        handler.apply_cli_args.return_value = True
        handler_cls = MagicMock(return_value=handler)
        with (
            patch(
                "replaygain_analyzer.utils.cli_args.parse",
                return_value=ReplayGainArgs(folder_path="D:/Music"),
            ),
            patch(
                "replaygain_analyzer.utils.cli_args.was_launched_from_driver",
                return_value=True,
            ),
            patch("replaygain_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        after_delays = [call.args[0] for call in app.root.after.call_args_list]
        assert 1500 in after_delays


class TestApplyCliArgsStandalone:
    """Standalone start: defaults applied, no handler/after scheduling."""

    def test_defaults_applied_to_panel_vars(self):
        from replaygain_analyzer.utils.cli_args import ReplayGainArgs

        app = _make_shell_app()
        handler_cls = MagicMock()
        with (
            patch(
                "replaygain_analyzer.utils.cli_args.parse",
                return_value=ReplayGainArgs(),
            ),
            patch(
                "replaygain_analyzer.utils.cli_args.was_launched_from_driver",
                return_value=False,
            ),
            patch("replaygain_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.auto_start_var.set.assert_called_once_with(False)
        app.auto_end_var.set.assert_called_once_with(False)
        app.clear_logs_var.set.assert_called_once_with(False)
        app.parallel_var.set.assert_called_once_with(False)
        app.apply_lossless_gain_var.set.assert_called_once_with(False)

    def test_no_handler_or_scheduling_without_folder(self):
        from replaygain_analyzer.utils.cli_args import ReplayGainArgs

        app = _make_shell_app()
        handler_cls = MagicMock()
        with (
            patch(
                "replaygain_analyzer.utils.cli_args.parse",
                return_value=ReplayGainArgs(),
            ),
            patch(
                "replaygain_analyzer.utils.cli_args.was_launched_from_driver",
                return_value=False,
            ),
            patch("replaygain_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        handler_cls.return_value.apply_cli_args.assert_not_called()
        app.root.after.assert_not_called()


# ── start_processing validation and the run snapshot ─────────────────────


def _make_processing_app() -> ReplayGainAnalyzerApp:
    """Build a minimal app for start_processing tests."""
    app = object.__new__(ReplayGainAnalyzerApp)
    app.root = MagicMock()
    app.folder_path = MagicMock()
    app.start_btn = MagicMock()
    app.file_listbox = MagicMock()
    app.notebook = MagicMock()
    app.overall_status = MagicMock()
    app.progress = MagicMock()
    app.stats_label = MagicMock()
    app.processing_frame = MagicMock()
    app.run_mode = MagicMock()
    app.run_mode.get.return_value = "Dry Run"
    app.target_lufs = MagicMock()
    app.target_lufs.get.return_value = "-16.0"
    app.apply_lossless_gain_var = MagicMock()
    app.apply_lossless_gain_var.get.return_value = False
    return app


class TestStartProcessingValidation:
    """start_processing() validates the folder and the target before a run."""

    def test_empty_folder_shows_error(self) -> None:
        app = _make_processing_app()
        app.folder_path.get.return_value = "   "
        with patch("replaygain_analyzer.app.messagebox") as mock_mb:
            app.start_processing()
        mock_mb.showerror.assert_called_once_with(
            "No Directory Selected",
            "Please select a music directory containing audio files.",
        )
        app.start_btn.config.assert_not_called()

    def test_nonexistent_folder_shows_error(self) -> None:
        app = _make_processing_app()
        app.folder_path.get.return_value = "/no/such/dir"
        with (
            patch("replaygain_analyzer.app.os.path.exists", return_value=False),
            patch("replaygain_analyzer.app.messagebox") as mock_mb,
        ):
            app.start_processing()
        mock_mb.showerror.assert_called_once()
        assert "does not exist" in mock_mb.showerror.call_args[0][1]

    def test_not_a_directory_shows_error(self) -> None:
        app = _make_processing_app()
        app.folder_path.get.return_value = "/some/file.mp3"
        with (
            patch("replaygain_analyzer.app.os.path.exists", return_value=True),
            patch("replaygain_analyzer.app.os.path.isdir", return_value=False),
            patch("replaygain_analyzer.app.messagebox") as mock_mb,
        ):
            app.start_processing()
        mock_mb.showerror.assert_called_once()
        assert "not a valid directory" in mock_mb.showerror.call_args[0][1]

    def test_no_audio_files_shows_error(self) -> None:
        app = _make_processing_app()
        app.folder_path.get.return_value = "/empty/dir"
        with (
            patch("replaygain_analyzer.app.os.path.exists", return_value=True),
            patch("replaygain_analyzer.app.os.path.isdir", return_value=True),
            patch("replaygain_analyzer.app.os.listdir", return_value=["readme.txt"]),
            patch("replaygain_analyzer.app.messagebox") as mock_mb,
        ):
            app.start_processing()
        mock_mb.showerror.assert_called_once()
        assert "No supported audio files" in mock_mb.showerror.call_args[0][1]

    def test_an_out_of_range_target_shows_error(self) -> None:
        app = _make_processing_app()
        app.folder_path.get.return_value = "/music"
        app.target_lufs.get.return_value = "-100"
        with (
            patch("replaygain_analyzer.app.os.path.exists", return_value=True),
            patch("replaygain_analyzer.app.os.path.isdir", return_value=True),
            patch("replaygain_analyzer.app.os.listdir", return_value=["a.mp3"]),
            patch("replaygain_analyzer.app.messagebox") as mock_mb,
        ):
            app.start_processing()
        mock_mb.showerror.assert_called_once()
        assert mock_mb.showerror.call_args[0][0] == "Invalid LUFS Target"

    def test_success_snapshots_the_run_inputs(self) -> None:
        """The worker must never call .get() on a Tk variable."""
        app = _make_processing_app()
        app.folder_path.get.return_value = "/music"
        app.run_mode.get.return_value = "Live Update"
        app.target_lufs.get.return_value = "-14.0"
        app.apply_lossless_gain_var.get.return_value = True
        with (
            patch("replaygain_analyzer.app.os.path.exists", return_value=True),
            patch("replaygain_analyzer.app.os.path.isdir", return_value=True),
            patch("replaygain_analyzer.app.os.listdir", return_value=["a.mp3"]),
            patch("replaygain_analyzer.app.threading.Thread"),
        ):
            app.start_processing()

        assert app._run_path == "/music"
        assert app._run_mode == "Live Update"
        assert app._run_target_lufs == -14.0
        assert app._run_apply_lossless_gain is True

    def test_success_resets_the_processing_tab(self) -> None:
        app = _make_processing_app()
        app.folder_path.get.return_value = "/music"
        with (
            patch("replaygain_analyzer.app.os.path.exists", return_value=True),
            patch("replaygain_analyzer.app.os.path.isdir", return_value=True),
            patch("replaygain_analyzer.app.os.listdir", return_value=["a.mp3"]),
            patch("replaygain_analyzer.app.threading.Thread") as mock_thread,
        ):
            app.start_processing()

        app.start_btn.config.assert_called_once_with(state="disabled")
        app.file_listbox.delete.assert_called_once_with(0, "end")
        app.notebook.select.assert_called_once_with(app.processing_frame)
        app.overall_status.set.assert_called_once_with("Analyzing ReplayGain values...")
        mock_thread.assert_called_once()
        assert mock_thread.call_args[1]["daemon"] is True
        assert mock_thread.call_args[1]["target"] == app._run
