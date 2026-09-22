"""
Tests for bpm_analyzer.app — BPMAnalyzerApp CLI mirroring and wiring.

Uses the object.__new__ + MagicMock shell pattern (no real display).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_shell_app():
    """Build a BPMAnalyzerApp shell with mock attributes."""
    from bpm_analyzer.app import BPMAnalyzerApp

    app = object.__new__(BPMAnalyzerApp)
    app.root = MagicMock()
    app.folder_path = MagicMock()
    app.run_mode = MagicMock()
    app.auto_end = False
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()

    handler = MagicMock()
    handler.apply_cli_args.return_value = False
    handler_cls = MagicMock(return_value=handler)
    return app, handler, handler_cls


class TestApplyCliArgsDriven:
    """A driver launch populates the Run Controls values before applying."""

    def _run(self, parsed):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, handler, handler_cls = _make_shell_app()
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=parsed,
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            assert isinstance(parsed, BPMArgs)
            app._apply_cli_args()
        return app, handler

    def test_inherited_values_applied_to_panel_vars(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, _ = self._run(
            BPMArgs(
                folder_path="D:/Music",
                live_mode=True,
                auto_start=True,
                auto_end=True,
                clear_logs=True,
                parallel_run=True,
            )
        )
        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_handler_invoked_with_folder_and_auto_start(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        parsed = BPMArgs(folder_path="D:/Music")
        app, handler = self._run(parsed)
        handler.apply_cli_args.assert_called_once_with(
            parsed, folder_var=app.folder_path, auto_start_func=app.start_processing
        )

    def test_auto_start_schedules_processing(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, _, handler_cls = _make_shell_app()
        handler_cls.return_value.apply_cli_args.return_value = True
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=BPMArgs(folder_path="D:/Music"),
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        after_delays = [call.args[0] for call in app.root.after.call_args_list]
        assert 1500 in after_delays


class TestApplyCliArgsStandalone:
    """Standalone start: defaults applied, no handler/after scheduling."""

    def test_defaults_applied_to_panel_vars(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, _, handler_cls = _make_shell_app()
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=BPMArgs(),
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.auto_start_var.set.assert_called_once_with(False)
        app.auto_end_var.set.assert_called_once_with(False)
        app.clear_logs_var.set.assert_called_once_with(False)
        app.parallel_var.set.assert_called_once_with(False)

    def test_no_handler_or_scheduling_without_folder(self):
        from audio_suite_shared.cli_dataclasses import BPMArgs

        app, handler, handler_cls = _make_shell_app()
        with (
            patch(
                "bpm_analyzer.utils.cli_args.parse",
                return_value=BPMArgs(),
            ),
            patch("bpm_analyzer.app.UniversalCLIHandler", handler_cls),
        ):
            app._apply_cli_args()

        handler.apply_cli_args.assert_not_called()
        app.root.after.assert_not_called()
