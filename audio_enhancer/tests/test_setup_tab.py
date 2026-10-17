"""Tests for audio_enhancer.ui.setup_tab — Setup tab and the Custom DSP editor.

Two contracts are locked here.

*One preset control.* The tab used to show two near-identical comboboxes two
rows apart — "Presets:" (saved suite presets) and "Enhancement Preset:"
(built-in DSP presets) — which did different things. There must now be exactly
one, listing the built-in presets first and the saved ones behind a
display-only divider, with a caption stating what the selection does.

*A compact tab with an editor.* The nineteen Custom controls used to sit on the
Setup tab, where they needed 745 px and pushed the tab to 1274 px against
887 px available at the shipped 880x980 window — clipping the lower controls
*and* the BEGIN ENHANCEMENT button (it was not mapped at all). The controls now
live in a single non-modal editor window and the tab keeps a summary row.

Uses the session-scoped real Tk root from conftest.py: the tab is built from
genuine widgets, because a mocked root cannot report mapping or geometry.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Any, NamedTuple
from unittest.mock import MagicMock, patch

import pytest

from audio_enhancer.ui import setup_tab
from audio_suite_shared.dsp_models import PRESETS, EnhancementParams, PresetName


class Built(NamedTuple):
    """One built Setup tab plus the handles the tests drive it with."""

    container: tk.Frame
    variables: dict[str, tk.Variable]
    start_btn: tk.Button
    values: dict[str, Any]
    panel: setup_tab.CustomDspPanel
    preset_combo: ttk.Combobox
    refresh_presets: Any
    on_preset_selected: MagicMock
    on_save_preset: MagicMock
    on_delete_preset: MagicMock


def _build(
    root: tk.Tk,
    *,
    preset: str = "Moderate",
    saved: tuple[str, ...] = (),
    container: tk.Frame | None = None,
) -> Built:
    """Build a real Setup tab, optionally inside a caller-supplied container."""
    frame = container if container is not None else tk.Frame(root)
    frame.pack(fill="both", expand=True)
    variables: dict[str, tk.Variable] = {
        "source": tk.StringVar(master=root),
        "output": tk.StringVar(master=root),
        "preset": tk.StringVar(master=root, value=preset),
        "run_mode": tk.StringVar(master=root, value="Live Update"),
        "auto_start": tk.BooleanVar(master=root, value=False),
        "auto_end": tk.BooleanVar(master=root, value=False),
        "clear_logs": tk.BooleanVar(master=root, value=False),
        "parallel": tk.BooleanVar(master=root, value=False),
    }
    on_preset_selected = MagicMock()
    on_save_preset = MagicMock()
    on_delete_preset = MagicMock()
    start_btn, refresh, values, panel = setup_tab.build(
        frame,
        source_path=variables["source"],
        output_path=variables["output"],
        preset_name=variables["preset"],
        params=EnhancementParams(),
        on_browse_src=MagicMock(),
        on_browse_out=MagicMock(),
        on_start=MagicMock(),
        run_mode=variables["run_mode"],
        auto_start_var=variables["auto_start"],
        auto_end_var=variables["auto_end"],
        clear_logs_var=variables["clear_logs"],
        parallel_var=variables["parallel"],
        preset_names=list(saved),
        on_save_preset=on_save_preset,
        on_delete_preset=on_delete_preset,
        on_preset_selected=on_preset_selected,
    )
    # The Run Controls panel has its own Mode combobox; the preset selector is
    # the one inside the Configuration group.
    combos = _find_all(_config_group(frame), ttk.Combobox)
    assert len(combos) == 1, "the Configuration group must show one preset selector"
    return Built(
        frame,
        variables,
        start_btn,
        values,
        panel,
        combos[0],
        refresh,
        on_preset_selected,
        on_save_preset,
        on_delete_preset,
    )


def _find_all(widget: tk.Misc, kind: type) -> list[tk.Misc]:
    found: list[tk.Misc] = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found.extend(_find_all(child, kind))
    return found


def _button(container: tk.Misc, text: str) -> tk.Button:
    for button in _find_all(container, tk.Button):
        if isinstance(button, tk.Button) and str(button.cget("text")) == text:
            return button
    raise AssertionError(f"button {text!r} not rendered")


def _config_group(container: tk.Frame) -> tk.LabelFrame:
    """Return the Setup tab's Configuration group."""
    for frame in _find_all(container, tk.LabelFrame):
        if isinstance(frame, tk.LabelFrame) and "Configuration" in str(
            frame.cget("text")
        ):
            return frame
    raise AssertionError("Configuration group not rendered")


def _select_preset(built: Built, value: str) -> None:
    """Simulate the user picking *value* in the single preset selector."""
    built.preset_combo.set(value)
    built.preset_combo.event_generate("<<ComboboxSelected>>")
    built.container.update_idletasks()


def _hint_text(built: Built) -> str:
    """The live caption under the preset selector."""
    for label in _find_all(built.container, tk.Label):
        text = str(label.cget("text"))
        if text.startswith(("Built-in preset", "Saved preset")):
            return text
    return ""


def _close(built: Built) -> None:
    built.panel.close()
    built.container.destroy()


class TestSinglePresetControl:
    """One selector lists both kinds and says which one is active."""

    def test_there_is_exactly_one_preset_combobox(self, root: tk.Tk) -> None:
        built = _build(root, saved=("My Chain",))
        try:
            group_combos = _find_all(_config_group(built.container), ttk.Combobox)
            assert len(group_combos) == 1
            # The only other combobox on the tab is the shared Mode selector.
            others = [
                combo
                for combo in _find_all(built.container, ttk.Combobox)
                if combo not in group_combos
            ]
            assert len(others) == 1
            # It is the Run Controls Mode selector, not another preset picker.
            assert "Mild" not in list(others[0]["values"])
        finally:
            _close(built)

    def test_built_in_presets_come_first_then_saved(self, root: tk.Tk) -> None:
        built = _build(root, saved=("Loud", "Vocal Chain"))
        try:
            values = list(built.preset_combo["values"])
            assert values[: len(PresetName)] == [p.value for p in PresetName]
            assert values[-2:] == ["Loud", "Vocal Chain"]
            assert setup_tab._SAVED_DIVIDER in values
        finally:
            _close(built)

    def test_no_divider_without_saved_presets(self, root: tk.Tk) -> None:
        built = _build(root)
        try:
            values = list(built.preset_combo["values"])
            assert values == [p.value for p in PresetName]
        finally:
            _close(built)

    def test_built_in_pick_applies_values_and_explains_itself(
        self, root: tk.Tk
    ) -> None:
        built = _build(root)
        try:
            _select_preset(built, "Mild")
            mild = PRESETS[PresetName.MILD]
            assert built.values["compressor_ratio"] == mild.compressor_ratio
            assert built.on_preset_selected.call_count == 0
            assert _hint_text(built).startswith("Built-in preset")
        finally:
            _close(built)

    def test_saved_pick_loads_settings_and_names_its_built_in(
        self, root: tk.Tk
    ) -> None:
        built = _build(root, saved=("My Chain",))
        try:
            # The app applies the stored settings, then the user's pick is
            # resolved: the selector keeps the saved name, the caption reports
            # the built-in preset it carries.
            built.variables["preset"].set("Custom")
            _select_preset(built, "My Chain")

            built.on_preset_selected.assert_called_once_with("My Chain")
            hint = _hint_text(built)
            assert hint.startswith("Saved preset")
            assert "Custom" in hint
        finally:
            _close(built)

    def test_divider_is_not_selectable(self, root: tk.Tk) -> None:
        built = _build(root, saved=("My Chain",))
        try:
            _select_preset(built, "Moderate")
            _select_preset(built, setup_tab._SAVED_DIVIDER)

            assert built.preset_combo.get() == "Moderate"
            built.on_preset_selected.assert_not_called()
        finally:
            _close(built)

    def test_delete_applies_to_saved_presets_only(self, root: tk.Tk) -> None:
        built = _build(root, saved=("My Chain",))
        try:
            delete = _button(built.container, "Delete")
            _select_preset(built, "Moderate")
            assert str(delete.cget("state")) == "disabled"

            _select_preset(built, "My Chain")
            assert str(delete.cget("state")) == "normal"
        finally:
            _close(built)

    def test_save_button_opens_the_shared_name_dialog(self, root: tk.Tk) -> None:
        built = _build(root)
        try:
            with patch.object(setup_tab.ui_common, "save_preset_dialog") as dialog:
                _button(built.container, "Save").invoke()
            dialog.assert_called_once()
            combo, on_save = dialog.call_args.args
            assert combo is built.preset_combo
            assert callable(on_save)
        finally:
            _close(built)

    def test_deleting_the_selected_preset_falls_back_to_the_built_in(
        self, root: tk.Tk
    ) -> None:
        built = _build(root, saved=("My Chain",))
        try:
            built.variables["preset"].set("Aggressive")
            _select_preset(built, "My Chain")
            # The app removes it from storage and pushes the new list back.
            built.refresh_presets([])

            assert built.preset_combo.get() == "Aggressive"
            assert _hint_text(built).startswith("Built-in preset")
        finally:
            _close(built)

    def test_programmatic_preset_still_shows_in_the_selector(self, root: tk.Tk) -> None:
        """A CLI/restored preset must move the selector (pre-fill rule)."""
        built = _build(root)
        try:
            built.variables["preset"].set("Aggressive")
            assert built.preset_combo.get() == "Aggressive"
            assert "Built-in preset" in _hint_text(built)
        finally:
            _close(built)

    def test_custom_pick_opens_the_editor(self, root: tk.Tk) -> None:
        built = _build(root)
        try:
            _select_preset(built, "Custom")
            assert built.panel.is_open()
            assert "Custom DSP window" in _hint_text(built)
        finally:
            _close(built)

    def test_saving_a_built_in_name_is_refused(self, root: tk.Tk) -> None:
        """A saved "Mild" could never be picked: the built-in owns that entry."""
        built = _build(root)
        try:
            with patch.object(
                setup_tab.ui_common,
                "save_preset_dialog",
                side_effect=lambda _combo, on_save: on_save("Mild"),
            ):
                with patch.object(setup_tab.messagebox, "showwarning") as warn:
                    _button(built.container, "Save").invoke()

            warn.assert_called_once()
            built.on_save_preset.assert_not_called()
            assert built.preset_combo.get() == "Moderate"
        finally:
            _close(built)

    def test_legacy_saved_preset_named_like_a_built_in_is_not_offered(
        self, root: tk.Tk
    ) -> None:
        """Older saved "Moderate" entries must not shadow the built-in row."""
        built = _build(root, saved=("Moderate", "My Chain"))
        try:
            values = list(built.preset_combo["values"])
            assert values.count("Moderate") == 1
            assert "My Chain" in values
            assert "Custom" in values
        finally:
            _close(built)


class TestBeginButtonVisibility:
    """The primary action must survive any preset state and window size."""

    def test_begin_button_is_visible_in_custom_mode_at_small_window(
        self, root: tk.Tk
    ) -> None:
        """Regression: in Custom mode the button used to be packed off-screen.

        At the shipped 880x980 size it measured height 1 and
        ``winfo_ismapped() == 0``; the test uses a deliberately harsher
        880x600 window so it cannot pass by accident on a tall display.
        """
        window = tk.Toplevel(root)
        window.geometry("880x600+0+0")
        built = _build(root, preset="Custom", container=tk.Frame(window))
        try:
            window.update()
            assert built.start_btn.winfo_ismapped() == 1
            assert built.start_btn.winfo_height() > 1
            bottom = built.start_btn.winfo_rooty() + built.start_btn.winfo_height()
            assert bottom <= window.winfo_rooty() + window.winfo_height()
        finally:
            built.panel.close()
            window.destroy()

    def test_setup_tab_stays_compact_in_custom_mode(self, root: tk.Tk) -> None:
        """The tab must fit the default window with the editor out of the way."""
        built = _build(root, preset="Custom")
        try:
            root.update_idletasks()
            setup_frame = built.container.winfo_children()[0]
            # 1274 px before the controls moved out; 523 px for a named preset.
            assert setup_frame.winfo_reqheight() <= 700
        finally:
            _close(built)

    def test_custom_mode_embeds_no_dsp_controls_on_the_tab(self, root: tk.Tk) -> None:
        """Guard: the controls must live in the editor, not creep back in."""
        built = _build(root, preset="Custom")
        try:
            # No sliders anywhere on the tab, and no effect toggles left in the
            # Configuration group (the run-controls panel has its own toggles).
            assert _find_all(built.container, tk.Scale) == []
            assert _find_all(_config_group(built.container), tk.Checkbutton) == []
        finally:
            _close(built)


class TestCustomRow:
    """The summary row appears only while Custom is selected."""

    def test_row_follows_the_preset_selector(self, root: tk.Tk) -> None:
        built = _build(root)
        try:
            row = _button(built.container, "Configure Custom DSP\u2026").master
            assert row.winfo_manager() == ""

            _select_preset(built, "Custom")
            assert row.winfo_manager() == "pack"

            _select_preset(built, "Moderate")
            assert row.winfo_manager() == ""
        finally:
            _close(built)

    def test_row_is_shown_when_custom_is_the_initial_preset(self, root: tk.Tk) -> None:
        """A restored/CLI 'Custom' preset must show the row, not hide it."""
        built = _build(root, preset="Custom")
        try:
            button = _button(built.container, "Configure Custom DSP\u2026")
            assert button.master.winfo_manager() == "pack"
            # …and it must not pop a window on its own.
            assert not built.panel.is_open()
        finally:
            _close(built)


class TestCustomDspDialog:
    """The editor window: one instance, all controls, live shared values."""

    def test_configure_button_opens_one_reusable_window(self, root: tk.Tk) -> None:
        built = _build(root)
        try:
            _select_preset(built, "Custom")
            first = built.panel.open()
            assert built.panel.is_open()
            assert built.panel.open() is first
            assert first.winfo_exists()
        finally:
            _close(built)

    def test_dialog_is_non_modal(self, root: tk.Tk) -> None:
        built = _build(root)
        try:
            dialog = built.panel.open()
            assert dialog.grab_current() is None
        finally:
            _close(built)

    def test_dialog_holds_every_dsp_control(self, root: tk.Tk) -> None:
        built = _build(root)
        try:
            dialog = built.panel.open()
            scales = _find_all(dialog, tk.Scale)
            checks = _find_all(dialog, tk.Checkbutton)
            # 13 numeric sliders + Karaoke Strength; 5 effect toggles.
            assert len(scales) == len(setup_tab.NUMERIC_DSP_FIELDS) + 1
            assert len(checks) == 5
        finally:
            _close(built)

    def test_edits_reach_the_shared_values_dict(self, root: tk.Tk) -> None:
        built = _build(root)
        try:
            built.panel.open()
            ratio = built.panel.variable("compressor_ratio")
            assert ratio is not None
            ratio.set(9.0)
            karaoke = built.panel.variable("karaoke")
            assert karaoke is not None
            karaoke.set(True)

            assert built.values["compressor_ratio"] == pytest.approx(9.0)
            assert built.values["karaoke"] is True
            # The worker's construction path must accept this dict as-is.
            rebuilt = EnhancementParams(**built.values)
            assert rebuilt.compressor_ratio == pytest.approx(9.0)
            assert rebuilt.karaoke is True
        finally:
            _close(built)

    def test_values_are_seeded_before_the_editor_opens(self, root: tk.Tk) -> None:
        """A run started without opening the editor still has every field."""
        built = _build(root, preset="Custom")
        try:
            assert set(built.values) == set(EnhancementParams.__dataclass_fields__)
            assert not built.panel.is_open()
        finally:
            _close(built)

    def test_switching_to_a_named_preset_closes_editor_and_applies_values(
        self, root: tk.Tk
    ) -> None:
        built = _build(root, preset="Custom")
        try:
            _select_preset(built, "Custom")
            assert built.panel.is_open()

            _select_preset(built, "Mild")
            assert not built.panel.is_open()
            mild = PRESETS[PresetName.MILD]
            assert built.values["compressor_ratio"] == mild.compressor_ratio
            assert built.values["high_shelf_gain_db"] == mild.high_shelf_gain_db
        finally:
            _close(built)

    def test_switching_preset_keeps_effect_toggles(self, root: tk.Tk) -> None:
        """D13: a built-in preset supplies the 13 numeric fields only."""
        built = _build(root, preset="Custom")
        try:
            built.panel.open()
            reverse = built.panel.variable("reverse")
            assert reverse is not None
            reverse.set(True)

            _select_preset(built, "Mild")

            assert built.values["reverse"] is True
            mild = PRESETS[PresetName.MILD]
            assert built.values["compressor_ratio"] == mild.compressor_ratio
        finally:
            _close(built)

    def test_apply_values_moves_live_controls(self, root: tk.Tk) -> None:
        """Loading a saved preset must move the visible controls, not just values."""
        built = _build(root, preset="Custom")
        try:
            built.panel.open()
            built.panel.apply_values(
                {"compressor_ratio": 7.5, "output_path": "ignored"}
            )
            var = built.panel.variable("compressor_ratio")
            assert var is not None
            assert var.get() == pytest.approx(7.5)
            assert "output_path" not in built.values
        finally:
            _close(built)

    def test_reopening_keeps_edits(self, root: tk.Tk) -> None:
        built = _build(root, preset="Custom")
        try:
            built.panel.open()
            ratio = built.panel.variable("compressor_ratio")
            assert ratio is not None
            ratio.set(6.5)
            built.panel.close()

            built.panel.open()
            reopened = built.panel.variable("compressor_ratio")
            assert reopened is not None
            assert reopened.get() == pytest.approx(6.5)
        finally:
            _close(built)
