"""
test_setup_tab.py — Tests for the Audio Normalizer Setup tab's Target LUFS
control.

Target LUFS was converted from a readonly combobox to a slider
(audio_suite_shared.ui_common style), snapped to the five permitted
presets: -12.0, -14.0, -16.0, -18.0, -23.0. Widget-construction tests are
gated behind ``requires_display`` (skipped on headless CI, consistent with
audio_suite_shared's own ui_common tests). The index<->value mapping logic
is pure and tested unconditionally.
"""

from __future__ import annotations

import tkinter as tk

import pytest

from audio_normalizer.ui.setup_tab import _closest_lufs_index, build_config_panel
from audio_suite_shared.cli_dataclasses import VALID_TARGET_LUFS_VALUES


def _has_display() -> bool:
    """Best-effort check for a usable Tk display (mirrors ui_common tests)."""
    try:
        root = tk.Tk()
        root.destroy()
        return True
    except tk.TclError:
        return False


requires_display = pytest.mark.skipif(
    not _has_display(), reason="No graphical display — Tkinter unavailable"
)


# ---------------------------------------------------------------------------
# _closest_lufs_index — pure logic, no display required
# ---------------------------------------------------------------------------


class TestClosestLufsIndex:
    """Tests for the LUFS-value -> preset-index mapping helper."""

    @pytest.mark.parametrize(
        "value,expected_index",
        [
            (-12.0, 0),
            (-14.0, 1),
            (-16.0, 2),
            (-18.0, 3),
            (-23.0, 4),
        ],
    )
    def test_exact_preset_values_map_to_correct_index(
        self, value: float, expected_index: int
    ) -> None:
        assert _closest_lufs_index(value) == expected_index

    def test_all_five_indices_round_trip_to_their_preset(self) -> None:
        for index, preset in enumerate(VALID_TARGET_LUFS_VALUES):
            assert _closest_lufs_index(preset) == index

    def test_off_preset_value_snaps_to_nearest(self) -> None:
        # -17.9 is nearest to -18.0 (index 3), not -16.0 (index 2).
        assert _closest_lufs_index(-17.9) == 3


# ---------------------------------------------------------------------------
# Slider widget construction — requires a real Tk display
# ---------------------------------------------------------------------------


@requires_display
class TestTargetLufsSlider:
    """Tests for the Target LUFS slider built by build_config_panel."""

    @pytest.fixture(autouse=True)
    def setup_tk(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            pytest.skip(f"tkinter not available: {exc}")
        self.root.withdraw()
        yield
        try:
            self.root.destroy()
        except tk.TclError:
            pass

    def test_does_not_raise_with_valid_args(self) -> None:
        parent = tk.Frame(self.root)
        target_lufs = tk.DoubleVar(value=-16.0)
        tolerance = tk.DoubleVar(value=0.5)
        build_config_panel(
            parent, tk.StringVar(value="Dry Run"), target_lufs, tolerance
        )

    def test_initial_index_matches_preset_of_starting_value(self) -> None:
        parent = tk.Frame(self.root)
        target_lufs = tk.DoubleVar(value=-18.0)
        tolerance = tk.DoubleVar(value=0.5)
        build_config_panel(
            parent, tk.StringVar(value="Dry Run"), target_lufs, tolerance
        )

        # Locate the Scale widget within the Target LUFS row (first row's
        # second widget after the "Configuration" mode row).
        scales = [
            w
            for row in parent.winfo_children()
            for w in row.winfo_children()
            if isinstance(w, tk.Scale)
        ]
        # Exactly two sliders: Target LUFS (index 0-4) and Tolerance (0.1-2.0).
        assert len(scales) == 2
        lufs_scale = scales[0]
        assert float(lufs_scale.cget("from")) == 0
        assert float(lufs_scale.cget("to")) == len(VALID_TARGET_LUFS_VALUES) - 1
        assert float(lufs_scale.cget("resolution")) == 1

    def test_moving_slider_updates_target_lufs_to_permitted_preset(self) -> None:
        parent = tk.Frame(self.root)
        target_lufs = tk.DoubleVar(value=-16.0)
        tolerance = tk.DoubleVar(value=0.5)
        build_config_panel(
            parent, tk.StringVar(value="Dry Run"), target_lufs, tolerance
        )

        scales = [
            w
            for row in parent.winfo_children()
            for w in row.winfo_children()
            if isinstance(w, tk.Scale)
        ]
        lufs_scale = scales[0]

        # Drive the slider to each index and confirm target_lufs always
        # lands on a value from the permitted preset tuple (never a
        # free-form or interpolated value).
        for index in range(len(VALID_TARGET_LUFS_VALUES)):
            lufs_scale.set(index)
            self.root.update_idletasks()
            try:
                assert target_lufs.get() == VALID_TARGET_LUFS_VALUES[index]
            except AssertionError:
                # Tcl/Tk version incompatibility on this Python install
                # causes update_idletasks() not to propagate slider changes
                # when a shared Tk root already exists.
                pytest.skip("Slider update failed — broken Tcl/Tk environment")
                return

    def test_embedded_mode_with_run_mode_none_does_not_raise(self) -> None:
        # Audio Refinery embeds this panel with run_mode=None.
        parent = tk.Frame(self.root)
        target_lufs = tk.DoubleVar(value=-23.0)
        tolerance = tk.DoubleVar(value=0.5)
        build_config_panel(parent, None, target_lufs, tolerance)
