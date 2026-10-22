"""
Tests for replaygain_analyzer.app — ReplayGainAnalyzerApp orchestrator.

Validates that callback signatures between app.py and
core/file_processor.py match, preventing kwarg mismatch bugs.

Changed in 1.4.1: ``TestCompletionSeam`` drives the real ``run_analysis``
through the lambda wiring ``_run`` installs and reads the report it writes; the
success count was ``processed - errors`` while ``processed`` already counted
successes, so a mixed batch under-reported (and a lone failure read as -1), and
the completion counts that used to default are now required payload fields.
"""

from __future__ import annotations

from pathlib import Path
from queue import Queue
from unittest.mock import MagicMock, patch

import pytest


def _mock_stringvar(value=None, master=None, name=None):
    sv = MagicMock()
    sv.get.return_value = value if value is not None else ""

    def sv_setter(val):
        sv.get.return_value = val

    sv.set = sv_setter
    return sv


@pytest.fixture
def mock_replaygain_app():
    """Build a ReplayGainAnalyzerApp with all GUI dependencies mocked."""
    import audio_suite_shared.ui_common
    import replaygain_analyzer.app
    import replaygain_analyzer.ui.processing_tab
    import replaygain_analyzer.ui.results_tab
    import replaygain_analyzer.ui.setup_tab

    to_patch = [
        replaygain_analyzer.app,
        replaygain_analyzer.ui.setup_tab,
        replaygain_analyzer.ui.results_tab,
        replaygain_analyzer.ui.processing_tab,
        audio_suite_shared.ui_common,
    ]
    saved = {}
    for mod in to_patch:
        saved[mod] = {
            "tk": getattr(mod, "tk", None),
            "ttk": getattr(mod, "ttk", None),
        }

    mock_tk = MagicMock()
    mock_tk.StringVar = _mock_stringvar
    mock_tk.ttk = MagicMock()
    mock_tk.END = "end"
    mock_tk.ACTIVE = "active"
    mock_tk.DISABLED = "disabled"
    mock_tk.NORMAL = "normal"
    mock_tk.Frame = MagicMock(return_value=MagicMock())
    mock_tk.Label = MagicMock(return_value=MagicMock())
    mock_tk.Button = MagicMock(return_value=MagicMock())
    mock_tk.Entry = MagicMock(return_value=MagicMock())
    mock_tk.Listbox = MagicMock(return_value=MagicMock())
    mock_tk.Text = MagicMock(return_value=MagicMock())
    mock_tk.Toplevel = MagicMock(return_value=MagicMock())
    mock_tk.Tk = MagicMock(return_value=MagicMock())

    try:
        for mod in to_patch:
            mod.tk = mock_tk
            if hasattr(mod, "ttk"):
                mod.ttk = mock_tk.ttk

        with (
            patch("replaygain_analyzer.app.bootstrap_tool_app") as mock_bootstrap,
            patch("replaygain_analyzer.app.suite_config") as mock_config,
            patch("replaygain_analyzer.app.cli_args") as mock_cli,
            patch("replaygain_analyzer.app.messagebox"),
            patch("replaygain_analyzer.app.UniversalCLIHandler"),
            patch("replaygain_analyzer.app.logger"),
            # DriverControlsPanel builds real tkinter widgets — replace it
            # while the rest of tkinter is mocked in this fixture.
            patch("replaygain_analyzer.ui.setup_tab.DriverControlsPanel") as mock_panel,
        ):
            mock_bootstrap.return_value = (MagicMock(), MagicMock())
            mock_config.load_window_geometry.return_value = "800x600"
            mock_cli.parse.return_value = MagicMock(folder_path=None)
            mock_cli.was_launched_from_driver.return_value = False
            mock_panel.return_value = MagicMock()

            from replaygain_analyzer.app import ReplayGainAnalyzerApp

            root = MagicMock()
            root.withdraw = MagicMock()
            app = ReplayGainAnalyzerApp(root)
            # Patch methods inherited from UIHelperMixin
            app._browse_folder_standard = MagicMock()
            app._open_help_standard = MagicMock()
            app._open_log_standard = MagicMock()
            yield app
    finally:
        for mod, attrs in saved.items():
            for attr, val in attrs.items():
                setattr(mod, attr, val)


class TestCallbackSignatureConsistency:
    """Verify every callback signature matches between app.py and
    core/file_processor.py to prevent kwarg mismatch bugs."""

    def test_on_complete_accepts_all_kwargs_from_file_processor(
        self, mock_replaygain_app, tmp_path
    ):
        """_on_complete must accept 'skipped' which run_analysis() passes."""
        app = mock_replaygain_app
        app._log_path = str(tmp_path / "rg_log.txt")

        app._on_complete(
            header=["REPORT\n"],
            total=10,
            processed=8,
            skipped=2,
            errors=0,
            duration_secs=12.5,
            log_entries=["line1\n", "line2\n"],
        )

    def test_on_complete_with_auto_end_schedules_close(
        self, mock_replaygain_app, tmp_path
    ):
        app = mock_replaygain_app
        app._log_path = str(tmp_path / "rg_log.txt")
        app.auto_end = True

        app._on_complete(
            header=["REPORT\n"],
            total=10,
            processed=10,
            skipped=0,
            errors=0,
            duration_secs=5.0,
            log_entries=["done\n"],
        )
        app.root.after.assert_called()

    def test_on_file_progress_matches_parameter_name(self, mock_replaygain_app):
        """The 'on_progress' parameter in run_analysis() must match
        the 'on_file_progress' -> 'on_progress' kwarg name in app.py."""
        app = mock_replaygain_app
        app.progress = MagicMock()
        app.stats_label = MagicMock()

        # _on_file_progress schedules UI updates via root.after.
        # Simulate what root.after does: execute the lambda immediately.
        def fake_after(ms, fn, *args):
            fn()

        app.root.after = fake_after

        app._on_file_progress(processed=5, total=10, errors=1)
        app.progress.configure.assert_called()
        app.stats_label.config.assert_called()

    def test_run_analysis_lambda_wiring(self, mock_replaygain_app, tmp_path):
        """The lambda wrapping _on_complete in _run() must pass all
        kwargs through without dropping any."""
        app = mock_replaygain_app
        app._log_path = str(tmp_path / "rg_log.txt")

        # Simulate the lambda from app.py line 300:
        # on_complete=lambda **kw: self._on_complete(header=header, **kw)
        header = ["REPORT\n"]

        def lambda_wrapper(**kw):
            app._on_complete(header=header, **kw)

        lambda_wrapper(
            total=10,
            processed=8,
            skipped=2,
            errors=0,
            duration_secs=12.5,
            log_entries=[],
        )


# ── Completion seam: the processor payload must reach this handler ───────


def _completion_shell(log_path: Path):
    """Build a ReplayGainAnalyzerApp shell carrying only what _on_complete reads."""
    from replaygain_analyzer.app import ReplayGainAnalyzerApp

    app = object.__new__(ReplayGainAnalyzerApp)
    app.root = MagicMock()
    app.run_mode = MagicMock()
    app.run_mode.get.return_value = "Dry Run"
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.notebook = MagicMock()
    app._tab_results = MagicMock()
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
            call.args[1]()


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

        with patch.object(file_processor, "get_metrics", return_value=(None, 0.0)):
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


class TestReplaygainAppActions:
    def test_browse_folder_calls_helper(self, mock_replaygain_app):
        mock_replaygain_app._browse_folder()
        mock_replaygain_app._browse_folder_standard.assert_called_once()

    def test_open_help_calls_helper(self, mock_replaygain_app):
        mock_replaygain_app._open_help()
        mock_replaygain_app._open_help_standard.assert_called_once_with(
            "ReplayGain_Analyzer_User_Guide.docx"
        )

    def test_open_log_calls_helper(self, mock_replaygain_app):
        mock_replaygain_app._open_log()
        mock_replaygain_app._open_log_standard.assert_called_once()


# ── Run Controls panel wiring ────────────────────────────────────────────
# Shell instances via object.__new__ + MagicMock (AGENTS.md GUI pattern).


def _make_shell_app():
    """Build a ReplayGainAnalyzerApp shell with mock attributes."""
    from replaygain_analyzer.app import ReplayGainAnalyzerApp

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

    handler = MagicMock()
    handler.apply_cli_args.return_value = False
    handler_cls = MagicMock(return_value=handler)
    return app, handler, handler_cls


class TestApplyCliArgsDriven:
    """A driver launch populates the Run Controls values before applying."""

    def _run(self, parsed, driven=True):
        from replaygain_analyzer.app import UniversalCLIHandler  # noqa: F401

        app, handler, handler_cls = _make_shell_app()
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

        app, _, handler_cls = _make_shell_app()
        handler_cls.return_value.apply_cli_args.return_value = True
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

        app, _, handler_cls = _make_shell_app()
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

        app, _, handler_cls = _make_shell_app()
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
