"""
Tests for replaygain_analyzer.ui.setup_tab

Validates the Run Controls panel integration:
  - build() wires every returned widget key
  - standalone launch keeps Source/Browse, Mode and Auto End editable
    while Auto Start stays greyed out (driver-only)
  - driver-launched build locks the whole panel to inherited values
  - legacy folder / mode rows are fully replaced by the shared panel
"""

import tkinter as tk

import pytest

from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from replaygain_analyzer.ui import setup_tab


def _make_vars(root):
    # Explicit master keeps every var on the session root's interpreter,
    # immune to other packages' tests disturbing tkinter's default root.
    return {
        "folder_path": tk.StringVar(master=root, value=""),
        "target_lufs": tk.StringVar(master=root, value="-16.0"),
        "run_mode": tk.StringVar(master=root, value="Dry Run"),
        "auto_start_var": tk.BooleanVar(master=root, value=False),
        "auto_end_var": tk.BooleanVar(master=root, value=False),
        "clear_logs_var": tk.BooleanVar(master=root, value=False),
        "parallel_var": tk.BooleanVar(master=root, value=False),
        "apply_lossless_gain_var": tk.BooleanVar(master=root, value=False),
    }


def _build(root, **overrides):
    kwargs = _make_vars(root)
    callbacks = {
        "on_browse_calls": [],
        "on_start_calls": [],
    }
    controls = setup_tab.build(
        root,
        folder_path=kwargs["folder_path"],
        target_lufs=kwargs["target_lufs"],
        run_mode=kwargs["run_mode"],
        auto_start_var=kwargs["auto_start_var"],
        auto_end_var=kwargs["auto_end_var"],
        clear_logs_var=kwargs["clear_logs_var"],
        parallel_var=kwargs["parallel_var"],
        apply_lossless_gain_var=kwargs["apply_lossless_gain_var"],
        on_browse=lambda: callbacks["on_browse_calls"].append(True),
        on_start=lambda: callbacks["on_start_calls"].append(True),
        **overrides,
    )
    return kwargs, controls, callbacks


def _descendant_texts(widget):
    """Collect the 'text' option of every descendant widget."""
    texts: list[str] = []
    for child in widget.winfo_children():
        try:
            texts.append(str(child.cget("text")))
        except tk.TclError:
            pass
        texts.extend(_descendant_texts(child))
    return texts


class TestBuildReturnsWiredWidgets:
    def test_returns_all_documented_keys(self, root):
        _, controls, _ = _build(root)
        assert set(controls) == {
            "start_btn",
            "preset_combo",
            "refresh_preset_list",
            "controls_panel",
        }

    def test_controls_panel_is_shared_widget(self, root):
        _, controls, _ = _build(root)
        assert isinstance(controls["controls_panel"], DriverControlsPanel)

    def test_start_button_invokes_on_start(self, root):
        _, controls, callbacks = _build(root)
        controls["start_btn"].invoke()
        assert callbacks["on_start_calls"] == [True]

    def test_browse_button_invokes_on_browse(self, root):
        _, controls, callbacks = _build(root)
        panel = controls["controls_panel"]
        assert panel.browse_btn is not None
        assert panel.browse_btn.cget("text") == "Browse"
        panel.browse_btn.invoke()
        assert callbacks["on_browse_calls"] == [True]

    def test_source_entry_bound_to_folder_var(self, root):
        kwargs, controls, _ = _build(root)
        kwargs["folder_path"].set("D:/Music")
        assert controls["controls_panel"].source_entry.get() == "D:/Music"

    def test_refresh_preset_list_updates_combo(self, root):
        _, controls, _ = _build(root)
        combo = controls["preset_combo"]
        controls["refresh_preset_list"](["Album", "Streaming"])
        assert list(combo["values"]) == ["Album", "Streaming"]
        assert combo.get() == "Album"


class TestStandalonePanelState:
    """Standalone: Mode/Auto End editable, Auto Start + driver-only inert."""

    @pytest.fixture
    def panel(self, root):
        _, controls, _ = _build(root, driver_locked=False)
        return controls["controls_panel"]

    def test_source_and_browse_editable(self, panel):
        assert str(panel.source_entry.cget("state")) == "normal"
        assert panel.browse_btn is not None
        assert str(panel.browse_btn.cget("state")) == "normal"

    def test_mode_combo_readonly_but_present(self, panel):
        assert str(panel.mode_combo.cget("state")) == "readonly"

    def test_auto_end_enabled_auto_start_disabled(self, panel):
        assert str(panel.auto_end_btn.cget("state")) == "normal"
        assert str(panel.auto_start_btn.cget("state")) == "disabled"

    def test_driver_only_options_inert_with_caption(self, panel):
        assert str(panel.clear_logs_btn.cget("state")) == "disabled"
        assert str(panel.parallel_btn.cget("state")) == "disabled"
        assert "(driver only)" in _descendant_texts(panel)


class TestDrivenPanelState:
    """Driver launch: inherited values visible but fully locked."""

    @pytest.fixture
    def panel(self, root):
        _, controls, _ = _build(root, driver_locked=True)
        return controls["controls_panel"]

    def test_source_locked(self, panel):
        assert str(panel.source_entry.cget("state")) == "disabled"
        assert panel.browse_btn is not None
        assert str(panel.browse_btn.cget("state")) == "disabled"

    def test_mode_and_checkbuttons_locked(self, panel):
        assert str(panel.mode_combo.cget("state")) == "disabled"
        assert str(panel.auto_start_btn.cget("state")) == "disabled"
        assert str(panel.auto_end_btn.cget("state")) == "disabled"


class TestLegacyRowsRemoved:
    """The old folder row and mode selector must not coexist with the panel."""

    def test_no_duplicate_folder_or_mode_labels(self, root):
        # Build inside a fresh container so the widget walk is not
        # polluted by panels created by earlier tests on the shared root.
        container = tk.Frame(root)
        _build(container)
        texts = _descendant_texts(container)
        assert texts.count("Source Music Directory:") == 1
        assert "Music Directory:" not in texts
        assert "Select Mode:" not in texts


class TestLosslessGainCheckbox:
    """apply_lossless_gain_var checkbox renders and binds correctly."""

    def test_checkbox_present_when_var_provided(self, root):
        container = tk.Frame(root)
        _, controls, _ = _build(container)
        texts = _descendant_texts(container)
        assert any("losslessly" in t.lower() for t in texts)

    def test_checkbox_not_present_when_var_none(self, root):
        container = tk.Frame(root)
        setup_tab.build(
            container,
            folder_path=tk.StringVar(master=root),
            target_lufs=tk.StringVar(master=root),
            run_mode=tk.StringVar(master=root),
            auto_start_var=tk.BooleanVar(master=root),
            auto_end_var=tk.BooleanVar(master=root),
            clear_logs_var=tk.BooleanVar(master=root),
            parallel_var=tk.BooleanVar(master=root),
            apply_lossless_gain_var=None,
            on_browse=lambda: None,
            on_start=lambda: None,
        )
        texts = _descendant_texts(container)
        assert not any("losslessly" in t.lower() for t in texts)


class TestDriverOnlyMirrorState:
    """Clear Logs / Parallel checkboxes mirror driver state, stay inert."""

    def test_mirror_vars_bound_and_disabled(self, root) -> None:
        kwargs, controls, _ = _build(root, driver_locked=True)
        panel = controls["controls_panel"]
        assert str(panel.clear_logs_btn.cget("state")) == "disabled"
        assert str(panel.parallel_btn.cget("state")) == "disabled"

        # Raw Tcl query — cget("variable") is version-specific on 3.14.
        assert root.tk.eval(str(panel.clear_logs_btn) + " cget -variable") == str(
            kwargs["clear_logs_var"]
        )
        assert root.tk.eval(str(panel.parallel_btn) + " cget -variable") == str(
            kwargs["parallel_var"]
        )
