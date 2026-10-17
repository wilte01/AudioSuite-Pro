"""Tests for cd_ripper.app — window construction, tab unlocking and wiring.

Changed in 1.2.0: covers the Results tab's re-rip callback reaching a real
re-rip of the flagged tracks (PLAN_feature_expansion.md D30).
"""

import tkinter as tk
from typing import Any
from unittest.mock import MagicMock

import pytest

from cd_ripper.app import CDRipperApp


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
