"""
Tests for music_format_converter.ui.setup_tab — Setup tab construction.

Uses the session-scoped real Tk root from conftest.py so the shared
DriverControlsPanel builds genuine widgets.

Changed in 2.1.2: added the ALAC description tests (R-02), which read the
label text through both the combobox handler and the update_format_menu
pre-fill route on real widgets.
"""

import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from music_format_converter.core.formats import ALL_FORMATS
from music_format_converter.ui import setup_tab


def _make_vars(root: tk.Tk) -> dict[str, tk.Variable]:
    return {
        "folder_path": tk.StringVar(master=root),
        "output_folder": tk.StringVar(master=root),
        "output_format": tk.StringVar(master=root, value="mp3"),
        "quality_preset": tk.StringVar(master=root, value="highest"),
        "sample_rate": tk.StringVar(master=root, value="source"),
        "bit_depth": tk.StringVar(master=root, value="auto"),
        "delete_originals": tk.BooleanVar(master=root, value=False),
        "normalize_mp3": tk.BooleanVar(master=root, value=False),
        "target_lufs": tk.DoubleVar(master=root, value=-16.0),
        "dither": tk.BooleanVar(master=root, value=True),
        "run_mode": tk.StringVar(master=root, value="Dry Run"),
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
        "output_folder": vars_["output_folder"],
        "output_format": vars_["output_format"],
        "quality_preset": vars_["quality_preset"],
        "sample_rate": vars_["sample_rate"],
        "bit_depth": vars_["bit_depth"],
        "delete_originals": vars_["delete_originals"],
        "normalize_mp3": vars_["normalize_mp3"],
        "target_lufs": vars_["target_lufs"],
        "dither": vars_["dither"],
        "run_mode": vars_["run_mode"],
        "auto_start_var": vars_["auto_start"],
        "auto_end_var": vars_["auto_end"],
        "clear_logs_var": vars_["clear_logs"],
        "parallel_var": vars_["parallel"],
        "ffmpeg_available": True,
        "all_formats": list(ALL_FORMATS),
        "on_browse_input": MagicMock(),
        "on_browse_output": MagicMock(),
        "on_start": MagicMock(),
        "driver_locked": False,
        "on_folder_change": MagicMock(),
        "preset_names": ["Preset A"],
        "on_save_preset": MagicMock(),
        "on_delete_preset": MagicMock(),
        "on_preset_selected": MagicMock(),
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


@pytest.fixture
def tab_vars(root: tk.Tk):
    return _make_vars(root)


class TestWiredWidgets:
    """build() returns every callable/widget the app needs."""

    def test_returns_expected_keys(self, root: tk.Tk) -> None:
        _, widgets, _ = _build(root)
        assert isinstance(widgets["start_btn"], tk.Button)
        assert isinstance(widgets["preset_combo"], ttk.Combobox)
        assert callable(widgets["update_detected_label"])
        assert callable(widgets["update_format_menu"])
        assert callable(widgets["update_format_info"])
        assert callable(widgets["refresh_preset_list"])
        assert isinstance(widgets["controls_panel"], DriverControlsPanel)

    def test_start_button_invokes_on_start(self, root: tk.Tk) -> None:
        kwargs, widgets, _ = _build(root)
        widgets["start_btn"].invoke()
        kwargs["on_start"].assert_called_once()

    def test_folder_change_bound_to_panel_entry(self, root: tk.Tk) -> None:
        """Legacy FocusOut/Return triggers must survive on the panel entry.

        Regression guard: when the input-folder row moved into the shared
        DriverControlsPanel, these two bindings had to be re-created on the
        panel's source entry or _on_folder_change would silently stop firing.
        Synthetic key-event dispatch is unreliable headless (a withdrawn root
        never receives real OS focus), so only binding presence is asserted.
        """
        _, widgets, _ = _build(root)
        entry = widgets["controls_panel"].source_entry
        assert entry.bind("<Return>")
        assert entry.bind("<FocusOut>")

    def test_tool_controls_present(self, root: tk.Tk) -> None:
        _, _, container = _build(root)
        texts = _descendant_texts(container)
        assert "Output Directory (leave empty for same as input):" in texts
        assert "Output Format:" in texts
        assert "Quality Preset:" in texts
        assert "Sample Rate:" in texts
        assert "Bit Depth:" in texts
        assert "Post-Conversion Options:" in texts


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
    """Input folder row and Run Mode block are replaced by the shared panel."""

    def test_panel_source_label_present_once_and_legacy_rows_gone(
        self, root: tk.Tk
    ) -> None:
        _, _, container = _build(root)
        texts = _descendant_texts(container)
        assert texts.count("Source Music Directory:") == 1
        assert "Input Music Directory:" not in texts
        assert "Run Mode:" not in texts


class TestLosslessGainControl:
    """MP3 normalization controls must be present and bound."""

    def test_checkbox_present(self, root: tk.Tk) -> None:
        _, _, container = _build(root)
        texts = _descendant_texts(container)
        assert "Normalize MP3 output to target loudness" in " ".join(texts)

    def test_checkbox_bound_to_var(self, root: tk.Tk) -> None:
        kwargs, _, container = _build(root)
        boxes = [
            w
            for w in _all_checkbuttons(container)
            if str(w.cget("variable")) == str(kwargs["normalize_mp3"])
        ]
        assert boxes

    def test_target_lufs_entry_bound(self, root: tk.Tk) -> None:
        kwargs, _, container = _build(root)
        entries = [
            w
            for w in _all_entries(container)
            if str(w.cget("textvariable")) == str(kwargs["target_lufs"])
        ]
        assert entries

    def test_default_target_is_minus_sixteen(self, root: tk.Tk) -> None:
        kwargs, _, _ = _build(root)
        assert kwargs["target_lufs"].get() == -16.0


def _all_checkbuttons(container: tk.Widget) -> list[tk.Checkbutton]:
    result = []
    for child in container.winfo_children():
        if isinstance(child, tk.Checkbutton):
            result.append(child)
        result.extend(_all_checkbuttons(child))
    return result


def _all_entries(container: tk.Widget) -> list[tk.Entry]:
    result = []
    for child in container.winfo_children():
        if isinstance(child, tk.Entry):
            result.append(child)
        result.extend(_all_entries(child))
    return result


def _find_comboboxes(container: tk.Widget) -> list[ttk.Combobox]:
    boxes = []
    for child in container.winfo_children():
        if isinstance(child, ttk.Combobox):
            boxes.append(child)
        boxes.extend(_find_comboboxes(child))
    return boxes


class TestSampleRateControl:
    def test_sample_rate_var_bound_and_values(self, root: tk.Tk) -> None:
        kwargs, _, container = _build(root)
        boxes = _find_comboboxes(container)
        labels = [str(b.cget("textvariable")) for b in boxes]
        assert str(kwargs["sample_rate"]) in labels
        sr_box = next(
            b
            for b in boxes
            if str(b.cget("textvariable")) == str(kwargs["sample_rate"])
        )
        values = list(sr_box.cget("values"))
        assert "source" in values
        assert "44100" in values
        assert "48000" in values
        assert "88200" in values
        assert "96000" in values
        assert "176400" in values
        assert "192000" in values

    def test_sample_rate_ui_preset_order(self, root: tk.Tk) -> None:
        """Presets must list source first (the default passthrough)."""
        kwargs, _, container = _build(root)
        sr_box = _find_sr_box(container, kwargs)
        assert sr_box.cget("values")[0] == "source"


def _find_sr_box(container: tk.Widget, kwargs: dict, var_key: str = "sample_rate"):
    target = str(kwargs[var_key])
    for b in _find_comboboxes(container):
        if str(b.cget("textvariable")) == target:
            return b
    raise AssertionError(f"No combobox bound to {var_key}")


class TestBitDepthControl:
    def test_bit_depth_var_bound_and_values(self, root: tk.Tk) -> None:
        kwargs, _, container = _build(root)
        bd_box = _find_sr_box(container, kwargs, "bit_depth")
        values = list(bd_box.cget("values"))
        assert "auto" in values
        assert "16" in values
        assert "24" in values
        assert "32" in values
        assert "float" in values

    def test_bit_depth_disabled_for_non_wav(self, root: tk.Tk) -> None:
        """mp3 selected by default → bit depth control is inert."""
        kwargs, _, container = _build(root)
        bd_box = _find_sr_box(container, kwargs, "bit_depth")
        assert str(bd_box.cget("state")) == "disabled"

    def test_bit_depth_enabled_for_wav_output(self, root: tk.Tk) -> None:
        """Selecting WAV via the app's scan seam re-enables the control."""
        kwargs, widgets, container = _build(root)
        widgets["update_format_menu"](["flac", "wav"], "wav")
        bd_box = _find_sr_box(container, kwargs, "bit_depth")
        assert str(bd_box.cget("state")) == "readonly"

    def test_bit_depth_resets_to_auto_on_format_switch(self, root: tk.Tk) -> None:
        """Selecting a non-WAV format clears a stale explicit depth."""
        kwargs, widgets, container = _build(root)
        widgets["update_format_menu"](["flac", "wav"], "wav")
        widgets["update_format_info"]("wav")
        kwargs["bit_depth"].set("24")
        widgets["update_format_menu"](["mp3", "ogg"], "mp3")
        assert kwargs["bit_depth"].get() == "auto"


class TestDitherControl:
    """The TPDF dither opt-out checkbox (plan E1, decision D1 option A)."""

    @staticmethod
    def _find_dither_box(container: tk.Widget) -> tk.Checkbutton:
        boxes = [
            b
            for b in _all_checkbuttons(container)
            if "dither" in str(b.cget("text")).lower()
        ]
        assert len(boxes) == 1, f"expected one dither checkbox, got {len(boxes)}"
        return boxes[0]

    def test_checkbox_present(self, root: tk.Tk) -> None:
        _, _, container = _build(root)
        assert self._find_dither_box(container) is not None

    def test_defaults_to_on(self, root: tk.Tk) -> None:
        """Dither is the always-on default; the checkbox is only an opt-out."""
        kwargs, _, _ = _build(root)
        assert kwargs["dither"].get() is True

    def test_bound_to_the_supplied_var(self, root: tk.Tk) -> None:
        """The widget must write through to the app's own BooleanVar."""
        kwargs, _, container = _build(root)
        box = self._find_dither_box(container)
        box.invoke()
        assert kwargs["dither"].get() is False
        box.invoke()
        assert kwargs["dither"].get() is True

    def test_checkbox_is_enabled_for_every_output_format(self, root: tk.Tk) -> None:
        """Unlike bit depth, this is not gated on format: the depth reduction
        that AIFF performs internally needs it just as much as WAV does."""
        _, widgets, container = _build(root)
        widgets["update_format_menu"](["flac", "wav"], "wav")
        assert str(self._find_dither_box(container).cget("state")) != "disabled"


class TestAlacFormatDescription:
    """A2 (R-02) — the ALAC description reaches the widget the user reads.

    The label text comes from `format_info` through two routes: the
    `<<ComboboxSelected>>` handler, and `update_format_menu`, which the app
    calls when it narrows the menu from scanned input (a programmatic pre-fill
    that never fires the widget event).  Both are exercised here on real
    widgets, because a description that only exists in `format_info` is not a
    description the user ever sees.
    """

    def test_alac_description_names_the_m4a_container(self, root: tk.Tk) -> None:
        _, widgets, container = _build(root)

        widgets["update_format_info"]("alac")

        texts = _descendant_texts(container)
        assert any(".m4a" in text and "container" in text.lower() for text in texts), (
            texts
        )

    def test_prefill_route_updates_the_description(self, root: tk.Tk) -> None:
        """`update_format_menu` is the pre-fill route; it must update the label."""
        _, widgets, container = _build(root)

        widgets["update_format_menu"](list(ALL_FORMATS), "alac")

        texts = _descendant_texts(container)
        assert any("ALAC" in text and ".m4a" in text for text in texts), texts
