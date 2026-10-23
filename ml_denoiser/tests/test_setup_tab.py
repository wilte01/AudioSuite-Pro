"""Tests for ``ml_denoiser.ui.setup_tab`` — Setup tab construction.

Uses the session-scoped real Tk root from ``conftest.py`` so the shared
``BaseSetupFrame`` and its Run Controls panel build genuine widgets.

The panel is where the tool explains two things it cannot fix for the user: the
model is speech-trained, and a dry run still runs it. Both are asserted as text,
because a caption silently dropped in a refactor is how a caveat disappears.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from ml_denoiser.ui import setup_tab


def _build(
    root: tk.Tk, **overrides: Any
) -> tuple[dict[str, Any], dict[str, Any], tk.Frame]:
    """Build the tab on a fresh container; return (kwargs, widgets, container)."""
    kwargs: dict[str, Any] = {
        "folder_path": tk.StringVar(master=root),
        "run_mode": tk.StringVar(master=root, value="Dry Run"),
        "amount": tk.IntVar(master=root, value=100),
        "on_browse": MagicMock(),
        "on_start": MagicMock(),
        "auto_start_var": tk.BooleanVar(master=root, value=False),
        "auto_end_var": tk.BooleanVar(master=root, value=False),
        "clear_logs_var": tk.BooleanVar(master=root, value=False),
        "parallel_var": tk.BooleanVar(master=root, value=False),
        "preset_names": [],
        "on_save_preset": MagicMock(),
        "on_delete_preset": MagicMock(),
        "on_preset_selected": MagicMock(),
    }
    kwargs.update(overrides)
    container = tk.Frame(root)
    widgets = setup_tab.build(container, **kwargs)
    return kwargs, widgets, container


def _descendants(widget: tk.Misc) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    for child in widget.winfo_children():
        found.append(child)
        found.extend(_descendants(child))
    return found


def _texts(widget: tk.Misc) -> list[str]:
    return [
        str(child.cget("text"))
        for child in _descendants(widget)
        if isinstance(child, (tk.Label, tk.Button, tk.Checkbutton))
    ]


@pytest.fixture
def built(root: tk.Tk):
    kwargs, widgets, container = _build(root)
    try:
        yield kwargs, widgets, container
    finally:
        container.destroy()


class TestWiredWidgets:
    """build() returns every widget and callable the app needs."""

    def test_returns_expected_keys(self, built) -> None:
        _kwargs, widgets, _container = built

        assert isinstance(widgets["start_btn"], tk.Button)
        assert isinstance(widgets["preset_combo"], ttk.Combobox)
        assert callable(widgets["refresh_preset_list"])
        assert isinstance(widgets["controls_panel"], DriverControlsPanel)

    def test_start_button_invokes_on_start(self, built) -> None:
        kwargs, widgets, _container = built

        widgets["start_btn"].invoke()

        kwargs["on_start"].assert_called_once()


class TestAmountControl:
    """One control carries the denoise decision."""

    def test_the_slider_is_bound_to_the_amount_variable(self, root: tk.Tk) -> None:
        kwargs, _widgets, container = _build(root)
        try:
            scales = [
                child
                for child in _descendants(container)
                if isinstance(child, tk.Scale)
            ]
            assert scales, "the Setup tab has no amount slider"
            bound = {str(scale.cget("variable")) for scale in scales}
        finally:
            container.destroy()

        assert str(kwargs["amount"]) in bound

    def test_the_slider_spans_one_to_one_hundred_percent(self, root: tk.Tk) -> None:
        _kwargs, _widgets, container = _build(root)
        try:
            scale = next(
                child
                for child in _descendants(container)
                if isinstance(child, tk.Scale)
            )
            assert float(scale.cget("from")) == 1.0
            assert float(scale.cget("to")) == 100.0
        finally:
            container.destroy()

    def test_the_speech_caveat_is_stated(self, built) -> None:
        """The measured behaviour must be visible where the control is."""
        _kwargs, _widgets, container = built
        text = " ".join(_texts(container))

        assert "speech" in text.lower()
        assert "blend" in text.lower()

    def test_the_dry_run_cost_is_stated(self, built) -> None:
        _kwargs, _widgets, container = built
        text = " ".join(_texts(container))

        assert "Dry Run still runs the model" in text
        assert "writes nothing" in text


class TestDrivenMode:
    """A driver launch locks the shared Run Controls panel."""

    def test_all_controls_locked(self, root: tk.Tk) -> None:
        _kwargs, widgets, container = _build(root, driver_locked=True)
        try:
            panel = widgets["controls_panel"]
            assert str(panel.source_entry.cget("state")) == "disabled"
            assert str(panel.mode_combo.cget("state")) == "disabled"
        finally:
            container.destroy()
