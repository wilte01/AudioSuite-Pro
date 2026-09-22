"""
Tests for metadata_scrubber.app — Run Controls panel wiring.

Uses the object.__new__ + MagicMock pattern so no real Tk root is
needed (per AGENTS.md GUI testing rules).
"""

import tkinter as tk
from unittest.mock import MagicMock, patch

from metadata_scrubber.app import MetadataScrubberApp
from metadata_scrubber.utils.cli_args import ScrubberArgs


def _make_app() -> MetadataScrubberApp:
    """Build a shell app instance with mock attributes (no real Tk)."""
    app = object.__new__(MetadataScrubberApp)
    app.root = MagicMock()
    app.folder_path = MagicMock(spec=tk.StringVar)
    app.run_mode = MagicMock(spec=tk.StringVar)
    app.auto_start_var = MagicMock(spec=tk.BooleanVar)
    app.auto_end_var = MagicMock(spec=tk.BooleanVar)
    app.clear_logs_var = MagicMock(spec=tk.BooleanVar)
    app.parallel_var = MagicMock(spec=tk.BooleanVar)
    app.cli_handler = MagicMock()
    app.cli_handler.apply_cli_args.return_value = False
    return app


class TestApplyCliArgsDriven:
    """A driver launch populates and locks the Run Controls values."""

    def test_inherited_values_applied_to_panel_vars(self):
        app = _make_app()
        parsed = ScrubberArgs(
            folder_path="D:/Music",
            live_mode=True,
            auto_start=True,
            auto_end=True,
            clear_logs=True,
            parallel_run=True,
        )
        with (
            patch("metadata_scrubber.utils.cli_args.parse", return_value=parsed),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=True,
            ),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Live Update")
        app.auto_start_var.set.assert_called_once_with(True)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_folder_passed_to_cli_handler(self):
        app = _make_app()
        parsed = ScrubberArgs(folder_path="D:/Music")
        with (
            patch("metadata_scrubber.utils.cli_args.parse", return_value=parsed),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=True,
            ),
        ):
            app._apply_cli_args()

        app.cli_handler.apply_cli_args.assert_called_once_with(
            parsed,
            folder_var=app.folder_path,
            auto_start_func=app._do_scan,
        )

    def test_scan_scheduled_after_apply(self):
        app = _make_app()
        parsed = ScrubberArgs(folder_path="D:/Music")
        with (
            patch("metadata_scrubber.utils.cli_args.parse", return_value=parsed),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=True,
            ),
        ):
            app._apply_cli_args()

        after_delays = [call.args[0] for call in app.root.after.call_args_list]
        assert 500 in after_delays

    def test_auto_start_schedules_processing(self):
        app = _make_app()
        app.cli_handler.apply_cli_args.return_value = True
        parsed = ScrubberArgs(folder_path="D:/Music", auto_start=True)
        with (
            patch("metadata_scrubber.utils.cli_args.parse", return_value=parsed),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=True,
            ),
        ):
            app._apply_cli_args()

        after_delays = [call.args[0] for call in app.root.after.call_args_list]
        assert 1000 in after_delays


class TestApplyCliArgsStandalone:
    """Standalone start: defaults applied, no handler/after scheduling."""

    def test_defaults_applied_to_panel_vars(self):
        app = _make_app()
        with (
            patch(
                "metadata_scrubber.utils.cli_args.parse",
                return_value=ScrubberArgs(),
            ),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=False,
            ),
        ):
            app._apply_cli_args()

        app.run_mode.set.assert_called_once_with("Dry Run")
        app.auto_start_var.set.assert_called_once_with(False)
        app.auto_end_var.set.assert_called_once_with(False)
        app.clear_logs_var.set.assert_called_once_with(False)
        app.parallel_var.set.assert_called_once_with(False)

    def test_no_handler_or_scheduling_without_folder(self):
        app = _make_app()
        with (
            patch(
                "metadata_scrubber.utils.cli_args.parse",
                return_value=ScrubberArgs(),
            ),
            patch(
                "metadata_scrubber.utils.cli_args.was_launched_from_driver",
                return_value=False,
            ),
        ):
            app._apply_cli_args()

        app.cli_handler.apply_cli_args.assert_not_called()
        app.root.after.assert_not_called()
