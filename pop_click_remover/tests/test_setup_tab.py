"""Tests for pop_click_remover.ui.setup_tab -- Setup tab construction.

Uses the session-scoped real Tk root from conftest.py so the shared
DriverControlsPanel builds genuine widgets.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock

from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from pop_click_remover.ui import setup_tab


def _make_vars(root: tk.Tk) -> dict[str, tk.Variable]:
    return {
        "folder_path": tk.StringVar(master=root),
        "run_mode": tk.StringVar(master=root, value="Dry Run"),
        "sensitivity": tk.DoubleVar(master=root, value=0.31),
        "max_width": tk.IntVar(master=root, value=2),
        "auto_start": tk.BooleanVar(master=root, value=False),
        "auto_end": tk.BooleanVar(master=root, value=False),
        "clear_logs": tk.BooleanVar(master=root, value=False),
        "parallel": tk.BooleanVar(master=root, value=False),
    }


def _build(root: tk.Tk, **overrides: object) -> tuple[dict, dict, tk.Frame]:
    vars_ = _make_vars(root)
    kwargs: dict[str, object] = {
        "folder_path": vars_["folder_path"],
        "run_mode": vars_["run_mode"],
        "sensitivity": vars_["sensitivity"],
        "max_width": vars_["max_width"],
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
    }
    kwargs.update(overrides)
    container = tk.Frame(root)
    widgets = setup_tab.build(container, **kwargs)  # type: ignore[arg-type]
    return kwargs, widgets, container


def _descendant_texts(widget: tk.Widget) -> list[str]:
    texts: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, (tk.Label, tk.Button, tk.Checkbutton)):
            texts.append(str(child.cget("text")))
        texts.extend(_descendant_texts(child))
    return texts


class TestWiredWidgets:
    """build() returns every callable/widget the app needs."""

    def test_returns_expected_keys(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root)
        assert isinstance(widgets["start_btn"], tk.Button)
        assert isinstance(widgets["preset_combo"], ttk.Combobox)
        assert callable(widgets["refresh_preset_list"])
        assert isinstance(widgets["controls_panel"], DriverControlsPanel)

    def test_start_button_invokes_on_start(self, root: tk.Tk) -> None:
        kwargs, widgets, _ = _build(root)
        widgets["start_btn"].invoke()
        kwargs["on_start"].assert_called_once()


class TestStandaloneMode:
    """Standalone launch: Source/Mode editable, Auto Start greyed out."""

    def test_source_and_mode_editable(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=False)
        panel: DriverControlsPanel = widgets["controls_panel"]
        assert str(panel.source_entry.cget("state")) == "normal"
        assert str(panel.mode_combo.cget("state")) == "readonly"

    def test_auto_start_disabled_auto_end_enabled(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=False)
        panel: DriverControlsPanel = widgets["controls_panel"]
        assert panel.auto_start_btn.cget("state") == "disabled"
        assert panel.auto_end_btn.cget("state") == "normal"


class TestDrivenMode:
    """Driver launch: whole Run Controls panel locked to inherited values."""

    def test_all_controls_locked(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=True)
        panel: DriverControlsPanel = widgets["controls_panel"]
        assert str(panel.source_entry.cget("state")) == "disabled"
        assert str(panel.mode_combo.cget("state")) == "disabled"
        assert panel.auto_start_btn.cget("state") == "disabled"
        assert panel.auto_end_btn.cget("state") == "disabled"

    def test_browse_disabled_when_driven(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=True)
        assert str(widgets["controls_panel"].browse_btn.cget("state")) == "disabled"


class TestDriverOnlyMirrorState:
    """Clear Logs / Parallel mirror driver state but stay inert."""

    def test_mirror_vars_bound_and_disabled(self, root: tk.Tk) -> None:
        kwargs, widgets, _ = _build(root, driver_locked=True)
        panel: DriverControlsPanel = widgets["controls_panel"]
        assert str(panel.clear_logs_btn.cget("state")) == "disabled"
        assert str(panel.parallel_btn.cget("state")) == "disabled"

        clear_var = kwargs["clear_logs_var"]
        assert root.tk.eval(str(panel.clear_logs_btn) + " cget -variable") == str(
            clear_var
        )

    def test_standalone_still_inert(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=False)
        panel: DriverControlsPanel = widgets["controls_panel"]
        assert panel.clear_logs_btn.cget("state") == "disabled"
        assert panel.parallel_btn.cget("state") == "disabled"


class TestLegacyRowsRemoved:
    """Folder row and mode block are replaced by the shared panel."""

    def test_panel_source_label_present_once(self, root: tk.Tk) -> None:
        _, _, container = _build(root)
        texts = _descendant_texts(container)
        assert texts.count("Source Music Directory:") == 1
        assert "Music Directory:" not in texts
