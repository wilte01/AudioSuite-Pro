"""Tests for cd_ripper.app — window construction, tab unlocking and wiring.

Changed in 1.2.0: covers the Results tab's re-rip callback reaching a real
re-rip of the flagged tracks (PLAN_feature_expansion.md D30).
Changed in 1.2.0: covers the run note a finished rip leaves for the Master
Driver batch report (the tracks that did not rip).
"""

import tkinter as tk
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.run_outcome import read_outcome
from cd_ripper.app import DRIVER_TOOL_ID, CDRipperApp


class TestAppConstructionAndTabFlowD3:
    """Stage 3 / D3 (audit A4): the full CD Ripper window builds; the two
    notebook-unlocking callbacks execute against the real tabs."""

    @staticmethod
    @pytest.fixture()
    def app_root(root: tk.Tk) -> Any:
        top = tk.Toplevel(root)
        top.withdraw()
        try:
            yield top
        finally:
            top.destroy()

    def test_window_builds_with_disabled_rip_and_results(self, app_root) -> None:
        app = CDRipperApp(app_root)
        assert str(app.notebook.tab(1, "state")) == "disabled"
        assert str(app.notebook.tab(2, "state")) == "disabled"
        assert app.state["tracks"] == []
        assert app.rip_tab is not None
        assert app.results_tab is not None

    def test_ready_to_rip_unlocks_rip_tab(self, app_root) -> None:
        app = CDRipperApp(app_root)
        prepare = MagicMock()
        app.rip_tab.prepare = prepare  # type: ignore[method-assign]

        app._on_ready_to_rip()

        assert str(app.notebook.tab(1, "state")) == "normal"
        prepare.assert_called_once_with()

    def test_rip_complete_unlocks_results_tab(self, app_root) -> None:
        app = CDRipperApp(app_root)
        refresh = MagicMock()
        app.results_tab.refresh = refresh  # type: ignore[method-assign]
        assert str(app.notebook.tab(2, "state")) == "disabled"

        app._on_rip_complete()

        assert str(app.notebook.tab(2, "state")) == "normal"
        refresh.assert_called_once_with()


class TestRunNote:
    """A finished rip leaves the disc's outstanding work where a batch can see it."""

    @staticmethod
    @pytest.fixture()
    def app_root(root: tk.Tk) -> Any:
        top = tk.Toplevel(root)
        top.withdraw()
        try:
            yield top
        finally:
            top.destroy()

    @staticmethod
    def _results(*successes: bool) -> list[dict[str, Any]]:
        return [
            {
                "number": index + 1,
                "success": ok,
                "path": f"track{index + 1}.flac" if ok else "",
                "error": "" if ok else "Not accurate",
            }
            for index, ok in enumerate(successes)
        ]

    def test_failed_tracks_are_reported_with_the_disc_total(
        self, app_root: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = CDRipperApp(app_root)
        app.results_tab.refresh = MagicMock()
        app.state["rip_results"] = self._results(True, False, False)

        app._on_rip_complete()

        assert read_outcome(DRIVER_TOOL_ID) == "2 of 3 tracks did not rip"

    def test_a_clean_disc_reports_nothing(
        self, app_root: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = CDRipperApp(app_root)
        app.results_tab.refresh = MagicMock()
        app.state["rip_results"] = self._results(True, True)

        app._on_rip_complete()

        assert read_outcome(DRIVER_TOOL_ID) == ""

    def test_re_ripping_the_last_flagged_track_clears_the_note(
        self, app_root: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The note describes the disc's *current* results, not a past session."""
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = CDRipperApp(app_root)
        app.results_tab.refresh = MagicMock()
        app.state["rip_results"] = self._results(True, False)
        app._on_rip_complete()
        assert read_outcome(DRIVER_TOOL_ID) == "1 of 2 tracks did not rip"

        # A re-rip replaces that track's row (see RipTab._record_result).
        app.state["rip_results"] = self._results(True, True)
        app._on_rip_complete()

        assert read_outcome(DRIVER_TOOL_ID) == ""


class TestReRipWiring:
    """D30: the Results tab's action reaches a real re-rip of those tracks."""

    @staticmethod
    @pytest.fixture()
    def app_root(root: tk.Tk) -> Any:
        top = tk.Toplevel(root)
        top.withdraw()
        try:
            yield top
        finally:
            top.destroy()

    def test_state_exposes_the_rerip_callback(self, app_root) -> None:
        app = CDRipperApp(app_root)
        assert callable(app.state["on_rerip"])

    def test_rerip_selects_the_rip_tab_and_passes_the_numbers(self, app_root) -> None:
        app = CDRipperApp(app_root)
        re_rip = MagicMock()
        app.rip_tab.re_rip = re_rip  # type: ignore[method-assign]
        assert str(app.notebook.tab(1, "state")) == "disabled"

        app.state["on_rerip"]([2, 4])

        assert str(app.notebook.tab(1, "state")) == "normal"
        assert app.notebook.index("current") == 1
        re_rip.assert_called_once_with([2, 4])
