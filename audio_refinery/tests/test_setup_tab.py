"""Tests for audio_refinery.ui.setup_tab.
Changed in 1.1.0: added EnhancementParams field-parity tests and a
slider-to-config sync regression test (D24).
"""

from __future__ import annotations

import gc
import itertools
import tkinter as tk
from unittest.mock import MagicMock

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


class TestEnhancePanelSync:
    """D24 regression: the enhancer panel widgets must write back to config.

    Before this fix ``_build_enhance_panel`` called ``build_dsp_sliders`` and
    discarded the returned vars/param_values, so dragging a Custom-mode slider
    never reached ``config.enhance_params`` — the refine output ignored it.
    The effect toggles are new in Item 1.2 and must sync the same way.
    """

    def _build_with_spies(
        self, root: tk.Tk, monkeypatch: object, config: object
    ) -> dict:
        from audio_enhancer.ui import setup_tab as enh_ui
        from audio_refinery.ui import setup_tab

        captured: dict = {}
        real_sliders = enh_ui.build_dsp_sliders
        real_effects = enh_ui.build_effect_controls

        def spy_sliders(parent, params):  # type: ignore[no-untyped-def]
            vars_, pv = real_sliders(parent, params)
            captured["sliders"] = vars_
            captured["param_values"] = pv
            return vars_, pv

        def spy_effects(parent, params, param_values):  # type: ignore[no-untyped-def]
            vars_ = real_effects(parent, params, param_values)
            captured["effects"] = vars_
            return vars_

        monkeypatch.setattr(enh_ui, "build_dsp_sliders", spy_sliders)
        monkeypatch.setattr(enh_ui, "build_effect_controls", spy_effects)

        setup_tab.build(
            parent=tk.Frame(root),
            source_path=tk.StringVar(),
            output_path=None,
            config=config,
            on_browse_src=lambda: None,
            on_browse_out=lambda: None,
            on_start=lambda: None,
            on_reset=lambda: None,
        )
        return captured

    def test_dsp_slider_writes_back_to_config(
        self, root: tk.Tk, monkeypatch: object
    ) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig()
        captured = self._build_with_spies(root, monkeypatch, config)
        assert "compressor_ratio" in captured["sliders"]

        captured["sliders"]["compressor_ratio"].set(9.0)

        assert config.enhance_params.compressor_ratio == 9.0

    def test_effect_toggle_writes_back_to_config(
        self, root: tk.Tk, monkeypatch: object
    ) -> None:
        from audio_refinery.core.models import StageConfig

        config = StageConfig()
        captured = self._build_with_spies(root, monkeypatch, config)
        assert set(captured["effects"]) == {
            "reverse",
            "karaoke",
            "phaser",
            "flanger",
            "chorus",
            "karaoke_strength",
        }

        captured["effects"]["reverse"].set(True)
        captured["effects"]["karaoke_strength"].set(0.4)

        assert config.enhance_params.reverse is True
        assert config.enhance_params.karaoke_strength == 0.4
