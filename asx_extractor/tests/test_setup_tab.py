"""
Tests for asx_extractor.ui.setup_tab — Setup tab construction.

Uses the session-scoped real Tk root from conftest.py so the shared
DriverControlsPanel builds genuine widgets.
"""

import tkinter as tk
from unittest.mock import MagicMock

from asx_extractor.ui import setup_tab
from audio_suite_shared.ui_driver_controls import DriverControlsPanel


def _make_vars(root: tk.Tk) -> dict[str, tk.Variable]:
    return {
        "current_folder": tk.StringVar(master=root),
        "asx_action_mode": tk.StringVar(master=root, value="Dry Run (Simulated)"),
        "auto_start": tk.BooleanVar(master=root, value=False),
        "auto_end": tk.BooleanVar(master=root, value=False),
        "clear_logs": tk.BooleanVar(master=root, value=False),
        "parallel": tk.BooleanVar(master=root, value=False),
    }


def _build(root: tk.Tk, **overrides):
    """Build the tab on a fresh container; returns (kwargs, widgets, container)."""
    vars_ = _make_vars(root)
    kwargs = {
        "current_folder": vars_["current_folder"],
        "asx_action_mode": vars_["asx_action_mode"],
        "auto_start_var": vars_["auto_start"],
        "auto_end_var": vars_["auto_end"],
        "clear_logs_var": vars_["clear_logs"],
        "parallel_var": vars_["parallel"],
        "on_browse": MagicMock(),
        "on_start": MagicMock(),
        "preset_names": ["Preset A"],
        "on_save_preset": MagicMock(),
        "on_delete_preset": MagicMock(),
        "on_preset_selected": MagicMock(),
        "driver_locked": False,
    }
    kwargs.update(overrides)
    container = tk.Frame(root)
    widgets = setup_tab.build(container, **kwargs)
    return kwargs, widgets, container


def _descendant_texts(widget: tk.Widget) -> list[str]:
    texts = []
    for child in widget.winfo_children():
        if isinstance(child, (tk.Label, tk.Button, tk.Checkbutton, tk.LabelFrame)):
            texts.append(str(child.cget("text")))
        texts.extend(_descendant_texts(child))
    return texts


class TestWiredWidgets:
    """build() returns every callable/widget the app needs."""

    def test_returns_expected_keys(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root)
        assert isinstance(widgets["start_btn"], tk.Button)
        assert callable(widgets["refresh_preset_list"])
        assert isinstance(widgets["controls_panel"], DriverControlsPanel)

    def test_start_button_invokes_on_start(self, root: tk.Tk) -> None:
        kwargs, widgets, _ = _build(root)
        widgets["start_btn"].invoke()
        kwargs["on_start"].assert_called_once()

    def test_browse_button_invokes_on_browse(self, root: tk.Tk) -> None:
        kwargs, widgets, _ = _build(root)
        assert widgets["controls_panel"].browse_btn is not None
        widgets["controls_panel"].browse_btn.invoke()
        kwargs["on_browse"].assert_called_once()

    def test_domain_mode_values_offered(self, root: tk.Tk) -> None:
        """Mode dropdown offers the exact strings the driver passes."""
        _, widgets, _ = _build(root)
        values = widgets["controls_panel"].mode_combo.cget("values")
        assert "Dry Run (Simulated)" in values
        assert "Execute Extraction (Permanent)" in values

    def test_tool_controls_present(self, root: tk.Tk) -> None:
        _, _, container = _build(root)
        texts = _descendant_texts(container)
        assert "START EXTRACTION" in texts


class TestStandaloneMode:
    """Standalone launch: Source/Mode/Auto End editable, Auto Start greyed."""

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

    def test_display_checkbuttons_inert_standalone(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=False)
        panel = widgets["controls_panel"]
        assert panel.clear_logs_btn.cget("state") == "disabled"
        assert panel.parallel_btn.cget("state") == "disabled"


class TestDrivenMode:
    """Driver launch: whole Run Controls panel locked to inherited values."""

    def test_all_controls_locked(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root, driver_locked=True)
        panel = widgets["controls_panel"]
        assert str(panel.source_entry.cget("state")) == "disabled"
        assert str(panel.mode_combo.cget("state")) == "disabled"
        assert str(panel.browse_btn.cget("state")) == "disabled"
        assert panel.auto_start_btn.cget("state") == "disabled"
        assert panel.auto_end_btn.cget("state") == "disabled"


class TestDriverOnlyMirrorState:
    """Clear Logs / Parallel mirror driver state but stay inert."""

    def test_mirror_vars_bound_and_disabled(self, root: tk.Tk) -> None:
        vars_ = _make_vars(root)
        overrides = {
            "clear_logs_var": vars_["clear_logs"],
            "parallel_var": vars_["parallel"],
        }
        _, widgets, _ = _build(root, driver_locked=True, **overrides)
        panel = widgets["controls_panel"]
        # Raw Tcl query — cget("variable") is version-specific on 3.14.
        assert root.tk.eval(str(panel.clear_logs_btn) + " cget -variable") == str(
            vars_["clear_logs"]
        )
        assert root.tk.eval(str(panel.parallel_btn) + " cget -variable") == str(
            vars_["parallel"]
        )


class TestLegacyRowsRemoved:
    """Target Directory row and standalone mode selector are replaced."""

    def test_legacy_rows_gone_and_panel_label_unique(self, root: tk.Tk) -> None:
        _, _, container = _build(root)
        texts = _descendant_texts(container)
        assert texts.count("Source Music Directory:") == 1
        assert " Target Directory " not in texts
        assert " [ ? ] " not in texts
