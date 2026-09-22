"""Tests for the shared DriverControlsPanel widget."""

import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.ui_driver_controls import DriverControlsPanel


@pytest.fixture
def control_vars(tk_root: tk.Tk) -> dict[str, tk.Variable]:
    """Fresh set of bound tkinter variables for one panel instance."""
    return {
        "source": tk.StringVar(master=tk_root),
        "mode": tk.StringVar(master=tk_root, value="Dry Run"),
        "auto_start": tk.BooleanVar(master=tk_root, value=False),
        "auto_end": tk.BooleanVar(master=tk_root, value=False),
    }


def _build_panel(
    tk_root: tk.Tk,
    control_vars: dict[str, tk.Variable],
    on_browse: MagicMock | None = None,
    bg: str | None = None,
    clear_logs_var: tk.BooleanVar | None = None,
    parallel_var: tk.BooleanVar | None = None,
) -> DriverControlsPanel:
    """Construct a panel from the shared variable set."""
    return DriverControlsPanel(
        tk_root,
        source_var=control_vars["source"],  # type: ignore[arg-type]
        mode_var=control_vars["mode"],  # type: ignore[arg-type]
        auto_start_var=control_vars["auto_start"],  # type: ignore[arg-type]
        auto_end_var=control_vars["auto_end"],  # type: ignore[arg-type]
        on_browse=on_browse,
        bg=bg,
        clear_logs_var=clear_logs_var,
        parallel_var=parallel_var,
    )


@pytest.fixture
def panel(tk_root: tk.Tk, control_vars: dict[str, tk.Variable]) -> DriverControlsPanel:
    """A DriverControlsPanel with a Browse callback."""
    return _build_panel(tk_root, control_vars, on_browse=MagicMock())


class TestWidgetCreation:
    """The panel creates every control shown on the Master Driver strip."""

    def test_creates_all_widgets(self, panel: DriverControlsPanel) -> None:
        assert isinstance(panel.source_entry, tk.Entry)
        assert isinstance(panel.browse_btn, tk.Button)
        assert isinstance(panel.mode_combo, ttk.Combobox)
        assert isinstance(panel.auto_start_btn, tk.Checkbutton)
        assert isinstance(panel.auto_end_btn, tk.Checkbutton)
        assert isinstance(panel.clear_logs_btn, tk.Checkbutton)
        assert isinstance(panel.parallel_btn, tk.Checkbutton)

    def test_mode_values_match_driver(self, panel: DriverControlsPanel) -> None:
        assert list(panel.mode_combo.cget("values")) == ["Dry Run", "Live Update"]

    def test_inert_options_disabled_on_creation(
        self, panel: DriverControlsPanel
    ) -> None:
        assert panel.clear_logs_btn.cget("state") == "disabled"
        assert panel.parallel_btn.cget("state") == "disabled"

    def test_source_var_bound_to_entry(
        self,
        tk_root: tk.Tk,
        control_vars: dict[str, tk.Variable],
    ) -> None:
        p = _build_panel(tk_root, control_vars)
        source_var = control_vars["source"]
        assert isinstance(source_var, tk.StringVar)
        source_var.set("D:/Music")
        assert p.source_entry.get() == "D:/Music"

    def test_browse_button_hidden_without_callback(
        self, tk_root: tk.Tk, control_vars: dict[str, tk.Variable]
    ) -> None:
        p = _build_panel(tk_root, control_vars)
        assert p.browse_btn is None

    def test_entry_lives_in_expanding_row_with_browse(
        self, panel: DriverControlsPanel
    ) -> None:
        """Regression: entry/browse share an inner row so the entry can
        expand full-width, while the control strip sits in its own frame."""
        assert isinstance(panel.source_entry.master, tk.Frame)
        assert panel.source_entry.master is not panel
        assert panel.browse_btn is not None
        assert panel.browse_btn.master is panel.source_entry.master

    def test_control_strip_is_separate_frame(self, panel: DriverControlsPanel) -> None:
        """Regression: Mode combo must not share geometry columns with the
        expanding source entry (which caused a large label/dropdown gap)."""
        for widget in (
            panel.mode_combo,
            panel.auto_start_btn,
            panel.auto_end_btn,
            panel.clear_logs_btn,
            panel.parallel_btn,
        ):
            assert widget.master is not panel.source_entry.master

    def test_control_strip_handle_exposed(self, panel: DriverControlsPanel) -> None:
        """The inner strip frame is reachable so callers (e.g. the Master
        Driver REFINE tab) can merge extra options into the same single row."""
        assert isinstance(panel.control_strip, tk.Frame)
        assert panel.mode_combo.master is panel.control_strip
        assert all(
            widget.master is panel.control_strip
            for widget in (
                panel.auto_start_btn,
                panel.auto_end_btn,
                panel.clear_logs_btn,
                panel.parallel_btn,
            )
        )


class TestStandaloneState:
    """set_driven(False): Mode/Auto End editable, Auto Start greyed out."""

    def test_editable_controls_enabled(self, panel: DriverControlsPanel) -> None:
        panel.set_driven(False)
        assert panel.source_entry.cget("state") == "normal"
        assert panel.browse_btn is not None
        assert panel.browse_btn.cget("state") == "normal"
        assert str(panel.mode_combo.cget("state")) == "readonly"
        assert panel.auto_end_btn.cget("state") == "normal"

    def test_auto_start_greyed_out_standalone(self, panel: DriverControlsPanel) -> None:
        panel.set_driven(False)
        assert panel.auto_start_btn.cget("state") == "disabled"

    def test_inert_options_still_disabled(self, panel: DriverControlsPanel) -> None:
        panel.set_driven(False)
        assert panel.clear_logs_btn.cget("state") == "disabled"
        assert panel.parallel_btn.cget("state") == "disabled"


class TestDrivenState:
    """set_driven(True): everything locked, inherited values still visible."""

    def test_all_widgets_locked(self, panel: DriverControlsPanel) -> None:
        panel.set_driven(True)
        assert panel.source_entry.cget("state") == "disabled"
        assert panel.browse_btn is not None
        assert panel.browse_btn.cget("state") == "disabled"
        assert str(panel.mode_combo.cget("state")) == "disabled"
        assert panel.auto_start_btn.cget("state") == "disabled"
        assert panel.auto_end_btn.cget("state") == "disabled"

    def test_values_survive_locking(
        self,
        tk_root: tk.Tk,
        control_vars: dict[str, tk.Variable],
    ) -> None:
        source_var = control_vars["source"]
        mode_var = control_vars["mode"]
        auto_end_var = control_vars["auto_end"]
        assert isinstance(source_var, tk.StringVar)
        assert isinstance(mode_var, tk.StringVar)
        assert isinstance(auto_end_var, tk.BooleanVar)
        source_var.set("D:/Library")
        mode_var.set("Live Update")
        auto_end_var.set(True)

        p = _build_panel(tk_root, control_vars, bg="#ffffff")
        p.set_driven(True)

        assert p.source_entry.get() == "D:/Library"
        assert p.mode_combo.get() == "Live Update"
        assert auto_end_var.get() is True


class TestBrowseButton:
    """The Browse button routes through the supplied callback."""

    def test_invoke_calls_callback(
        self, tk_root: tk.Tk, control_vars: dict[str, tk.Variable]
    ) -> None:
        callback = MagicMock()
        p = _build_panel(tk_root, control_vars, on_browse=callback)
        p.set_driven(False)
        assert p.browse_btn is not None
        p.browse_btn.invoke()
        callback.assert_called_once()


class TestDriverOnlyVarBinding:
    """Optional Clear Logs / Parallel vars let inert checkboxes mirror
    the driver's orchestration state (AGENTS.md shared-config pattern)."""

    @staticmethod
    def _bound_var(root: tk.Tk, widget: tk.Widget) -> str:
        """Raw Tcl query — immune to tkinter version-specific cget types."""
        return root.tk.eval(str(widget) + " cget -variable")

    def test_unbound_by_default(
        self, tk_root: tk.Tk, panel: DriverControlsPanel
    ) -> None:
        # Python 3.14 auto-generates an internal variable named after the
        # widget when none is supplied, so only assert no explicit binding.
        assert "PY_VAR" not in self._bound_var(tk_root, panel.clear_logs_btn)
        assert "PY_VAR" not in self._bound_var(tk_root, panel.parallel_btn)
        assert str(panel.clear_logs_btn.cget("state")) == "disabled"
        assert str(panel.parallel_btn.cget("state")) == "disabled"

    def test_bound_vars_mirror_state_while_inert(
        self, tk_root: tk.Tk, control_vars: dict[str, tk.Variable]
    ) -> None:
        clear_logs = tk.BooleanVar(master=tk_root, value=True)
        parallel = tk.BooleanVar(master=tk_root, value=False)
        p = _build_panel(
            tk_root,
            control_vars,
            clear_logs_var=clear_logs,
            parallel_var=parallel,
        )
        p.set_driven(True)

        assert self._bound_var(tk_root, p.clear_logs_btn) == str(clear_logs)
        assert self._bound_var(tk_root, p.parallel_btn) == str(parallel)
        # Mirrored state is visible but the controls remain driver-owned.
        assert str(p.clear_logs_btn.cget("state")) == "disabled"
        assert str(p.parallel_btn.cget("state")) == "disabled"
