"""Tests for the Restoration window.

The window is a ``NoisePopToolApp``, so what is checked here is what is this
tool's own: the validation a run must pass, the driver's pre-fill routes, the
preset round trip, and -- ``TestCompletionSeam`` -- the real batch driven into
the completion handler, asserting the summary it renders.

``RestorationApp`` wires its completion and error callbacks through local
closures (the ``NoisePopToolApp`` peer shape), which the cross-tool AST lock
cannot resolve to a handler; this class is where that seam is locked instead.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest

from restoration.core.declipper import DEFAULT_MAX_RUN_MS, DEFAULT_THRESHOLD
from restoration.ui.app import RestorationApp

from .conftest import sine, to_segment


def shell(mode: str = "Dry Run") -> RestorationApp:
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
    app.auto_end_var = MagicMock()
    app.auto_end_var.get.return_value = False
    app.progress = MagicMock()
    app.overall_status = MagicMock()
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.completion_label = MagicMock()
    app.notebook = MagicMock()
    app.start_btn = MagicMock()
    app._tab_results = MagicMock()
    app._run_was_dry_run = mode == "Dry Run"
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
        assert RestorationApp.RESULTS_LABEL == "Repaired"


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

        assert app.run_mode.set.call_args[0][0] == "Live Update"
        app.threshold.set.assert_called_once_with(0.8)
        app.max_run.set.assert_called_once_with(12)
        app.auto_end_var.set.assert_called_once_with(True)

    def test_no_mode_in_argv_leaves_the_mode_alone(self) -> None:
        app = shell()

        app._apply_tool_cli_options(
            MagicMock(live_mode=None, threshold=0.0, run_ms=0, auto_end=False)
        )

        app.run_mode.set.assert_not_called()
        app.threshold.set.assert_not_called()
        app.max_run.set.assert_not_called()

    def test_a_dry_mode_argv_selects_dry_run(self) -> None:
        app = shell(mode="Live Update")

        app._apply_tool_cli_options(
            MagicMock(live_mode=False, threshold=0.0, run_ms=0, auto_end=False)
        )

        assert app.run_mode.set.call_args[0][0] == "Dry Run"


class TestPresets:
    """A saved preset round-trips the settings the tool owns."""

    def test_collect_and_apply_round_trip(self) -> None:
        app = shell(mode="Live Update")

        settings = RestorationApp._collect_settings(app)
        app.threshold.set.reset_mock()
        app.max_run.set.reset_mock()
        app.run_mode.set.reset_mock()
        RestorationApp._apply_preset(app, settings)

        app.threshold.set.assert_called_once_with(DEFAULT_THRESHOLD)
        app.max_run.set.assert_called_once_with(DEFAULT_MAX_RUN_MS)
        app.run_mode.set.assert_called_once_with("Live Update")


@pytest.mark.integration
class TestCompletionSeam:
    """The real batch into the handler the window's closure calls."""

    def test_the_summary_renders_the_counts_the_run_published(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        folder = tmp_path / "music"
        folder.mkdir()
        clipped = np.clip(sine(0.9886), -0.8, 0.8)
        to_segment(clipped).export(str(folder / "clipped.flac"), format="flac")
        to_segment(sine(0.95)).export(str(folder / "clean.flac"), format="flac")
        app = shell()
        # The base handler renders the summary; the closure would marshal it to
        # the Tk thread, which a shell has no loop for, so it is called here.
        monkeypatch.setattr(app, "_update_auto_end", lambda: None)

        from restoration.core.file_processor import run_declipping

        run_declipping(str(folder), True, on_complete=app._on_complete)

        rendered = app.summary_label.config.call_args.kwargs["text"]
        assert f"{RestorationApp.RESULTS_LABEL}: 1" in rendered
        assert "Skipped: 1" in rendered
        assert "Errors: 0" in rendered
        assert app.completion_label.config.call_args.kwargs["text"] == (
            RestorationApp.COMPLETION_LABEL
        )
