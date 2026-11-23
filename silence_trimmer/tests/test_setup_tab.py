"""Tests for silence_trimmer.ui.setup_tab -- Setup tab construction.

Uses the session-scoped real Tk root from conftest.py so the shared
DriverControlsPanel builds genuine widgets.

Changed in 2.9.0: ``parent`` is the test's own frame on the shared root
and the fixture destroys it after each test, so the module no longer declares
``clean_shared_root``.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock

from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from silence_trimmer.ui import setup_tab


def _make_vars(parent: tk.Frame) -> dict[str, tk.Variable]:
    return {
        "folder_path": tk.StringVar(master=parent),
        "run_mode": tk.StringVar(master=parent, value="Dry Run"),
        "threshold": tk.IntVar(master=parent, value=-50),
        "fade_var": tk.BooleanVar(master=parent, value=False),
        "fade_in_duration": tk.IntVar(master=parent, value=500),
        "fade_out_duration": tk.IntVar(master=parent, value=1000),
        "auto_start": tk.BooleanVar(master=parent, value=False),
        "auto_end": tk.BooleanVar(master=parent, value=False),
        "clear_logs": tk.BooleanVar(master=parent, value=False),
        "parallel": tk.BooleanVar(master=parent, value=False),
        "parallel_mode": tk.BooleanVar(master=parent, value=False),
        "max_workers": tk.IntVar(master=parent, value=4),
    }


def _build(parent: tk.Frame, **overrides: object) -> tuple[dict, dict]:
    vars_ = _make_vars(parent)
    kwargs: dict[str, object] = {
        "folder_path": vars_["folder_path"],
        "run_mode": vars_["run_mode"],
        "threshold": vars_["threshold"],
        "fade_var": vars_["fade_var"],
        "fade_in_duration": vars_["fade_in_duration"],
        "fade_out_duration": vars_["fade_out_duration"],
        "on_browse": MagicMock(),
        "on_start": MagicMock(),
        "preset_names": ["Preset A"],
        "on_save_preset": MagicMock(),
        "on_delete_preset": MagicMock(),
        "on_preset_selected": MagicMock(),
        "auto_start_var": vars_["auto_start"],
        "auto_end_var": vars_["auto_end"],
        "clear_logs_var": vars_["clear_logs"],
        "parallel_var": vars_["parallel"],
        "parallel_mode": vars_["parallel_mode"],
        "max_workers": vars_["max_workers"],
    }
    kwargs.update(overrides)
    widgets = setup_tab.build(parent, **kwargs)  # type: ignore[arg-type]
    return kwargs, widgets


def _descendant_texts(widget: tk.Widget) -> list[str]:
    texts: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, (tk.Label, tk.Button, tk.Checkbutton, tk.LabelFrame)):
            texts.append(str(child.cget("text")))
        texts.extend(_descendant_texts(child))
    return texts


class TestWiredWidgets:
    """build() returns every callable/widget the app needs."""

    def test_returns_expected_keys(self, parent: tk.Frame) -> None:
        _, widgets = _build(parent)
        assert isinstance(widgets["start_btn"], tk.Button)
        assert isinstance(widgets["preset_combo"], ttk.Combobox)
        assert callable(widgets["refresh_presets"])
        assert isinstance(widgets["controls_panel"], DriverControlsPanel)

    def test_start_button_invokes_on_start(self, parent: tk.Frame) -> None:
        kwargs, widgets = _build(parent)
        widgets["start_btn"].invoke()
        kwargs["on_start"].assert_called_once()

    def test_panel_source_label_present_once(self, parent: tk.Frame) -> None:
        _, _ = _build(parent)
        texts = _descendant_texts(parent)
        assert texts.count("Source Music Directory:") == 1


class TestStandaloneMode:
    """Standalone launch: Source/Mode editable, Auto Start greyed out."""

    def test_source_and_mode_editable(self, parent: tk.Frame) -> None:
        _, widgets = _build(parent, driver_locked=False)
        panel: DriverControlsPanel = widgets["controls_panel"]
        assert str(panel.source_entry.cget("state")) == "normal"
        assert str(panel.mode_combo.cget("state")) == "readonly"

    def test_auto_start_disabled_auto_end_enabled(self, parent: tk.Frame) -> None:
        _, widgets = _build(parent, driver_locked=False)
        panel: DriverControlsPanel = widgets["controls_panel"]
        assert panel.auto_start_btn.cget("state") == "disabled"
        assert panel.auto_end_btn.cget("state") == "normal"


class TestDrivenMode:
    """Driver launch: whole Run Controls panel locked to inherited values."""

    def test_all_controls_locked(self, parent: tk.Frame) -> None:
        _, widgets = _build(parent, driver_locked=True)
        panel: DriverControlsPanel = widgets["controls_panel"]
        assert str(panel.source_entry.cget("state")) == "disabled"
        assert str(panel.mode_combo.cget("state")) == "disabled"
        assert panel.auto_start_btn.cget("state") == "disabled"
        assert panel.auto_end_btn.cget("state") == "disabled"

    def test_browse_disabled_when_driven(self, parent: tk.Frame) -> None:
        _, widgets = _build(parent, driver_locked=True)
        assert str(widgets["controls_panel"].browse_btn.cget("state")) == "disabled"


class TestDriverOnlyMirrorState:
    """Clear Logs / Parallel mirror driver state but stay inert."""

    def test_mirror_vars_bound_and_disabled(self, parent: tk.Frame) -> None:
        kwargs, widgets = _build(parent, driver_locked=True)
        panel: DriverControlsPanel = widgets["controls_panel"]
        assert str(panel.clear_logs_btn.cget("state")) == "disabled"
        assert str(panel.parallel_btn.cget("state")) == "disabled"

        clear_var = kwargs["clear_logs_var"]
        assert parent.tk.eval(str(panel.clear_logs_btn) + " cget -variable") == str(
            clear_var
        )

    def test_standalone_still_inert(self, parent: tk.Frame) -> None:
        _, widgets = _build(parent, driver_locked=False)
        panel: DriverControlsPanel = widgets["controls_panel"]
        assert panel.clear_logs_btn.cget("state") == "disabled"
        assert panel.parallel_btn.cget("state") == "disabled"


class TestLegacyRowsRemoved:
    """Folder row and mode block are replaced by the shared panel."""

    def test_no_legacy_mode_selector_in_config(self, parent: tk.Frame) -> None:
        _, _ = _build(parent)
        texts = _descendant_texts(parent)
        assert "Execution Mode:" not in texts

    def test_config_still_has_threshold_slider(self, parent: tk.Frame) -> None:
        _, _ = _build(parent)
        texts = _descendant_texts(parent)
        assert any("Silence Threshold" in t for t in texts)

    def test_config_has_fade_checkbox(self, parent: tk.Frame) -> None:
        _, _ = _build(parent)
        texts = _descendant_texts(parent)
        assert "Apply Smart Fades" in texts

    def test_parallel_workers_present(self, parent: tk.Frame) -> None:
        _, _ = _build(parent)
        texts = _descendant_texts(parent)
        assert "Parallel Processing" in texts
        assert "Workers:" in texts
