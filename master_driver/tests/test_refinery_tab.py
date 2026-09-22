"""Tests for master_driver.ui.refinery_tab (REFINE tab single-strip layout).

The REFINE tab must show exactly one control bar: the shared
DriverControlsPanel.  The old duplicate injected bar (SELECT ALL + Mode +
Auto Start + Auto End + Clear Logs) is gone; only its SELECT ALL cheque
survives, merged into the front of the Run Controls strip.  The output
folder picker is retained.
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from typing import Any

from master_driver.state.app_state import AppState
from master_driver.ui import refinery_tab
from master_driver.ui.refinery_tab import _inject_select_all


def _build(root: tk.Tk) -> tuple[tk.Frame, AppState, tuple[Any, Any, dict[str, Any]]]:
    """Build the REFINE tab into a fresh frame; returns (parent, state, result)."""
    parent = tk.Frame(root)
    state = AppState(master=root)
    result = refinery_tab.build(
        parent,
        state,
        on_run=lambda: None,
        on_open_refinery=lambda: None,
    )
    return parent, state, result


def _descendant_texts(widget: tk.Widget) -> list[str]:
    """All descendant ``text`` option values, depth-first."""
    texts: list[str] = []
    for child in widget.winfo_children():
        try:
            texts.append(str(child.cget("text")))
        except tk.TclError:
            pass
        texts.extend(_descendant_texts(child))
    return texts


def _select_all_checkbuttons(widget: tk.Widget) -> list[tk.Checkbutton]:
    """Every descendant Checkbutton labelled ``SELECT ALL``."""
    found: list[tk.Checkbutton] = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Checkbutton):
            try:
                if child.cget("text") == "SELECT ALL":
                    found.append(child)
            except tk.TclError:
                pass
        found.extend(_select_all_checkbuttons(child))
    return found


def _select_all_checkbox(widget: tk.Widget) -> tk.Checkbutton:
    """The single SELECT ALL Checkbutton, or raise if not exactly one."""
    found = _select_all_checkbuttons(widget)
    assert len(found) == 1, f"expected exactly 1 SELECT ALL, got {len(found)}"
    return found[0]


def _find_label(widget: tk.Widget, text: str) -> tk.Label | None:
    """The first descendant Label whose ``text`` equals *text*."""
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            try:
                if child.cget("text") == text:
                    return child
            except tk.TclError:
                pass
        found = _find_label(child, text)
        if found is not None:
            return found
    return None


class TestSingleControlStrip:
    """Exactly one control bar — SELECT ALL merged into the Run Controls strip."""

    def test_select_all_lives_inside_controls_panel(self, root: tk.Tk) -> None:
        parent, _state, result = _build(root)
        setup_state = result[2]
        panel = setup_state["controls_panel"]
        checkboxes = _select_all_checkbuttons(parent)
        assert len(checkboxes) == 1
        assert checkboxes[0].master is panel.control_strip

    def test_mode_combo_shares_same_strip(self, root: tk.Tk) -> None:
        _parent, _state, result = _build(root)
        panel = result[2]["controls_panel"]
        assert panel.mode_combo.master is panel.control_strip
        assert panel.auto_start_btn.master is panel.control_strip
        assert panel.auto_end_btn.master is panel.control_strip

    def test_select_all_leads_the_strip(self, root: tk.Tk) -> None:
        _parent, _state, result = _build(root)
        panel = result[2]["controls_panel"]
        checkbox = _select_all_checkbox(panel)
        assert checkbox.grid_info()["column"] == 0
        # Existing controls shifted right to make room.
        mode_label = _find_label(panel, "Mode:")
        assert mode_label is not None
        assert mode_label.grid_info()["column"] == 1

    def test_no_duplicate_control_options(self, root: tk.Tk) -> None:
        parent, _state, _result = _build(root)
        texts = _descendant_texts(parent)
        assert texts.count("SELECT ALL") == 1
        assert texts.count("Mode:") == 1
        assert texts.count("Auto Start") == 1
        assert texts.count("Auto End") == 1
        assert texts.count("Clear Logs") == 1

    def test_output_folder_kept(self, root: tk.Tk) -> None:
        parent, _state, _result = _build(root)
        assert "Output folder (blank = in-place):" in _descendant_texts(parent)


class TestSelectAllBehaviour:
    """SELECT ALL toggles all five pipeline stage checkboxes.

    The toggle logic is driven via the stored ``refine_toggle_all`` callback
    rather than ``Checkbutton.invoke()`` so the tests are robust to the
    shared multi-root test environment (the checkbox widget and the Boolean
    vars can land on different Tcl interpreters; invoking the callback
    directly exercises the real command deterministically).
    """

    def test_selects_and_deselects_stages(self, root: tk.Tk) -> None:
        _parent, state, result = _build(root)
        setup_state = result[2]
        panel = setup_state["controls_panel"]
        stage_vars = setup_state["stage_vars"]
        toggle = panel.refine_toggle_all

        state.refinery_select_all_var.set(False)
        for var in stage_vars.values():
            var.set(False)
        toggle()  # reads var False -> all stages False
        assert not any(var.get() for var in stage_vars.values())

        state.refinery_select_all_var.set(True)
        toggle()  # reads var True -> all stages True
        assert all(var.get() for var in stage_vars.values())

    def test_write_guard_skips_unchanged_vars(self, root: tk.Tk) -> None:
        """Regression/guard rail: a stage var is only written when its value
        actually differs, so a repeat click cannot spin an update loop."""
        _parent, state, result = _build(root)
        setup_state = result[2]
        panel = setup_state["controls_panel"]
        stage_vars = setup_state["stage_vars"]
        toggle = panel.refine_toggle_all

        # In sync (var False, stages False): toggle target matches current
        # stage values -> zero writes.
        state.refinery_select_all_var.set(False)
        for var in stage_vars.values():
            var.set(False)

        counts: dict[str, int] = {name: 0 for name in stage_vars}

        def _count_writes(name: str) -> Callable[..., object]:
            def _inc(*_args: Any) -> None:
                counts[name] += 1

            return _inc

        for name, var in stage_vars.items():
            var.trace_add("write", _count_writes(name))

        toggle()
        assert counts == {name: 0 for name in stage_vars}
        assert not any(var.get() for var in stage_vars.values())

        # Out of sync (var True, stages False): one write per stage.
        state.refinery_select_all_var.set(True)
        toggle()
        assert counts == {name: 1 for name in stage_vars}
        assert all(var.get() for var in stage_vars.values())


class TestInjectionGuards:
    """_inject_select_all must be idempotent and safe for other tools."""

    def test_second_call_adds_no_duplicate(self, root: tk.Tk) -> None:
        parent, state, result = _build(root)
        _inject_select_all(result[2], state, result[1])
        assert len(_select_all_checkbuttons(parent)) == 1
        assert state.refinery_select_all_var.get() is False

    def test_missing_controls_panel_is_noop(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig

        state = AppState(master=root)
        _inject_select_all({}, state, StageConfig())  # must not raise
        assert state.refinery_select_all_var.get() is False


class TestDefensiveStageDefaults:
    """REFINE stage cards must start unchecked, matching SELECT ALL.

    Regression: the stage checkboxes inherited their value from the
    persisted ``refinery_settings.json`` (all True), so they showed checked
    while SELECT ALL started unchecked. Startup now forces UI vars and the
    run source-of-truth (``config``) to the unchecked default in lockstep.
    """

    def test_all_stage_cards_unchecked_at_startup(self, root: tk.Tk) -> None:
        _parent, _state, result = _build(root)
        stage_vars = result[2]["stage_vars"]
        root.update_idletasks()
        assert not any(var.get() for var in stage_vars.values())

    def test_config_matches_unchecked_ui(self, root: tk.Tk) -> None:
        _parent, _state, result = _build(root)
        config = result[1]
        stage_vars = result[2]["stage_vars"]
        for name, var in stage_vars.items():
            assert getattr(config, name) is False
            assert var.get() is False

    def test_select_all_can_turn_stages_on_with_config(self, root: tk.Tk) -> None:
        _parent, state, result = _build(root)
        stage_vars = result[2]["stage_vars"]
        config = result[1]
        panel = result[2]["controls_panel"]
        state.refinery_select_all_var.set(True)
        panel.refine_toggle_all()
        root.update_idletasks()
        assert all(var.get() for var in stage_vars.values())
        assert all(getattr(config, name) for name in stage_vars)
        assert config.declick is True and config.normalise is True


def test_build_returns_launch_button_config_and_state(root: tk.Tk) -> None:
    launch_btn, config, setup_state = _build(root)[2]
    assert isinstance(launch_btn, tk.Button)
    assert str(launch_btn.cget("text")) == "LAUNCH REFINERY"
    assert hasattr(config, "declick")
    assert "controls_panel" in setup_state
    assert "stage_vars" in setup_state


class TestRefineModeCombo:
    """The REFINE tab's Mode combo must display and drive ``state.global_mode``.

    Regression: the embedded DriverControlsPanel previously created its own
    short-lived StringVar that was garbage-collected, leaving the box blank.
    The panel is now wired to the driver's persistent ``state.global_mode``,
    so the value always renders and stays in sync with the execution mode.
    """

    def test_mode_combo_displays_global_mode(self, root: tk.Tk) -> None:
        parent, state, result = _build(root)
        panel = result[2]["controls_panel"]
        root.update_idletasks()
        assert panel.mode_combo.get() == "Dry Run"
        assert panel.mode_combo.cget("textvariable") == str(state.global_mode)

    def test_mode_combo_tracks_global_mode_changes(self, root: tk.Tk) -> None:
        _parent, state, result = _build(root)
        panel = result[2]["controls_panel"]
        state.global_mode.set("Live Update")
        root.update_idletasks()
        assert panel.mode_combo.get() == "Live Update"


class TestDriverOwnedControlsEnabled:
    """Auto Start / Auto End / Clear Logs must be live and driver-bound.

    Regression: the embedded DriverControlsPanel is built for child tools
    and therefore starts with Auto Start and Clear Logs greyed out. Inside
    the REFINE tab the driver is the host, so these must be clickable and
    bound to the driver's state vars (exactly like the ENRICH tab strip),
    otherwise the toggles can never reach launch_refinery / arg_builder.
    """

    def test_auto_start_enabled_and_bound(self, root: tk.Tk) -> None:
        _parent, state, result = _build(root)
        panel = result[2]["controls_panel"]
        assert panel.auto_start_btn.cget("state") == "normal"
        assert str(panel.auto_start_btn.cget("variable")) == str(
            state.refinery_auto_start
        )

    def test_clear_logs_enabled_and_bound(self, root: tk.Tk) -> None:
        _parent, state, result = _build(root)
        panel = result[2]["controls_panel"]
        assert panel.clear_logs_btn.cget("state") == "normal"
        assert str(panel.clear_logs_btn.cget("variable")) == str(state.clear_logs_var)

    def test_auto_end_enabled_and_bound(self, root: tk.Tk) -> None:
        _parent, state, result = _build(root)
        panel = result[2]["controls_panel"]
        assert panel.auto_end_btn.cget("state") == "normal"
        assert str(panel.auto_end_btn.cget("variable")) == str(state.refinery_auto_end)

    def test_toggle_reaches_driver_state(self, root: tk.Tk) -> None:
        _parent, state, result = _build(root)
        panel = result[2]["controls_panel"]
        state.refinery_auto_start.set(False)
        panel.auto_start_btn.invoke()
        assert state.refinery_auto_start.get() is True
        state.clear_logs_var.set(False)
        panel.clear_logs_btn.invoke()
        assert state.clear_logs_var.get() is True

    def test_parallel_stays_inert(self, root: tk.Tk) -> None:
        """The refinery runner path never exercises Parallel, so it stays
        greyed out rather than presenting a no-op control."""
        _parent, _state, result = _build(root)
        panel = result[2]["controls_panel"]
        assert panel.parallel_btn.cget("state") == "disabled"

    def test_missing_controls_panel_is_noop(self, root: tk.Tk) -> None:
        from master_driver.ui.refinery_tab import _activate_driver_run_controls

        state = AppState(master=root)
        _activate_driver_run_controls({}, state)  # must not raise
        assert state.refinery_auto_start.get() is False
