"""Tests for the shared DriverControlsPanel widget.

Changed in 2.3.1: locks the locked strip's colours in all four theme states -
a ``set_driven(True)`` panel used to paint the source entry with Tk's symbolic
``SystemButtonFace`` (2.04:1 under a dark theme) and the Browse button with
``SystemDisabledText`` on the accent (1.13:1) (PLAN_restoration_2026-10-31.md
T-03).
"""

import tkinter as tk
from collections.abc import Iterator
from contextlib import contextmanager
from tkinter import ttk
from unittest.mock import MagicMock

import pytest

from audio_suite_shared import styles
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


# ── Theme-conformance: the locked strip (T-03) ──────────────────────────────
#
# These assertions read the *effective* colours back off each control and
# resolve them through ``winfo_rgb()``, so a symbolic default is measured as the
# colour the display actually paints.  Asserting the ``styles`` constants would
# pass on the broken build: the bug is a colour the code did not pass.

#: WCAG AA for body text.
_MIN_TEXT_CONTRAST = 4.5

#: ``(theme mode, what the OS reports)``.  ``None`` leaves the real probe in
#: place; the two ``System`` states patch ``styles._get_system_theme`` rather
#: than ``os.name`` (AGENTS.md, *Verification Tooling Traps*).
_LOCKED_STRIP_STATES: tuple[tuple[str, str | None], ...] = (
    ("Light", None),
    ("Dark", None),
    ("System", "Light"),
    ("System", "Dark"),
)

_STATE_IDS = ("Light", "Dark", "System->Light", "System->Dark")


def _resolved_rgb(widget: tk.Misc, colour: str) -> tuple[int, int, int]:
    """The 8-bit RGB a colour name paints as, symbolic names included."""
    red, green, blue = widget.winfo_rgb(colour)
    return (red // 256, green // 256, blue // 256)


def _relative_luminance(colour: tuple[int, int, int]) -> float:
    """WCAG relative luminance of an 8-bit sRGB triple."""
    linear: list[float] = []
    for value in colour:
        scaled = value / 255
        linear.append(
            scaled / 12.92 if scaled <= 0.03928 else ((scaled + 0.055) / 1.055) ** 2.4
        )
    red, green, blue = linear
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def _contrast_ratio(widget: tk.Misc, foreground: str, background: str) -> float:
    """How far *foreground* sits from *background* on *widget*'s display."""
    lighter, darker = sorted(
        (
            _relative_luminance(_resolved_rgb(widget, foreground)),
            _relative_luminance(_resolved_rgb(widget, background)),
        ),
        reverse=True,
    )
    return (lighter + 0.05) / (darker + 0.05)


def _is_symbolic(colour: str) -> bool:
    """True for a Tk system colour, which ignores the suite theme entirely."""
    return colour.startswith("System")


@contextmanager
def _locked_strip(
    tk_root: tk.Tk,
    control_vars: dict[str, tk.Variable],
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    os_theme: str | None,
) -> Iterator[DriverControlsPanel]:
    """A driven (locked) panel built inside one theme state.

    The palette is pinned to the shipped default while the panel is measured:
    a live Windows-accent palette left active by another module's tests is read
    from the OS registry, its light tint decides ``BG_LIGHT``/``BG_READONLY``,
    and the accent decides the Browse button's fill - so the same assertion
    would measure a different suite depending on test order.  Contrast across
    every palette is a separate sweep.
    """
    if os_theme is not None:
        monkeypatch.setattr(styles, "_get_system_theme", lambda: os_theme)
    theme_before = styles.THEME_MODE
    palette_before = styles.get_active_palette_name()
    styles.set_active_palette(styles.DEFAULT_PALETTE)
    styles.set_theme_mode(mode)
    styles.apply_styles(ttk.Style())
    panel = _build_panel(tk_root, control_vars, on_browse=MagicMock())
    try:
        panel.set_driven(True)
        yield panel
    finally:
        panel.destroy()
        # Leave the shared palette, theme and ttk style matching what this test
        # found, or a later test would read this run's colours out of them.
        styles.set_theme_mode(theme_before)
        styles.set_active_palette(palette_before)
        styles.apply_styles(ttk.Style())


def _locked_surfaces(
    panel: DriverControlsPanel,
) -> list[tuple[str, tk.Misc, str, str]]:
    """``(label, widget, foreground, background)`` for each locked control."""
    assert panel.browse_btn is not None
    rows: list[tuple[str, tk.Misc, str, str]] = [
        (
            "Source Music Directory value",
            panel.source_entry,
            str(panel.source_entry.cget("disabledforeground")),
            str(panel.source_entry.cget("disabledbackground")),
        ),
        (
            "Browse button label",
            panel.browse_btn,
            str(panel.browse_btn.cget("disabledforeground")),
            str(panel.browse_btn.cget("background")),
        ),
    ]
    for label, toggle in (
        ("Auto Start", panel.auto_start_btn),
        ("Auto End", panel.auto_end_btn),
        ("Clear Logs", panel.clear_logs_btn),
        ("Parallel", panel.parallel_btn),
    ):
        rows.append(
            (
                f"{label} label",
                toggle,
                str(toggle.cget("disabledforeground")),
                str(toggle.cget("background")),
            )
        )
    return rows


class TestLockedStripFollowsTheTheme:
    """Every control ``set_driven(True)`` locks stays legible and themed."""

    @pytest.mark.parametrize(("mode", "os_theme"), _LOCKED_STRIP_STATES, ids=_STATE_IDS)
    def test_every_locked_control_clears_wcag_aa(
        self,
        tk_root: tk.Tk,
        control_vars: dict[str, tk.Variable],
        monkeypatch: pytest.MonkeyPatch,
        mode: str,
        os_theme: str | None,
    ) -> None:
        with _locked_strip(tk_root, control_vars, monkeypatch, mode, os_theme) as panel:
            measured = [
                (
                    label,
                    widget,
                    foreground,
                    background,
                    _contrast_ratio(widget, foreground, background),
                )
                for label, widget, foreground, background in _locked_surfaces(panel)
            ]
            # ttk has no per-widget disabled colours: the locked dropdown's
            # surface comes from the style map, which is what a user sees.
            style = ttk.Style()
            combo_foreground = style.lookup("TCombobox", "foreground", ("disabled",))
            combo_background = style.lookup(
                "TCombobox", "fieldbackground", ("disabled",)
            )
            measured.append(
                (
                    "Mode dropdown value",
                    panel.mode_combo,
                    str(combo_foreground),
                    str(combo_background),
                    _contrast_ratio(
                        panel.mode_combo, str(combo_foreground), str(combo_background)
                    ),
                )
            )

        failures = [
            f"{label}: {foreground} on {background} = {ratio:.2f}:1"
            for label, _widget, foreground, background, ratio in measured
            if ratio < _MIN_TEXT_CONTRAST
        ]
        state_label = f"{mode} (OS reports {os_theme})" if os_theme else mode
        assert not failures, (
            f"locked strip in {state_label} - text below {_MIN_TEXT_CONTRAST}:1:\n  "
            + "\n  ".join(failures)
        )

    @pytest.mark.parametrize(("mode", "os_theme"), _LOCKED_STRIP_STATES, ids=_STATE_IDS)
    def test_no_locked_surface_is_a_symbolic_system_colour(
        self,
        tk_root: tk.Tk,
        control_vars: dict[str, tk.Variable],
        monkeypatch: pytest.MonkeyPatch,
        mode: str,
        os_theme: str | None,
    ) -> None:
        """Tk's symbolic colours are fixed for both themes, which is the bug."""
        with _locked_strip(tk_root, control_vars, monkeypatch, mode, os_theme) as panel:
            surfaces = _locked_surfaces(panel)

        symbolic = [
            f"{label}: {foreground if _is_symbolic(foreground) else background}"
            for label, _widget, foreground, background in surfaces
            if _is_symbolic(foreground) or _is_symbolic(background)
        ]
        assert not symbolic, (
            "a locked control still paints a symbolic system colour, so it "
            "ignores the theme:\n  " + "\n  ".join(symbolic)
        )
