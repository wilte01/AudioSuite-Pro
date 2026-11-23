"""
Tests for mood_analysis_batch_tagger.ui.setup_tab — Setup tab construction.

Uses the session-scoped real Tk root from conftest.py so the shared
DriverControlsPanel builds genuine widgets.

Behaviour-lock (iteration-7 B3): the tool-own labels/defaults must
survive the shared-builder consolidation — if dedup removes a
tool-specific string or default, these tests fail.

Changed in 2.9.0: ``parent`` is the test's own frame on the shared root
and the fixture destroys it after each test, so the module no longer declares
``clean_shared_root``.
"""

import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from mood_analysis_batch_tagger.ui import setup_tab


def _make_vars(parent: tk.Frame) -> dict[str, tk.Variable]:
    return {
        "root_path": tk.StringVar(master=parent),
        "run_mode": tk.StringVar(master=parent, value="Dry Run"),
        "analysis_duration": tk.IntVar(master=parent, value=90),
        "auto_start": tk.BooleanVar(master=parent, value=False),
        "auto_end": tk.BooleanVar(master=parent, value=False),
        "clear_logs": tk.BooleanVar(master=parent, value=False),
        "parallel": tk.BooleanVar(master=parent, value=False),
        "parallel_mode": tk.BooleanVar(master=parent, value=True),
        "max_workers": tk.IntVar(master=parent, value=4),
    }


def _build(parent: tk.Frame, **overrides):
    """Build the tab into *parent*; returns (kwargs, widgets)."""
    vars_ = _make_vars(parent)
    kwargs = {
        "root_path": vars_["root_path"],
        "run_mode": vars_["run_mode"],
        "analysis_duration": vars_["analysis_duration"],
        "auto_start_var": vars_["auto_start"],
        "auto_end_var": vars_["auto_end"],
        "clear_logs_var": vars_["clear_logs"],
        "parallel_var": vars_["parallel"],
        "on_browse": MagicMock(),
        "on_start": MagicMock(),
        "parallel_mode": vars_["parallel_mode"],
        "max_workers": vars_["max_workers"],
        "preset_names": ["Preset A"],
        "on_save_preset": MagicMock(),
        "on_delete_preset": MagicMock(),
        "on_preset_selected": MagicMock(),
    }
    kwargs.update(overrides)
    widgets = setup_tab.build(parent, **kwargs)
    return kwargs, widgets


def _descendant_texts(widget: tk.Widget) -> list[str]:
    texts = []
    for child in widget.winfo_children():
        if isinstance(child, (tk.Label, tk.Button, tk.Checkbutton)):
            texts.append(str(child.cget("text")))
        texts.extend(_descendant_texts(child))
    return texts


class TestWiredWidgets:
    """build() returns every callable/widget the app needs."""

    def test_returns_expected_keys(self, parent: tk.Frame) -> None:
        _, widgets = _build(parent)
        assert isinstance(widgets["start_btn"], tk.Button)
        assert isinstance(widgets["preset_combo"], ttk.Combobox)
        assert callable(widgets["refresh_preset_list"])
        assert isinstance(widgets["controls_panel"], DriverControlsPanel)

    def test_start_button_invokes_on_start(self, parent: tk.Frame) -> None:
        kwargs, widgets = _build(parent)
        widgets["start_btn"].invoke()
        kwargs["on_start"].assert_called_once()

    def test_start_button_label_is_batch_mood_specific(self, parent: tk.Frame) -> None:
        _, widgets = _build(parent)
        assert widgets["start_btn"].cget("text") == "BEGIN BATCH MOOD ANALYSIS"


class TestDistinctToolSurfaces:
    """Tool-own texts survive consolidation (no over-eager dedup)."""

    def test_title_and_option_labels(self, parent: tk.Frame) -> None:
        _, _ = _build(parent)
        texts = _descendant_texts(parent)
        assert "Mood Analysis Batch Tagger" in texts
        assert "Analysis Duration (seconds):" in texts
        assert "(Lower values = faster processing, less accuracy)" in texts
        assert "How Mood Is Determined:" in texts

    def test_help_text_content_is_batch_proprietary(self, parent: tk.Frame) -> None:
        _, _ = _build(parent)
        joined = "\n".join(_descendant_texts(parent))
        assert "recursively scans" in joined
        assert "mood_analysis_batch_log.txt" in joined

    def test_parallel_row_present_with_caption(self, parent: tk.Frame) -> None:
        _, widgets = _build(parent)
        texts = _descendant_texts(widgets["start_btn"].master)
        assert "Parallel Processing" in texts
        assert "Workers:" in texts
        assert "(ProcessPoolExecutor bypasses GIL for CQT / FFT)" in texts


@pytest.mark.parametrize("driver_locked", [False, True])
def test_build_completes_without_raising(parent: tk.Frame, driver_locked: bool) -> None:
    _, widgets = _build(parent, driver_locked=driver_locked)
    assert widgets["controls_panel"] is not None
