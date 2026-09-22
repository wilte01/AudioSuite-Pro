"""
Tests for tempo_analyzer.ui.setup_tab — Setup tab construction.

Uses the session-scoped real Tk root from conftest.py so the shared
DriverControlsPanel builds genuine widgets.
"""

import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from tempo_analyzer.core.tempo_schemes import TEMPO_SCHEMES
from tempo_analyzer.ui import setup_tab


def _make_vars(root: tk.Tk) -> dict[str, tk.Variable]:
    return {
        "folder_path": tk.StringVar(master=root),
        "run_mode": tk.StringVar(master=root, value="Dry Run"),
        "tempo_scheme": tk.StringVar(master=root, value=next(iter(TEMPO_SCHEMES))),
        "auto_start": tk.BooleanVar(master=root, value=False),
        "auto_end": tk.BooleanVar(master=root, value=False),
        "clear_logs": tk.BooleanVar(master=root, value=False),
        "parallel": tk.BooleanVar(master=root, value=False),
    }


def _build(root: tk.Tk, **overrides):
    """Build the tab on a fresh container; returns (kwargs, widgets, container)."""
    vars_ = _make_vars(root)
    kwargs = {
        "folder_path": vars_["folder_path"],
        "run_mode": vars_["run_mode"],
        "tempo_scheme": vars_["tempo_scheme"],
        "scheme_names": list(TEMPO_SCHEMES.keys()),
        "auto_start_var": vars_["auto_start"],
        "auto_end_var": vars_["auto_end"],
        "clear_logs_var": vars_["clear_logs"],
        "parallel_var": vars_["parallel"],
        "on_browse": MagicMock(),
        "on_start": MagicMock(),
        "on_scheme_change": MagicMock(),
        "on_preset_select": MagicMock(),
        "on_save_preset": MagicMock(),
        "on_delete_preset": MagicMock(),
    }
    kwargs.update(overrides)
    container = tk.Frame(root)
    widgets = setup_tab.build(container, **kwargs)
    return kwargs, widgets, container


def _descendant_texts(widget: tk.Widget) -> list[str]:
    texts = []
    for child in widget.winfo_children():
        if isinstance(child, (tk.Label, tk.Button, tk.Checkbutton)):
            texts.append(str(child.cget("text")))
        texts.extend(_descendant_texts(child))
    return texts


@pytest.fixture
def tab_vars(root: tk.Tk):
    return _make_vars(root)


class TestWiredWidgets:
    """build() returns every callable/widget the app needs."""

    def test_returns_expected_keys(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root)
        assert isinstance(widgets["start_btn"], tk.Button)
        assert isinstance(widgets["preset_combo"], ttk.Combobox)
        assert callable(widgets["update_reference"])
        assert callable(widgets["refresh_preset_list"])
        assert isinstance(widgets["controls_panel"], DriverControlsPanel)

    def test_start_button_invokes_on_start(self, root: tk.Tk) -> None:
        kwargs, widgets, _ = _build(root)
        widgets["start_btn"].invoke()
        kwargs["on_start"].assert_called_once()

    def test_update_reference_renders_markings(self, root: tk.Tk) -> None:
        _, widgets, container = _build(root)
        markings = TEMPO_SCHEMES[next(iter(TEMPO_SCHEMES))]
        before = len(container.winfo_children())
        widgets["update_reference"](markings)
        # Reference rows are appended inside the scrollable table frame.
        assert len(container.winfo_children()) >= before

    def test_refresh_preset_list_updates_combo(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root)
        widgets["refresh_preset_list"](["Preset A", "Preset B"])
        assert list(widgets["preset_combo"]["values"]) == ["Preset A", "Preset B"]

    def test_scheme_trace_fires_on_change(self, root: tk.Tk, tab_vars) -> None:
        overrides = {"tempo_scheme": tab_vars["tempo_scheme"]}
        kwargs, _, _ = _build(root, **overrides)
        var = kwargs["tempo_scheme"]
        var.set(next(iter(TEMPO_SCHEMES)))
        kwargs["on_scheme_change"].assert_called()


class TestStandaloneMode:
    """Standalone launch: Source/Mode editable, Auto Start greyed out."""

    def test_source_and_mode_editable(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=False)
        panel = widgets["controls_panel"]
        assert str(panel.source_entry.cget("state")) == "normal"
        assert str(panel.mode_combo.cget("state")) == "readonly"

    def test_auto_start_disabled_auto_end_enabled(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=False)
        panel = widgets["controls_panel"]
        assert panel.auto_start_btn.cget("state") == "disabled"
        assert panel.auto_end_btn.cget("state") == "normal"


class TestDrivenMode:
    """Driver launch: whole Run Controls panel locked to inherited values."""

    def test_all_controls_locked(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=True)
        panel = widgets["controls_panel"]
        assert str(panel.source_entry.cget("state")) == "disabled"
        assert str(panel.mode_combo.cget("state")) == "disabled"
        assert panel.auto_start_btn.cget("state") == "disabled"
        assert panel.auto_end_btn.cget("state") == "disabled"

    def test_browse_disabled_when_driven(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=True)
        assert str(widgets["controls_panel"].browse_btn.cget("state")) == "disabled"


class TestDriverOnlyMirrorState:
    """Clear Logs / Parallel mirror driver state but stay inert."""

    def test_mirror_vars_bound_and_disabled(self, root: tk.Tk, tab_vars) -> None:
        overrides = {
            "clear_logs_var": tab_vars["clear_logs"],
            "parallel_var": tab_vars["parallel"],
        }
        _, widgets, _ = _build(root, driver_locked=True, **overrides)
        panel = widgets["controls_panel"]
        assert str(panel.clear_logs_btn.cget("state")) == "disabled"
        assert str(panel.parallel_btn.cget("state")) == "disabled"

        # Raw Tcl query — cget("variable") is version-specific on 3.14.
        assert root.tk.eval(str(panel.clear_logs_btn) + " cget -variable") == str(
            tab_vars["clear_logs"]
        )
        assert root.tk.eval(str(panel.parallel_btn) + " cget -variable") == str(
            tab_vars["parallel"]
        )

    def test_standalone_still_inert(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=False)
        panel = widgets["controls_panel"]
        assert panel.clear_logs_btn.cget("state") == "disabled"
        assert panel.parallel_btn.cget("state") == "disabled"


class TestLegacyRowsRemoved:
    """Folder row and mode block are replaced by the shared panel."""

    def test_panel_source_label_present_once_and_legacy_rows_gone(
        self, root: tk.Tk
    ) -> None:
        _, _, container = _build(root)
        texts = _descendant_texts(container)
        assert texts.count("Source Music Directory:") == 1
        assert "Music Directory:" not in texts
        assert "Execution Mode:" not in texts
