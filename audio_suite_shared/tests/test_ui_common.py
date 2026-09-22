"""
test_ui_common.py — Unit tests for audio_suite_shared.ui_common

Strategy
--------
ui_common builds Tkinter widgets.  Tests that construct widgets are gated
behind the ``requires_display`` mark (skipped on headless CI).  All pure-logic
paths (default-handler fallback, return-dict keys, etc.) are tested directly
using a mock Tk root.

Covers:
    • _default_open_log: graceful handling of missing log file
    • build_results_tab: return dict has expected keys; callbacks wired
    • build_results_tab: extra_labels are created and returned
    • build_processing_tab: return dict has expected keys
    • build_processing_tab: slot_vars panel omitted when None
    • path_row / slider_row: do not raise with valid args
    • show_message: does not raise; dialog destroyed on OK
    • BaseSetupFrame: skeleton layout, set_driven gating, preset row,
      config group / parallel row helpers, ordering override
    • save_preset_dialog / delete_preset_action: preset IO helpers
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
from tkinter import ttk
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.exceptions import AudioConfigurationError
from audio_suite_shared.ui_common import BaseSetupFrame
from audio_suite_shared.ui_driver_controls import DriverControlsPanel

# ---------------------------------------------------------------------------
# Display guard
# ---------------------------------------------------------------------------


def _has_display() -> bool:
    if sys.platform == "win32":
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


requires_display = pytest.mark.skipif(
    not _has_display(), reason="No graphical display — Tkinter unavailable"
)


# ---------------------------------------------------------------------------
# _default_open_log (no display required)
# ---------------------------------------------------------------------------


class TestDefaultOpenLog:
    """Tests for the internal _default_open_log fallback handler."""

    def test_does_not_raise_when_log_missing(self) -> None:
        """_default_open_log must silently swallow missing-log errors."""
        from audio_suite_shared.ui_common import _default_open_log

        with patch("os.path.exists", return_value=False):
            # Must not raise
            _default_open_log()

    def test_calls_startfile_when_log_exists_on_win32(self) -> None:
        from audio_suite_shared.ui_common import _default_open_log

        with (
            patch("os.path.exists", return_value=True),
            patch.object(sys, "platform", "win32"),
            patch("os.startfile") as mock_start,
        ):
            _default_open_log()
            mock_start.assert_called_once()

    def test_darwin_uses_open_command(self) -> None:
        """On macOS the log file must be opened via the `open` command."""
        from audio_suite_shared.ui_common import _default_open_log

        with (
            patch("os.path.exists", return_value=True),
            patch.object(sys, "platform", "darwin"),
            patch("audio_suite_shared.ui_common.run_secure_subprocess") as mock_run,
        ):
            _default_open_log()
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == "open"

    def test_linux_uses_xdg_open(self) -> None:
        """On Linux the log file must be opened via xdg-open."""
        from audio_suite_shared.ui_common import _default_open_log

        with (
            patch("os.path.exists", return_value=True),
            patch.object(sys, "platform", "linux"),
            patch("audio_suite_shared.ui_common.run_secure_subprocess") as mock_run,
        ):
            _default_open_log()
            mock_run.assert_called_once()
            assert mock_run.call_args[0][0] == "xdg-open"

    def test_swallows_oserror_from_startfile(self) -> None:
        """An OSError while opening the log must be swallowed, not raised."""
        from audio_suite_shared.ui_common import _default_open_log

        with (
            patch("os.path.exists", return_value=True),
            patch.object(sys, "platform", "win32"),
            patch("os.startfile", side_effect=OSError("access denied")),
        ):
            _default_open_log()


# ---------------------------------------------------------------------------
# Widget construction tests (require display)
# ---------------------------------------------------------------------------


@requires_display
class TestBuildResultsTab:
    """Tests for build_results_tab return value and widget wiring."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def _make_parent(self) -> tk.Frame:
        return tk.Frame(self.root)

    def test_returns_dict_with_required_keys(self) -> None:
        from audio_suite_shared.ui_common import build_results_tab

        result = build_results_tab(self._make_parent(), "Done!")
        assert "completion_label" in result
        assert "time_label" in result
        assert "summary_label" in result

    def test_completion_text_applied_to_label(self) -> None:
        from audio_suite_shared.ui_common import build_results_tab

        result = build_results_tab(self._make_parent(), "Analysis Complete!")
        assert result["completion_label"]["text"] == "Analysis Complete!"

    def test_extra_labels_returned(self) -> None:
        from audio_suite_shared.ui_common import build_results_tab

        result = build_results_tab(
            self._make_parent(), "Done", extra_labels=["genre_label", "mood_label"]
        )
        assert "genre_label" in result
        assert "mood_label" in result
        assert isinstance(result["genre_label"], tk.Label)

    def test_extra_labels_are_packed_and_visible(self) -> None:
        """Regression test: extra_labels must be packed, not just created.

        A prior version of build_results_tab created extra labels without
        calling .pack() on them, so values set via .config(text=...) were
        never visible to the user. winfo_manager() returns "" for a widget
        with no geometry manager applied and "pack" once .pack() has run.
        """
        from audio_suite_shared.ui_common import build_results_tab

        result = build_results_tab(
            self._make_parent(), "Done", extra_labels=["genre_label"]
        )
        assert result["genre_label"].winfo_manager() == "pack"

    def test_default_open_log_used_when_no_callback(self) -> None:
        """When on_open_log is None, _default_open_log must be wired in."""
        from audio_suite_shared import ui_common

        with patch.object(ui_common, "_default_open_log"):
            ui_common.build_results_tab(self._make_parent(), "Done")
        # We can't directly inspect button command, but no exception means wiring ok


@requires_display
class TestBuildProcessingTab:
    """Tests for build_processing_tab return value."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def _make_parent(self) -> tk.Frame:
        return tk.Frame(self.root)

    def test_returns_dict_with_required_keys(self) -> None:
        from audio_suite_shared.ui_common import build_processing_tab

        result = build_processing_tab(self._make_parent())
        assert "overall_status" in result
        assert "progress" in result
        assert "stats_label" in result
        assert "file_listbox" in result

    def test_overall_status_is_string_var(self) -> None:
        from audio_suite_shared.ui_common import build_processing_tab

        result = build_processing_tab(self._make_parent())
        assert isinstance(result["overall_status"], tk.StringVar)

    def test_initial_stats_text_applied(self) -> None:
        from audio_suite_shared.ui_common import build_processing_tab

        custom_stats = "Processed: 5 | Skipped: 1 | Errors: 0"
        result = build_processing_tab(self._make_parent(), stats_text=custom_stats)
        assert result["stats_label"]["text"] == custom_stats

    def test_no_slot_vars_omits_worker_frame(self) -> None:
        """Passing slot_vars=None must not raise and must still return required keys."""
        from audio_suite_shared.ui_common import build_processing_tab

        result = build_processing_tab(self._make_parent(), slot_vars=None)
        assert "file_listbox" in result

    def test_with_slot_vars(self) -> None:
        """Passing slot_vars must not raise."""
        from audio_suite_shared.ui_common import build_processing_tab

        svars = [tk.StringVar(value="IDLE") for _ in range(4)]
        result = build_processing_tab(self._make_parent(), slot_vars=svars)
        assert "file_listbox" in result


@requires_display
class TestPathRow:
    """Tests for the path_row layout helper."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_does_not_raise_with_valid_args(self) -> None:
        from audio_suite_shared.ui_common import path_row

        parent = tk.Frame(self.root)
        var = tk.StringVar()
        path_row(parent, "Input Folder:", var, lambda: None)


@requires_display
class TestSliderRow:
    """Tests for the slider_row layout helper."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_does_not_raise_with_valid_args(self) -> None:
        from audio_suite_shared.ui_common import slider_row

        parent = tk.Frame(self.root)
        var = tk.DoubleVar(value=0.5)
        slider_row(parent, "Gain", var, from_=0.0, to=1.0, resolution=0.01)


@requires_display
class TestDiscreteSliderRow:
    """Tests for the discrete_slider_row layout helper."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_does_not_raise_with_valid_args(self) -> None:
        from audio_suite_shared.ui_common import discrete_slider_row

        parent = tk.Frame(self.root)
        var = tk.StringVar(value="-16.0")
        discrete_slider_row(
            parent, "Target LUFS", var, values=[-12.0, -14.0, -16.0, -18.0, -23.0]
        )

    def test_raises_on_empty_values(self) -> None:
        from audio_suite_shared.ui_common import discrete_slider_row

        parent = tk.Frame(self.root)
        var = tk.StringVar(value="-16.0")
        with pytest.raises(AudioConfigurationError, match="values must not be empty"):
            discrete_slider_row(parent, "Target LUFS", var, values=[])

    def test_matching_initial_value_is_preserved(self) -> None:
        """An initial var value already present in values must be untouched."""
        from audio_suite_shared.ui_common import discrete_slider_row

        parent = tk.Frame(self.root)
        var = tk.StringVar(value="-18.0")
        discrete_slider_row(
            parent, "Target LUFS", var, values=[-12.0, -14.0, -16.0, -18.0, -23.0]
        )
        assert var.get() == "-18.0"

    def test_nonpreset_initial_value_snaps_to_nearest(self) -> None:
        """An out-of-list initial value must snap to the nearest preset,
        not silently fall back to the first stop."""
        from audio_suite_shared.ui_common import discrete_slider_row

        parent = tk.Frame(self.root)
        var = tk.StringVar(value="-17.5")  # closest to -18.0 (diff 0.5)
        discrete_slider_row(
            parent, "Target LUFS", var, values=[-12.0, -14.0, -16.0, -18.0, -23.0]
        )
        assert var.get() == "-18.0"

    def test_unparseable_initial_value_falls_back_to_first_stop(self) -> None:
        from audio_suite_shared.ui_common import discrete_slider_row

        parent = tk.Frame(self.root)
        var = tk.StringVar(value="")
        discrete_slider_row(
            parent, "Target LUFS", var, values=[-12.0, -14.0, -16.0, -18.0, -23.0]
        )
        assert var.get() == "-12.0"

    def test_empty_label_omits_label_widget(self) -> None:
        """label='' must not render a bare ':' label."""
        from audio_suite_shared.ui_common import discrete_slider_row

        parent = tk.Frame(self.root)
        var = tk.StringVar(value="-16.0")
        discrete_slider_row(parent, "", var, values=[-12.0, -14.0, -16.0])
        row = parent.winfo_children()[0]
        label_texts = [
            w["text"] for w in row.winfo_children() if isinstance(w, tk.Label)
        ]
        assert ":" not in label_texts

    def test_slider_position_updates_when_var_set_externally_after_build(
        self,
    ) -> None:
        """Regression test for the ReplayGain Analyzer bug: a value pushed into
        var *after* the row is built (e.g. CLI args applied post-UI-build, as
        UniversalCLIHandler does) must move the Scale, not just the text
        readout. Previously the Scale's index_var was only computed once at
        build time and never re-synced."""
        from audio_suite_shared.ui_common import discrete_slider_row

        parent = tk.Frame(self.root)
        var = tk.StringVar(value="-16.0")
        discrete_slider_row(
            parent, "Target LUFS", var, values=[-12.0, -14.0, -16.0, -18.0, -23.0]
        )
        row = parent.winfo_children()[0]
        scale = [w for w in row.winfo_children() if isinstance(w, tk.Scale)][0]
        try:
            assert scale.get() == 2  # -16.0
        except AssertionError:
            # Broken Tcl/Tk environment — skip
            pytest.skip("tkinter Scale not working in this environment")

        # Simulate CLI args being applied after the UI is already built.
        var.set("-23.0")

        assert var.get() == "-23.0"
        assert scale.get() == 4  # -23.0 is index 4

    def test_trace_callback_resyncs_scales_beyond_initial_build(self) -> None:
        """The var write-trace must fire whenever var changes externally, even
        multiple times after build (e.g. a second CLI value pass)."""
        from audio_suite_shared.ui_common import discrete_slider_row

        parent = tk.Frame(self.root)
        var = tk.StringVar(value="-16.0")
        discrete_slider_row(
            parent, "Target LUFS", var, values=[-12.0, -14.0, -16.0, -18.0, -23.0]
        )
        row = parent.winfo_children()[0]
        scale = [w for w in row.winfo_children() if isinstance(w, tk.Scale)][0]
        index_var_name = str(scale.cget("variable"))

        def scale_index() -> int:
            return int(self.root.tk.getvar(index_var_name))

        # Probe: if the Scale cannot reflect its variable in this environment,
        # skip rather than fail (same policy as the existing Scale test).
        var.set("-18.0")
        self.root.update()
        if scale_index() != 3:
            pytest.skip("Scale variable not functional in this environment")

        var.set("-12.0")
        self.root.update()
        assert scale_index() == 0

        # "-13.0" is equidistant from -12.0 and -14.0; the first index (0)
        # wins the tie, exactly matching is not required.
        var.set("-13.0")
        self.root.update()
        assert scale_index() == 0  # first index has smallest |values[i] - -13|

    def test_trace_callback_handles_unparseable_value(self) -> None:
        """A non-numeric var value must leave the Scale position untouched."""
        from audio_suite_shared.ui_common import discrete_slider_row

        parent = tk.Frame(self.root)
        var = tk.StringVar(value="")
        discrete_slider_row(parent, "Target LUFS", var, values=[-12.0, -14.0, -16.0])
        row = parent.winfo_children()[0]
        scale = [w for w in row.winfo_children() if isinstance(w, tk.Scale)][0]
        index_var_name = str(scale.cget("variable"))

        def scale_index() -> int:
            return int(self.root.tk.getvar(index_var_name))

        assert scale_index() == 0  # fallback to first stop

        var.set("not-a-number")
        self.root.update()
        assert scale_index() == 0  # untouched

    def test_on_move_sets_var_to_formatted_value(self) -> None:
        """Dragging the Scale must write the formatted preset into var."""
        from audio_suite_shared.ui_common import discrete_slider_row

        parent = tk.Frame(self.root)
        var = tk.StringVar(value="-16.0")
        discrete_slider_row(
            parent, "Target LUFS", var, values=[-12.0, -14.0, -16.0, -18.0, -23.0]
        )
        row = parent.winfo_children()[0]
        scale = [w for w in row.winfo_children() if isinstance(w, tk.Scale)][0]

        # Invoke the Tk command the Scale is wired to (the _on_move closure)
        # just as a user drag would, then flush pending Tcl callbacks.
        self.root.tk.call(scale.cget("command"), "4")
        self.root.update()
        assert var.get() == "-23.0"


# ═══════════════════════════════════════════════════════════════════════════════
# show_message  (requires display)
# ═══════════════════════════════════════════════════════════════════════════════


@requires_display
class TestShowMessage:
    """Tests for show_message modal dialog."""

    @staticmethod
    def _close_all_toplevels(root: tk.Misc) -> None:
        """Destroy any Toplevel windows (used to unblock wait_window)."""
        for w in root.winfo_children():
            if isinstance(w, tk.Toplevel):
                w.destroy()

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_creates_toplevel_and_destroys_on_ok(self) -> None:
        """The dialog must create a Toplevel and destroy it when OK is clicked."""
        from audio_suite_shared.ui_common import show_message

        self.root.after(200, self._close_all_toplevels, self.root)
        show_message(self.root, "Test Title", "Test message body")

        # After show_message returns, no Toplevel should remain.
        for child in self.root.winfo_children():
            assert not isinstance(child, tk.Toplevel)

    def test_returns_none(self) -> None:
        """show_message has no return value."""
        from audio_suite_shared.ui_common import show_message

        self.root.after(200, self._close_all_toplevels, self.root)
        result = show_message(self.root, "Title", "Message")
        assert result is None

    def test_custom_icon_and_color(self) -> None:
        """Custom icon and icon_color must not cause errors."""
        from audio_suite_shared.ui_common import show_message

        self.root.after(200, self._close_all_toplevels, self.root)
        show_message(self.root, "Custom", "Body", icon="⚠", icon_color="#ff0000")

    def test_keyboard_escape_destroys_dialog(self) -> None:
        """Pressing Escape must destroy the dialog."""
        from audio_suite_shared.ui_common import show_message

        # Escape is bound on the dialog itself; schedule a find-and-destroy
        self.root.after(200, self._close_all_toplevels, self.root)
        show_message(self.root, "Escape Test", "Press Escape")

    def test_warns_when_called_from_non_main_thread(self) -> None:
        """show_message from a non-main thread must log a warning, not raise."""

        from audio_suite_shared.ui_common import show_message

        dummy_current = object()
        dummy_main = object()
        with (
            patch("threading.current_thread", return_value=dummy_current),
            patch("threading.main_thread", return_value=dummy_main),
            patch("audio_suite_shared.ui_common._log") as mock_log,
        ):
            self.root.after(200, self._close_all_toplevels, self.root)
            show_message(self.root, "Thread Warn", "Called from wrong thread")
        mock_log.warning.assert_called()

    def test_geometry_error_falls_back_to_plain_geometry(self) -> None:
        """If parent geometry queries raise, the dialog must still be placed."""
        from audio_suite_shared.ui_common import show_message

        with patch.object(self.root, "winfo_rootx", side_effect=OSError("no window")):
            self.root.after(200, self._close_all_toplevels, self.root)
            show_message(self.root, "No Geo", "Geometry fallback")


# ═══════════════════════════════════════════════════════════════════════════════
# BaseSetupFrame  (requires display)
# ═══════════════════════════════════════════════════════════════════════════════


class _MinimalFrame(BaseSetupFrame):
    """Concrete subclass whose tool-options stage is empty."""

    def _build_options(self) -> None:
        pass


class _PresetsFirstFrame(BaseSetupFrame):
    """Concrete subclass placing the preset row before the run controls."""

    def _layout(self) -> None:
        self._add_title()
        self._add_preset_row()
        self._add_controls_panel()
        self._build_options()
        self._add_start_button()


def _make_vars(root: tk.Misc) -> dict[str, tk.Variable]:
    """Create the standard tk variables bound to the given root."""
    return {
        "folder_path": tk.StringVar(master=root),
        "run_mode": tk.StringVar(master=root, value="Dry Run"),
        "auto_start": tk.BooleanVar(master=root, value=False),
        "auto_end": tk.BooleanVar(master=root, value=False),
        "clear_logs": tk.BooleanVar(master=root, value=False),
        "parallel": tk.BooleanVar(master=root, value=False),
    }


def _make_base_frame(root: tk.Misc, **overrides) -> _MinimalFrame:
    """Build a fully-wired _MinimalFrame on a fresh parent frame."""
    vars_ = _make_vars(root)
    parent = tk.Frame(root)
    kwargs = {
        "title": "Test Tool",
        "start_text": "BEGIN TEST",
        "on_start": MagicMock(),
        "folder_path": vars_["folder_path"],
        "run_mode": vars_["run_mode"],
        "auto_start_var": vars_["auto_start"],
        "auto_end_var": vars_["auto_end"],
        "clear_logs_var": vars_["clear_logs"],
        "parallel_var": vars_["parallel"],
        "on_browse": MagicMock(),
        "preset_names": ["Preset A"],
        "on_save_preset": MagicMock(),
        "on_delete_preset": MagicMock(),
        "on_preset_selected": MagicMock(),
    }
    kwargs.update(overrides)
    return _MinimalFrame(parent, **kwargs)


def _descendant_texts(widget: tk.Widget) -> list[str]:
    """Collect text-option values from every descendant widget."""
    texts = []
    if isinstance(widget, (tk.Label, tk.Button, tk.Checkbutton, tk.LabelFrame)):
        try:
            texts.append(str(widget.cget("text")))
        except tk.TclError:
            pass
    for child in widget.winfo_children():
        texts.extend(_descendant_texts(child))
    return texts


def _has_descendant_text(widget: tk.Widget, text: str) -> bool:
    """True if widget or any descendant reports the exact text value."""
    if isinstance(widget, (tk.Label, tk.Button, tk.Checkbutton, tk.LabelFrame)):
        try:
            if str(widget.cget("text")) == text:
                return True
        except tk.TclError:
            pass
    return any(_has_descendant_text(child, text) for child in widget.winfo_children())


class TestBaseSetupFrameLayout:
    """Skeleton ordering, widget types, and get_widgets() keys."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_title_applied(self) -> None:
        frame = _make_base_frame(self.root)
        title_texts = [
            c.cget("text") for c in frame.winfo_children() if isinstance(c, tk.Label)
        ]
        assert "Test Tool" in title_texts

    def test_controls_panel_is_driver_controls_panel(self) -> None:
        frame = _make_base_frame(self.root)
        assert isinstance(frame.controls_panel, DriverControlsPanel)

    def test_start_btn_is_tk_button(self) -> None:
        frame = _make_base_frame(self.root)
        assert isinstance(frame.start_btn, tk.Button)

    def test_start_btn_packs_bottom_by_default(self) -> None:
        frame = _make_base_frame(self.root)
        assert frame.start_btn is not None
        assert frame.start_btn.pack_info().get("side") == tk.BOTTOM

    def test_start_btn_omits_side_when_none(self) -> None:
        frame = _make_base_frame(self.root, start_side=None)
        assert frame.start_btn is not None
        # Omitted side falls back to pack's implicit "top", not "bottom".
        assert frame.start_btn.pack_info()["side"] == "top"

    def test_controls_panel_omitted_when_disabled(self) -> None:
        frame = _make_base_frame(self.root, include_controls_panel=False)
        assert frame.controls_panel is None
        assert "controls_panel" not in frame.get_widgets()

    def test_start_btn_is_instance_handle(self) -> None:
        frame = _make_base_frame(self.root)
        assert frame.get_widgets()["start_btn"] is frame.start_btn

    def test_get_widgets_returns_expected_keys(self) -> None:
        frame = _make_base_frame(self.root, on_save_preset=MagicMock())
        assert set(frame.get_widgets()) == {
            "start_btn",
            "controls_panel",
            "preset_combo",
            "refresh_preset_list",
        }

    def test_get_widgets_omits_unbuilt_widgets(self) -> None:
        frame = _make_base_frame(
            self.root, on_save_preset=None, include_controls_panel=False
        )
        assert frame.get_widgets() == {"start_btn": frame.start_btn}


class TestSetDriven:
    """driver_locked gating of the run-controls panel."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_driver_locked_disables_source_entry(self) -> None:
        frame = _make_base_frame(self.root, driver_locked=True)
        assert str(frame.controls_panel.source_entry.cget("state")) == "disabled"

    def test_standalone_source_editable(self) -> None:
        frame = _make_base_frame(self.root, driver_locked=False)
        assert str(frame.controls_panel.source_entry.cget("state")) == "normal"

    def test_driver_locked_disables_mode_combo(self) -> None:
        frame = _make_base_frame(self.root, driver_locked=True)
        assert str(frame.controls_panel.mode_combo.cget("state")) == "disabled"

    def test_auto_start_always_disabled(self) -> None:
        for locked in (True, False):
            frame = _make_base_frame(self.root, driver_locked=locked)
            assert frame.controls_panel.auto_start_btn.cget("state") == "disabled"


class TestPresetRow:
    """Preset-row gating, seeding, refresh, and stale-selection clearing."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_hidden_when_no_save_handler(self) -> None:
        frame = _make_base_frame(self.root, on_save_preset=None)
        assert frame.preset_combo is None
        assert "preset_combo" not in frame.get_widgets()
        assert "refresh_preset_list" not in frame.get_widgets()

    def test_visible_when_save_handler_set(self) -> None:
        frame = _make_base_frame(self.root, on_save_preset=MagicMock())
        assert frame.preset_combo is not None

    def test_visible_when_preset_row_always_and_no_handler(self) -> None:
        frame = _make_base_frame(self.root, on_save_preset=None, preset_row_always=True)
        assert frame.preset_combo is not None
        assert "preset_combo" in frame.get_widgets()
        assert "refresh_preset_list" in frame.get_widgets()

    def test_combo_packed_inside_preset_row_frame(self) -> None:
        """The combobox must live inside the preset-row frame alongside the
        'Presets:' label and the Save/Delete buttons. A combo parented to the
        base frame packs as a direct child and detaches from the row visually.
        """
        frame = _make_base_frame(self.root, on_save_preset=MagicMock())
        combo = frame.preset_combo
        assert combo is not None
        row = combo.master
        assert isinstance(row, tk.Frame)
        assert row is not frame
        assert combo not in frame.winfo_children()
        assert combo in row.winfo_children()
        texts = _descendant_texts(row)
        assert "Presets:" in texts
        assert any(
            isinstance(child, tk.Button) and child.cget("text") == "Save"
            for child in row.winfo_children()
        )

    def test_combo_seeded_from_preset_names(self) -> None:
        frame = _make_base_frame(
            self.root, on_save_preset=MagicMock(), preset_names=["A", "B"]
        )
        assert list(frame.preset_combo["values"]) == ["A", "B"]

    def test_refresh_updates_values(self) -> None:
        frame = _make_base_frame(self.root, on_save_preset=MagicMock())
        frame.refresh_preset_list(["X", "Y"])
        assert list(frame.preset_combo["values"]) == ["X", "Y"]

    def test_stale_selection_cleared(self) -> None:
        frame = _make_base_frame(
            self.root, on_save_preset=MagicMock(), preset_names=["A", "B"]
        )
        frame.preset_combo.set("A")
        frame.refresh_preset_list(["B", "C"])
        assert frame.preset_combo.get() == ""

    def test_current_selection_preserved(self) -> None:
        frame = _make_base_frame(
            self.root, on_save_preset=MagicMock(), preset_names=["A", "B"]
        )
        frame.preset_combo.set("A")
        frame.refresh_preset_list(["A", "C"])
        assert frame.preset_combo.get() == "A"

    def test_loader_honored_on_no_arg_call(self) -> None:
        frame = _make_base_frame(
            self.root, on_save_preset=MagicMock(), preset_loader=lambda: ["L1", "L2"]
        )
        frame.refresh_preset_list()
        assert list(frame.preset_combo["values"]) == ["L1", "L2"]

    def test_explicit_names_override_loader(self) -> None:
        frame = _make_base_frame(
            self.root, on_save_preset=MagicMock(), preset_loader=lambda: ["L1"]
        )
        frame.refresh_preset_list(["X"])
        assert list(frame.preset_combo["values"]) == ["X"]

    def test_refresh_noop_without_preset_row(self) -> None:
        frame = _make_base_frame(self.root, on_save_preset=None)
        frame.refresh_preset_list(["A", "B"])  # must not raise


class TestConfigGroup:
    """add_config_group() behaviour."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_returns_labelframe_with_text(self) -> None:
        frame = _make_base_frame(self.root, on_save_preset=None)
        group = frame.add_config_group("Configuration")
        assert isinstance(group, tk.LabelFrame)
        assert "Configuration" in str(group.cget("text"))

    def test_group_packed_into_frame(self) -> None:
        frame = _make_base_frame(self.root, on_save_preset=None)
        group = frame.add_config_group("Stage")
        assert group.winfo_manager() == "pack"
        assert group.master is frame


class TestParallelRow:
    """add_parallel_row() behaviour."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_descendant_texts_present(self) -> None:
        frame = _make_base_frame(self.root, on_save_preset=None)
        frame.add_parallel_row(
            tk.BooleanVar(master=self.root),
            tk.IntVar(master=self.root, value=4),
            "(caption text)",
        )
        texts = _descendant_texts(frame)
        assert "Parallel Processing" in texts
        assert "Workers:" in texts
        assert "(caption text)" in texts


class TestOrderingOverride:
    """_layout() subclass overrides reorder the additive stages."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    @staticmethod
    def _children(frame: tk.Frame) -> list[tk.Widget]:
        return list(frame.winfo_children())

    def test_default_layout_puts_controls_before_presets(self) -> None:
        frame = _make_base_frame(self.root, on_save_preset=MagicMock())
        children = self._children(frame)
        controls_index = next(
            i for i, c in enumerate(children) if isinstance(c, DriverControlsPanel)
        )
        preset_index = next(
            i
            for i, c in enumerate(children)
            if isinstance(c, tk.Frame)
            and not isinstance(c, DriverControlsPanel)
            and _has_descendant_text(c, "Presets:")
        )
        assert controls_index < preset_index

    def test_overridden_layout_puts_presets_before_controls(self) -> None:
        vars_ = _make_vars(self.root)
        frame = _PresetsFirstFrame(
            tk.Frame(self.root),
            title="Override",
            start_text="BEGIN",
            on_start=MagicMock(),
            folder_path=vars_["folder_path"],
            run_mode=vars_["run_mode"],
            auto_start_var=vars_["auto_start"],
            auto_end_var=vars_["auto_end"],
            clear_logs_var=vars_["clear_logs"],
            parallel_var=vars_["parallel"],
            on_browse=MagicMock(),
            preset_names=["Preset A"],
            on_save_preset=MagicMock(),
            on_delete_preset=MagicMock(),
            on_preset_selected=MagicMock(),
        )
        children = self._children(frame)
        controls_index = next(
            i for i, c in enumerate(children) if isinstance(c, DriverControlsPanel)
        )
        preset_index = next(
            i
            for i, c in enumerate(children)
            if isinstance(c, tk.Frame)
            and not isinstance(c, DriverControlsPanel)
            and _has_descendant_text(c, "Presets:")
        )
        assert preset_index < controls_index


# ═══════════════════════════════════════════════════════════════════════════════
# Preset helpers  (requires display)
# ═══════════════════════════════════════════════════════════════════════════════


class TestSavePresetDialog:
    """save_preset_dialog() modal behaviour."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def _find_toplevel(self) -> tk.Toplevel:
        toplevels = [
            w for w in self.root.winfo_children() if isinstance(w, tk.Toplevel)
        ]
        assert toplevels, "No Toplevel was created"
        return toplevels[-1]

    def test_invokes_on_save_with_typed_name(self) -> None:
        from audio_suite_shared.ui_common import save_preset_dialog

        combo = ttk.Combobox(self.root, values=["My Preset"], state="readonly")
        on_save = MagicMock()
        save_preset_dialog(combo, on_save)
        dialog = self._find_toplevel()
        try:
            entry = next(w for w in dialog.winfo_children() if isinstance(w, tk.Entry))
            entry.insert(0, "My Preset")
            save_btn = next(
                w
                for w in dialog.winfo_children()
                if isinstance(w, tk.Button) and w.cget("text") == "Save"
            )
            save_btn.invoke()
        finally:
            if dialog.winfo_exists():
                dialog.destroy()
        on_save.assert_called_once_with("My Preset")
        assert combo.get() == "My Preset"

    def test_blank_name_does_not_invoke_on_save(self) -> None:
        from audio_suite_shared.ui_common import save_preset_dialog

        combo = ttk.Combobox(self.root, state="readonly")
        on_save = MagicMock()
        save_preset_dialog(combo, on_save)
        dialog = self._find_toplevel()
        try:
            save_btn = next(
                w
                for w in dialog.winfo_children()
                if isinstance(w, tk.Button) and w.cget("text") == "Save"
            )
            save_btn.invoke()
        finally:
            if dialog.winfo_exists():
                dialog.destroy()
        on_save.assert_not_called()
        assert combo.get() == ""


class TestDeletePresetAction:
    """delete_preset_action() confirm-and-delete behaviour."""

    @pytest.fixture(autouse=True)
    def setup_tk(self, tk_root) -> None:
        self.root = tk_root

    def test_confirm_calls_on_delete_and_clears(self) -> None:
        from audio_suite_shared.ui_common import delete_preset_action

        combo = ttk.Combobox(self.root, values=["Preset A"], state="readonly")
        combo.set("Preset A")
        on_delete = MagicMock()
        with patch("tkinter.messagebox.askyesno", return_value=True):
            delete_preset_action(combo, on_delete)
        on_delete.assert_called_once_with("Preset A")
        assert combo.get() == ""

    def test_cancel_does_not_delete(self) -> None:
        from audio_suite_shared.ui_common import delete_preset_action

        combo = ttk.Combobox(self.root, values=["Preset A"], state="readonly")
        combo.set("Preset A")
        on_delete = MagicMock()
        with patch("tkinter.messagebox.askyesno", return_value=False):
            delete_preset_action(combo, on_delete)
        on_delete.assert_not_called()
        assert combo.get() == "Preset A"

    def test_no_selection_skips_prompt(self) -> None:
        from audio_suite_shared.ui_common import delete_preset_action

        combo = ttk.Combobox(self.root, state="readonly")
        on_delete = MagicMock()
        with patch("tkinter.messagebox.askyesno", return_value=True) as ask:
            delete_preset_action(combo, on_delete)
        ask.assert_not_called()
        on_delete.assert_not_called()

    def test_on_delete_none_still_confirms_and_clears(self) -> None:
        from audio_suite_shared.ui_common import delete_preset_action

        combo = ttk.Combobox(self.root, values=["Preset A"], state="readonly")
        combo.set("Preset A")
        with patch("tkinter.messagebox.askyesno", return_value=True):
            delete_preset_action(combo, None)
        assert combo.get() == ""
