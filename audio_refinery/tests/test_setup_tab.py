# Changed in 2.7.0: the EQ panel's table, curve and write-back are locked (F-S1).
"""Tests for audio_refinery.ui.setup_tab.
Changed in 1.1.0: added EnhancementParams field-parity tests and a
slider-to-config sync regression test (D24).

Changed in 2.3.1: carries this window's change for its module (see
CHANGELOG.md and TECHNICAL_CHANGELOG.md).
"""

from __future__ import annotations

import gc
import itertools
import tkinter as tk
from tkinter import ttk
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.ui_driver_controls import DriverControlsPanel

_MODE_VAR_IDS = itertools.count()


def _mode_var(root: tk.Tk, value: str) -> tk.StringVar:
    """Create a mode variable with a stable, unique Tcl name, bound to the
    supplied root's interpreter (not ``tk._default_root``)."""
    return tk.StringVar(root, value=value, name=f"_test_mode_cbo_{next(_MODE_VAR_IDS)}")


def _make_app() -> object:
    """Build a minimal AudioRefineryApp-like stub for testing."""
    app = object.__new__(type("Stub", (), {}))
    app.root = MagicMock(spec=tk.Tk)
    app.source_path = tk.StringVar()
    app.output_path = tk.StringVar()
    app.auto_start_var = tk.BooleanVar(value=False)
    app.auto_end_var = tk.BooleanVar(value=False)
    app.clear_logs_var = tk.BooleanVar(value=False)
    app.parallel_var = tk.BooleanVar(value=False)
    return app


class TestStagePanelSync:
    """Declick, Trim and Normalise controls write back into the stage params.

    Regression (U-04): until 2.6.0 each of those three panels bound a
    throwaway Tk variable, so moving REFINE's Click Sensitivity, Trim
    Threshold or Target LUFS slider changed a value the pipeline never read and
    the run used the stored setting. The panels' variables are captured here
    through the shared builders they hand their widgets, then set, and the
    config the pipeline reads is asserted.
    """

    def _build(self, root: tk.Tk, config: Any) -> dict[str, Any]:
        from audio_refinery.ui import setup_tab

        return setup_tab.build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )

    def _capture(self, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        """Record the variables each embedded panel binds its widgets to."""
        import audio_normalizer.ui.setup_tab as normalise_ui
        import pop_click_remover.ui.setup_tab as declick_ui
        import silence_trimmer.ui.setup_tab as trim_ui

        captured: dict[str, Any] = {}

        original_declick = declick_ui.build_config_panel
        original_trim = trim_ui.build_config_panel
        original_normalise = normalise_ui.build_config_panel

        def capture_declick(
            parent: tk.Misc,
            run_mode: tk.StringVar | None,
            sensitivity: tk.DoubleVar,
            max_width: tk.IntVar,
        ) -> None:
            captured["sensitivity"] = sensitivity
            captured["max_width"] = max_width
            return original_declick(parent, run_mode, sensitivity, max_width)

        def capture_trim(
            parent: tk.Misc,
            run_mode: tk.StringVar | None,
            threshold: tk.IntVar,
            fade: tk.BooleanVar,
            fade_in: tk.IntVar,
            fade_out: tk.IntVar,
        ) -> None:
            captured["threshold"] = threshold
            captured["fade"] = fade
            captured["fade_in"] = fade_in
            captured["fade_out"] = fade_out
            return original_trim(parent, run_mode, threshold, fade, fade_in, fade_out)

        def capture_normalise(
            parent: tk.Misc,
            run_mode: tk.StringVar | None,
            target_lufs: tk.DoubleVar,
            tolerance: tk.DoubleVar,
            true_peak: tk.DoubleVar | None = None,
            lra: tk.DoubleVar | None = None,
        ) -> None:
            captured["target_lufs"] = target_lufs
            captured["tolerance"] = tolerance
            captured["true_peak"] = true_peak
            captured["lra"] = lra
            return original_normalise(
                parent,
                run_mode,
                target_lufs,
                tolerance,
                true_peak=true_peak,
                lra=lra,
            )

        monkeypatch.setattr(declick_ui, "build_config_panel", capture_declick)
        monkeypatch.setattr(trim_ui, "build_config_panel", capture_trim)
        monkeypatch.setattr(normalise_ui, "build_config_panel", capture_normalise)
        return captured

    def test_declick_sliders_write_back(
        self, root: tk.Tk, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig()
        captured = self._capture(monkeypatch)
        self._build(root, config)

        captured["sensitivity"].set(0.05)
        captured["max_width"].set(7)

        assert config.declick_params.sensitivity == 0.05
        assert config.declick_params.max_width_ms == 7

    def test_trim_controls_write_back(
        self, root: tk.Tk, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig()
        captured = self._capture(monkeypatch)
        self._build(root, config)

        captured["threshold"].set(-35)
        captured["fade"].set(True)
        captured["fade_in"].set(250)
        captured["fade_out"].set(750)

        assert config.trim_params.threshold == -35
        assert config.trim_params.apply_fade is True
        assert config.trim_params.fade_in_ms == 250
        assert config.trim_params.fade_out_ms == 750

    def test_normalise_controls_write_back(
        self, root: tk.Tk, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig()
        captured = self._capture(monkeypatch)
        self._build(root, config)

        captured["target_lufs"].set(-18.0)
        captured["tolerance"].set(1.2)
        captured["true_peak"].set(-3.0)
        captured["lra"].set(7.0)

        assert config.normalise_params.target_lufs == -18.0
        assert config.normalise_params.tolerance == 1.2
        assert config.normalise_params.true_peak == -3.0
        assert config.normalise_params.lra == 7.0

    def test_normalise_strategy_choice_writes_back(
        self, root: tk.Tk, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui import setup_tab

        config = StageConfig()
        self._capture(monkeypatch)
        # Build into this test's own frame so the session-scoped root's other
        # widgets (other tests' mode combos) cannot match the search.
        frame = tk.Frame(root)
        setup_tab.build(
            parent=frame,
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )

        combos: list[ttk.Combobox] = [
            widget
            for widget in _walk(frame, ttk.Combobox)
            if isinstance(widget, ttk.Combobox)
            and "Lossless (MP3 global gain)" in tuple(widget.cget("values"))
        ]
        assert len(combos) == 1

        combos[0].set("Lossless (MP3 global gain)")

        assert config.normalise_params.mode == "lossless"


class TestSetupTabBuild:
    """Tests for setup_tab.build() return value and panel embedding."""

    def test_returns_dict(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        assert isinstance(result, dict)

    def test_dict_has_start_btn(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        assert "start_btn" in result
        assert isinstance(result["start_btn"], tk.Button)

    def test_dict_has_reset_btn(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        assert "reset_btn" in result
        assert isinstance(result["reset_btn"], tk.Button)

    def test_dict_has_controls_panel(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        assert "controls_panel" in result
        assert isinstance(result["controls_panel"], DriverControlsPanel)

    def test_panel_source_label(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        panel: DriverControlsPanel = result["controls_panel"]
        texts = [
            child.cget("text")
            for child in panel.winfo_children()
            if isinstance(child, tk.Label)
        ]
        assert "Source Music Directory:" in texts

    def test_panel_mode_label(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        panel: DriverControlsPanel = result["controls_panel"]

        def _descendant_texts(w: tk.Widget) -> list[str]:
            texts: list[str] = []
            for child in w.winfo_children():
                try:
                    texts.append(str(child.cget("text")))
                except Exception:
                    # cget("text") is invalid on some widget types (e.g.
                    # ttk.Progressbar) — skip widgets without a text option.
                    pass
                texts.extend(_descendant_texts(child))
            return texts

        assert "Mode:" in _descendant_texts(panel)

    def test_panel_checkbox_labels(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        panel: DriverControlsPanel = result["controls_panel"]

        def _descendant_texts(w: tk.Widget) -> list[str]:
            texts: list[str] = []
            for child in w.winfo_children():
                try:
                    texts.append(str(child.cget("text")))
                except Exception:
                    # cget("text") is invalid on some widget types (e.g.
                    # ttk.Progressbar) — skip widgets without a text option.
                    pass
                texts.extend(_descendant_texts(child))
            return texts

        all_texts = _descendant_texts(panel)
        assert "Auto Start" in all_texts
        assert "Auto End" in all_texts
        assert "Clear Logs" in all_texts
        assert "Parallel" in all_texts

    def test_driver_locked_disables_widgets(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
            driver_locked=True,
        )
        panel: DriverControlsPanel = result["controls_panel"]
        assert str(panel.source_entry.cget("state")) == "disabled"
        assert str(panel.mode_combo.cget("state")) == "disabled"
        assert str(panel.auto_start_btn.cget("state")) == "disabled"

    def test_standalone_keeps_source_editable(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
            driver_locked=False,
        )
        panel: DriverControlsPanel = result["controls_panel"]
        assert str(panel.source_entry.cget("state")) == "normal"
        assert str(panel.mode_combo.cget("state")) == "readonly"

    def test_source_var_bound(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        src_var = tk.StringVar(value="/test/music")
        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=src_var,
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        panel: DriverControlsPanel = result["controls_panel"]
        root.update_idletasks()
        assert src_var.get() == "/test/music"
        assert panel.source_entry.cget("textvariable") == str(src_var)

    def test_output_path_row_present(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        out_var = tk.StringVar(value="/output")
        build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=out_var,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        assert out_var.get() == "/output"

    def test_mode_combo_displays_default_when_no_var_passed(self, root: tk.Tk) -> None:
        """Regression: the Mode combo must not render blank.

        A bare inline StringVar passed to the combobox is garbage-collected
        (its Tcl variable is destroyed), which leaves the box empty. The
        panel must keep the default mode var alive so "Dry Run" displays.
        """
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        panel: DriverControlsPanel = result["controls_panel"]
        gc.collect()
        root.update_idletasks()
        assert panel.mode_combo.get() == "Dry Run"

    def test_mode_combo_uses_passed_mode_var(self, root: tk.Tk) -> None:
        """The Mode combo binds the caller's var and reflects its value."""
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        mode_var = _mode_var(root, "Live Update")
        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
            mode_var=mode_var,
        )
        panel: DriverControlsPanel = result["controls_panel"]
        gc.collect()
        root.update_idletasks()
        assert panel.mode_combo.get() == "Live Update"
        assert panel.mode_combo.cget("textvariable") == str(mode_var)

    def test_mode_combo_tracks_mode_var_changes(self, root: tk.Tk) -> None:
        """Changing the bound var updates the displayed Mode value."""
        from audio_refinery.core.models import StageConfig
        from audio_refinery.ui.setup_tab import build

        mode_var = _mode_var(root, "Dry Run")
        config = StageConfig()
        result = build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
            mode_var=mode_var,
        )
        panel: DriverControlsPanel = result["controls_panel"]
        mode_var.set("Live Update")
        root.update_idletasks()
        assert panel.mode_combo.get() == "Live Update"


class TestEnhanceParamsFieldParity:
    """D12: the enhancer/refinery/params classes must not drift.

    ``_build_enhance_panel`` casts the refinery's ``EnhanceParams`` to the
    enhancer's ``EnhancementParams`` (``setup_tab.py``) before handing it to
    ``build_dsp_sliders``. A field present on one class but not another is a
    runtime ``AttributeError`` that mypy cannot see through the ``cast``, so
    this guard pins the three field sets in lockstep.
    """

    _EFFECT_FIELDS = frozenset(
        {"reverse", "karaoke", "karaoke_strength", "phaser", "flanger", "chorus"}
    )

    def test_dsp_models_and_enhancer_fields_identical(self) -> None:
        from audio_enhancer.core.models import EnhancementParams as EnhancerParams
        from audio_suite_shared.dsp_models import EnhancementParams as SharedParams

        assert set(SharedParams.__dataclass_fields__) == set(
            EnhancerParams.__dataclass_fields__
        )

    def test_refinery_is_superset_plus_preset(self) -> None:
        from audio_enhancer.core.models import EnhancementParams as EnhancerParams
        from audio_refinery.core.models import EnhanceParams

        refinery = set(EnhanceParams.__dataclass_fields__)
        enhancer = set(EnhancerParams.__dataclass_fields__)
        assert refinery - enhancer == {"preset"}
        assert enhancer - refinery == set()

    def test_effect_fields_present_on_all_three(self) -> None:
        from audio_enhancer.core.models import EnhancementParams as EnhancerParams
        from audio_refinery.core.models import EnhanceParams
        from audio_suite_shared.dsp_models import EnhancementParams as SharedParams

        for cls in (SharedParams, EnhancerParams, EnhanceParams):
            assert self._EFFECT_FIELDS <= set(cls.__dataclass_fields__), cls.__name__

    def test_effect_defaults_off_and_consistent(self) -> None:
        from audio_enhancer.core.models import EnhancementParams as EnhancerParams
        from audio_refinery.core.models import EnhanceParams
        from audio_suite_shared.dsp_models import EnhancementParams as SharedParams

        builders = (SharedParams, EnhancerParams, EnhanceParams)
        for field in self._EFFECT_FIELDS:
            values = {getattr(cls(), field) for cls in builders}
            assert len(values) == 1, f"{field} defaults differ across classes"
            only = next(iter(values))
            if field == "karaoke_strength":
                assert only == 1.0
            else:
                assert only is False


def _walk(widget: tk.Misc, kind: type) -> list[tk.Misc]:
    """Every descendant of *widget* that is an instance of *kind*."""
    found: list[tk.Misc] = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found.extend(_walk(child, kind))
    return found


class TestEnhancePanelSync:
    """The enhance stage's editor must write back to the run config.

    D24's regression (sliders writing to a discarded dict) now runs through the
    shared ``CustomDspPanel``: the panel reports every change — widget or
    preset — and the stage mirrors the full value set into
    ``config.enhance_params``, which is what the pipeline reads. Before that it
    synced one variable at a time from the inline sliders.
    """

    def _build(self, root: tk.Tk, config: object) -> dict:
        from audio_refinery.ui import setup_tab

        return setup_tab.build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )

    def _open_panel(self, state: dict) -> object:
        panel = state["dsp_panel"]
        panel.open()
        return panel

    def test_slider_edit_writes_back_to_config(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig()
        state = self._build(root, config)
        panel = self._open_panel(state)

        var = panel.variable("compressor_ratio")
        assert var is not None
        var.set(9.0)

        assert config.enhance_params.compressor_ratio == 9.0

    def test_effect_toggle_writes_back_to_config(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig()
        state = self._build(root, config)
        panel = self._open_panel(state)

        for field in ("reverse", "karaoke", "phaser", "flanger", "chorus"):
            var = panel.variable(field)
            assert var is not None
            var.set(True)
        strength = panel.variable("karaoke_strength")
        assert strength is not None
        strength.set(0.4)

        assert config.enhance_params.reverse is True
        assert config.enhance_params.karaoke_strength == 0.4
        assert config.enhance_params.chorus is True

    def test_preset_switch_does_not_reset_the_effects(self, root: tk.Tk) -> None:
        """D13: a named preset supplies the 13 base fields only."""
        from audio_refinery.core.models import StageConfig

        config = StageConfig()
        state = self._build(root, config)
        panel = self._open_panel(state)
        reverse = panel.variable("reverse")
        assert reverse is not None
        reverse.set(True)

        state["preset_var"].set("Mild")

        assert config.enhance_params.reverse is True
        assert config.enhance_params.preset == "Mild"

    def test_stage_body_holds_no_inline_controls(self, root: tk.Tk) -> None:
        """The 19 controls must live in the editor, not in the stage body."""
        from audio_refinery.core.models import StageConfig

        state = self._build(root, StageConfig())
        body = state["dsp_row"].master
        assert _walk(body, tk.Scale) == []
        assert _walk(body, tk.Checkbutton) == []
        assert state["dsp_panel"].variable("compressor_ratio") is None

    def test_custom_pick_opens_the_shared_editor(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig

        state = self._build(root, StageConfig())
        combo = state["enhance_preset_combo"]
        combo.set("Custom")
        combo.event_generate("<<ComboboxSelected>>")

        assert state["dsp_panel"].is_open()

    def test_custom_mode_adds_only_the_summary_row(self, root: tk.Tk) -> None:
        """Regression for the REFINE tab overflow: Custom must stay compact."""
        from audio_refinery.core.models import StageConfig

        state = self._build(root, StageConfig())
        body = state["dsp_row"].master
        root.update_idletasks()
        before = body.winfo_reqheight()

        state["preset_var"].set("Custom")
        root.update_idletasks()

        # The row appears (summary + button, well under 150 px); the old inline
        # panel added 745 px here and pushed the tab past the desktop height.
        assert state["dsp_row"].winfo_manager() == "pack"
        assert body.winfo_reqheight() - before < 150

    def test_output_gain_row_hidden_while_normaliser_is_enabled(
        self, root: tk.Tk
    ) -> None:
        """The Normaliser owns the final level, so the row is hidden."""
        from audio_refinery.core.models import StageConfig

        config = StageConfig()
        config.normalise = True
        state = self._build(root, config)
        panel = self._open_panel(state)
        dialog = panel.open()

        def output_gain_row() -> tk.Misc | None:
            for label in _walk(dialog, tk.Label):
                if str(label.cget("text")).startswith("Output Gain"):
                    return label.master
            return None

        row = output_gain_row()
        assert row is not None
        assert row.winfo_manager() == ""

        config.normalise = False
        state["normalise_toggle_cb"]()
        assert row.winfo_manager() == "pack"


class TestEqPanel:
    """The EQ table and curve are two views of the rack the run renders (F-S1)."""

    def _build(self, root: tk.Tk, config: Any) -> dict[str, Any]:
        from audio_refinery.ui import setup_tab

        return setup_tab.build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )

    def test_the_stage_and_its_refresh_are_registered(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig

        state = self._build(root, StageConfig())

        assert "eq" in state["stage_vars"]
        assert callable(state["eq_refresh"])
        assert state["eq_tree"].get_children() == ()

    def test_a_loaded_rack_reaches_the_table_and_the_measured_curve(
        self, root: tk.Tk
    ) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_suite_shared.dsp_eq import EqBand, EqSettings, response_curve

        config = StageConfig(
            eq=True,
            eq_params=EqSettings(bands=(EqBand("peaking", 1000.0, 6.0, 1.0),)),
        )

        state = self._build(root, config)
        state["eq_refresh"]()

        assert len(state["eq_tree"].get_children()) == 1
        freqs, curve = state["eq_curve"]
        expected = response_curve(config.eq_params, freqs)
        assert max(abs(a - b) for a, b in zip(curve, expected)) < 1e-9
        nearest = min(range(len(freqs)), key=lambda i: abs(freqs[i] - 1000.0))
        assert curve[nearest] == pytest.approx(6.0, abs=0.5)

    def test_adding_a_band_writes_the_run_config(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig
        from audio_suite_shared.dsp_eq import EqBand

        config = StageConfig(eq=True)
        state = self._build(root, config)
        entries = state["eq_entries"]
        entries["kind"].set("highshelf")
        entries["freq"].set("8000")
        entries["gain"].set("-3.5")
        entries["q"].set("0.8")

        state["eq_add"]()

        assert config.eq_params.bands == (EqBand("highshelf", 8000.0, -3.5, 0.8),)
        assert len(state["eq_tree"].get_children()) == 1

    def test_an_invalid_band_is_refused_without_touching_the_rack(
        self, root: tk.Tk
    ) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig(eq=True)
        state = self._build(root, config)
        state["eq_entries"]["freq"].set("90000")

        state["eq_add"]()

        assert config.eq_params.bands == ()
        assert state["eq_tree"].get_children() == ()


def _walk_labels(widget: Any) -> list[tk.Label]:
    """Return every Label under *widget*, depth first."""
    found: list[tk.Label] = []
    for child in widget.winfo_children():
        if isinstance(child, tk.Label):
            found.append(child)
        found.extend(_walk_labels(child))
    return found


class TestDynamicsPanel:
    """The eight controls write the settings object the stage renders (F-S2)."""

    def _build(self, root: tk.Tk, config: Any) -> dict[str, Any]:
        from audio_refinery.ui import setup_tab

        return setup_tab.build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )

    def test_the_stage_joins_select_all_with_all_eight_controls(
        self, root: tk.Tk
    ) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig()
        state = self._build(root, config)
        entries = state["dynamics_entries"]

        assert state["stage_vars"]["dynamics"] is not None
        assert set(entries) == {
            "threshold_db",
            "ratio",
            "attack_ms",
            "release_ms",
            "makeup_db",
            "ceiling_dbtp",
            "lookahead_ms",
            "limiter_release_ms",
        }
        assert (
            entries["threshold_db"].get()
            == f"{config.compressor_params.threshold_db:g}"
        )
        assert (
            entries["ceiling_dbtp"].get() == f"{config.limiter_params.ceiling_dbtp:g}"
        )

    def test_the_pipeline_line_names_the_stage_in_its_place(self, root: tk.Tk) -> None:
        """The window's own subtitle must name every stage it now shows."""
        from audio_refinery.core.models import StageConfig

        self._build(root, StageConfig())
        state_label = next(
            label
            for label in _walk_labels(root)
            if str(label.cget("text")).startswith("Single-pass pipeline")
        )
        line = str(state_label.cget("text"))

        assert line.index("EQ") < line.index("Dynamics") < line.index("Enhance")
        for stage in ("Declick", "Trim", "Noise Reduction", "Normalise"):
            assert stage in line

    def test_an_edit_writes_the_pair_the_pipeline_renders(self, root: tk.Tk) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig(dynamics=True)
        state = self._build(root, config)
        entries = state["dynamics_entries"]
        entries["threshold_db"].set("-24")
        entries["ratio"].set("6")
        entries["attack_ms"].set("5")
        entries["release_ms"].set("200")
        entries["makeup_db"].set("3")
        entries["ceiling_dbtp"].set("-2")
        entries["lookahead_ms"].set("10")
        entries["limiter_release_ms"].set("300")

        assert config.compressor_params.threshold_db == -24.0
        assert config.compressor_params.ratio == 6.0
        assert config.compressor_params.attack_ms == 5.0
        assert config.compressor_params.release_ms == 200.0
        assert config.compressor_params.makeup_db == 3.0
        assert config.limiter_params.ceiling_dbtp == -2.0
        assert config.limiter_params.lookahead_ms == 10.0
        assert config.limiter_params.release_ms == 300.0
        assert state["dynamics_status"].get() == ""

    def test_a_refused_value_is_reported_and_left_out_of_the_run(
        self, root: tk.Tk
    ) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig(dynamics=True)
        state = self._build(root, config)
        before = config.limiter_params

        state["dynamics_entries"]["ceiling_dbtp"].set("5")

        assert config.limiter_params == before
        assert "outside" in state["dynamics_status"].get()

    def test_a_non_number_is_refused_without_touching_the_pair(
        self, root: tk.Tk
    ) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig(dynamics=True)
        state = self._build(root, config)
        before = config.compressor_params

        state["dynamics_entries"]["ratio"].set("4x")

        assert config.compressor_params == before
        assert "number" in state["dynamics_status"].get()
