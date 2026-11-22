"""Tests for the Restoration window.

The window is a ``SuiteApp``, so what is checked here is what is this tool's
own: the validation a run must pass, the driver's pre-fill routes, the preset
round trip, the queue-only callbacks, and -- ``TestCompletionSeam`` -- the real
declip batch driven into the completion handler, asserting the report it writes
and the summary it renders.  The shell's own contract (tabs, title, report
pointer, worker hand-off) is ``tests/test_suite_app_contract.py``.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
Changed in 2.9.0: the window adopts ``SuiteApp`` (C1 stage 2, D34); the seam is
the bound ``_finish_run`` rather than a local closure, and the report it writes
is read back from disk instead of inferred from a mocked writer.
"""

from __future__ import annotations

from pathlib import Path
from queue import SimpleQueue
from unittest.mock import MagicMock

import numpy as np
import pytest

from restoration.core.declipper import DEFAULT_MAX_RUN_MS, DEFAULT_THRESHOLD
from restoration.core.file_processor import run_declipping
from restoration.ui.app import DRY_RUN, LIVE_UPDATE, RUN_REPORT_DRY_RUN, RestorationApp

from .conftest import sine, to_segment


def shell(mode: str = DRY_RUN) -> RestorationApp:
    """Return a window object without building any widgets.

    Args:
        mode: The value the Mode combobox holds.

    Returns:
        The shell, ready for a handler call.
    """
    app = object.__new__(RestorationApp)
    app.root = MagicMock()
    app.run_mode = MagicMock()
    app.run_mode.get.return_value = mode
    app.threshold = MagicMock()
    app.threshold.get.return_value = DEFAULT_THRESHOLD
    app.max_run = MagicMock()
    app.max_run.get.return_value = DEFAULT_MAX_RUN_MS
    app.auto_start_var = MagicMock()
    app.auto_end_var = MagicMock()
    app.auto_end_var.get.return_value = False
    app.clear_logs_var = MagicMock()
    app.parallel_var = MagicMock()
    app.progress = MagicMock()
    app.stats_label = MagicMock()
    app.overall_status = MagicMock()
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.notebook = MagicMock()
    app.start_btn = MagicMock()
    app._ui_updates = SimpleQueue()
    app._run_mode = mode
    app._run_folder = ""
    app._run_was_dry_run = mode == DRY_RUN
    app._audition_original = None
    app._audition_result = None
    app.set_audition_state = MagicMock()
    return app


class TestToolIdentity:
    """The ids and labels the driver, the Help button and the report use."""

    def test_the_tool_id_is_the_manifest_id(self) -> None:
        from audio_suite_shared.tool_plugin import get_registry

        assert RestorationApp.TOOL_ID in {m.id for m in get_registry().all}

    def test_the_help_guide_is_the_registered_name(self) -> None:
        assert RestorationApp.HELP_GUIDE == "Restoration_User_Guide.docx"

    def test_the_result_label_names_the_repair(self) -> None:
        assert RestorationApp.TAGGED_LABEL == "Repaired"

    def test_the_completion_text_names_the_repair(self) -> None:
        assert RestorationApp.completion_text == "Declip Complete!"

    def test_the_window_plays_the_before_and_after_row(self) -> None:
        assert RestorationApp.audition_row is True


class TestStartValidation:
    """A run that cannot work never starts."""

    def test_the_shipped_defaults_pass(self) -> None:
        assert RestorationApp._validate_start(shell()) is None

    def test_a_threshold_outside_the_unit_range_is_refused(self) -> None:
        app = shell()
        app.threshold.get.return_value = 1.5

        message = RestorationApp._validate_start(app)

        assert message is not None and "threshold" in message.lower()

    def test_a_zero_width_limit_is_refused(self) -> None:
        app = shell()
        app.max_run.get.return_value = 0

        message = RestorationApp._validate_start(app)

        assert message is not None and "width" in message.lower()


class TestDriverOptions:
    """Every pre-fill route writes the control the user would have edited."""

    def test_the_threshold_and_width_are_mirrored(self) -> None:
        app = shell()

        app._apply_tool_cli_options(
            MagicMock(live_mode=True, threshold=0.8, run_ms=12, auto_end=True)
        )

        app.threshold.set.assert_called_once_with(0.8)
        app.max_run.set.assert_called_once_with(12)

    def test_the_mode_and_the_orchestration_flags_are_mirrored(self) -> None:
        app = shell()

        app._apply_cli_args(
            MagicMock(
                folder_path="",
                live_mode=True,
                auto_start=False,
                auto_end=True,
                clear_logs=True,
                parallel_run=True,
                threshold=0.0,
                run_ms=0,
            )
        )

        app.run_mode.set.assert_called_once_with(LIVE_UPDATE)
        app.auto_end_var.set.assert_called_once_with(True)
        app.clear_logs_var.set.assert_called_once_with(True)
        app.parallel_var.set.assert_called_once_with(True)

    def test_no_mode_in_argv_leaves_the_mode_alone(self) -> None:
        app = shell()

        app._apply_tool_cli_options(
            MagicMock(live_mode=None, threshold=0.0, run_ms=0, auto_end=False)
        )

        app.run_mode.set.assert_not_called()
        app.threshold.set.assert_not_called()
        app.max_run.set.assert_not_called()

    def test_a_dry_mode_argv_selects_dry_run(self) -> None:
        app = shell(mode=LIVE_UPDATE)

        app._apply_cli_args(
            MagicMock(
                folder_path="",
                live_mode=False,
                auto_start=False,
                auto_end=False,
                clear_logs=False,
                parallel_run=False,
                threshold=0.0,
                run_ms=0,
            )
        )

        app.run_mode.set.assert_called_once_with(DRY_RUN)


class TestPresets:
    """A saved preset round-trips the settings the tool owns."""

    def test_collect_and_apply_round_trip(self) -> None:
        app = shell(mode=LIVE_UPDATE)

        settings = RestorationApp._collect_settings(app)
        app.threshold.set.reset_mock()
        app.max_run.set.reset_mock()
        app.run_mode.set.reset_mock()
        RestorationApp._apply_preset(app, settings)

        app.threshold.set.assert_called_once_with(DEFAULT_THRESHOLD)
        app.max_run.set.assert_called_once_with(DEFAULT_MAX_RUN_MS)
        app.run_mode.set.assert_called_once_with(LIVE_UPDATE)


class TestQueuedUiUpdates:
    """The processor's threads queue; only the Tk poller writes widgets."""

    def test_a_progress_tick_is_queued_not_rendered(self) -> None:
        app = shell()

        app._on_progress(1, 2, 1, 0, 0, "[REPAIRED] a.flac")

        assert app._ui_updates.get_nowait() == (
            "progress",
            1,
            2,
            1,
            0,
            0,
            "[REPAIRED] a.flac",
        )
        app.stats_label.config.assert_not_called()

    def test_a_fatal_error_is_queued_not_shown(self) -> None:
        app = shell()

        app._on_error("the temp folder is not writable")

        assert app._ui_updates.get_nowait() == (
            "error",
            "the temp folder is not writable",
        )


@pytest.mark.integration
class TestCompletionSeam:
    """The real batch into the handler the window binds."""

    def test_the_report_and_summary_carry_the_counts_the_run_published(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        folder = tmp_path / "music"
        folder.mkdir()
        clipped = np.clip(sine(0.9886), -0.8, 0.8)
        to_segment(clipped).export(str(folder / "clipped.flac"), format="flac")
        to_segment(sine(0.95)).export(str(folder / "clean.flac"), format="flac")
        app = shell()
        app._log_path = str(folder / RUN_REPORT_DRY_RUN)
        app._run_folder = str(folder)
        app._ui_updates = SimpleQueue()
        # The shell's writer needs the report path; everything else the batch
        # publishes is real.
        monkeypatch.setattr(app, "_render_audition", lambda: None)

        run_declipping(
            str(folder),
            True,
            on_complete=(
                lambda **payload: app._finish_run(
                    header=["RESTORATION (DECLIP) REPORT\n"], **payload
                )
            ),
        )
        app._poll_ui_updates()

        report = (folder / RUN_REPORT_DRY_RUN).read_text(encoding="utf-8")
        assert "SUMMARY:" in report
        assert "Repaired: 1" in report
        assert "Skipped: 1" in report
        assert "Errors: 0" in report
        rendered = app.summary_label.config.call_args.kwargs["text"]
        assert "Total: 2 files" in rendered
        assert f"{RestorationApp.TAGGED_LABEL}: 1" in rendered
        assert "Skipped: 1" in rendered

    def test_a_dry_run_leaves_the_result_half_unplayable(self) -> None:
        app = shell()

        app._dispatch_ui_message(("complete", 2, 1, 1, 0, 1.0))

        assert app.set_audition_state.call_args[0][1] is None
        assert "Dry Run" in app.set_audition_state.call_args[0][2]

    def test_a_live_run_offers_the_snapshot_against_the_repaired_file(self) -> None:
        app = shell(mode=LIVE_UPDATE)
        app._audition_original = Path("before.flac")
        app._audition_result = Path("after.flac")

        app._dispatch_ui_message(("complete", 1, 1, 0, 0, 1.0))

        original, result, caption = app.set_audition_state.call_args[0]
        assert (original, result) == (Path("before.flac"), Path("after.flac"))
        assert "Audition ready" in caption
