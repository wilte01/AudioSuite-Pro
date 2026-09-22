"""
Tests for metadata_scrubber.ui.setup_tab — Run Controls panel embedding.

Uses the session-scoped real Tk root from conftest.py.
"""

import tkinter as tk

import pytest

from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from metadata_scrubber.ui.setup_tab import SetupTab


def _find_labels(widget: tk.Widget, text: str) -> list[tk.Widget]:
    """Recursively collect widgets whose text equals ``text``."""
    found: list[tk.Widget] = []
    for child in widget.winfo_children():
        try:
            if str(child.cget("text")) == text:
                found.append(child)
        except tk.TclError:
            pass  # containers (Frame/Canvas/Scrollbar) have no text option
        found.extend(_find_labels(child, text))
    return found


@pytest.fixture
def tab_vars(root: tk.Tk) -> dict[str, tk.Variable]:
    """Fresh tkinter variables for one SetupTab instance."""
    return {
        "folder": tk.StringVar(master=root),
        "mode": tk.StringVar(master=root, value="Dry Run"),
        "auto_start": tk.BooleanVar(master=root, value=False),
        "auto_end": tk.BooleanVar(master=root, value=False),
        "clear_logs": tk.BooleanVar(master=root, value=False),
        "parallel": tk.BooleanVar(master=root, value=False),
        "lyrics": tk.BooleanVar(master=root, value=True),
        "album_artist": tk.BooleanVar(master=root, value=True),
        "embedded_art": tk.BooleanVar(master=root, value=True),
    }


@pytest.fixture
def parent(root: tk.Tk) -> tk.Frame:
    frame = tk.Frame(root)
    frame.pack()
    yield frame
    frame.destroy()


@pytest.fixture
def make_tab(parent: tk.Frame, tab_vars: dict[str, tk.Variable]):
    """Factory building a SetupTab with sensible defaults."""

    def _factory(**overrides: object) -> SetupTab:
        kwargs: dict[str, object] = {
            "folder_path": tab_vars["folder"],
            "run_mode": tab_vars["mode"],
            "auto_start_var": tab_vars["auto_start"],
            "auto_end_var": tab_vars["auto_end"],
            "clear_logs_var": tab_vars["clear_logs"],
            "parallel_var": tab_vars["parallel"],
            "preserve_lyrics": tab_vars["lyrics"],
            "preserve_album_artist": tab_vars["album_artist"],
            "preserve_embedded_art": tab_vars["embedded_art"],
            "on_browse_scan": lambda: None,
            "on_start": lambda: None,
            **overrides,
        }
        return SetupTab(parent, **kwargs)  # type: ignore[arg-type]

    return _factory


class TestSetupTabConstruction:
    def test_embeds_driver_controls_panel(self, make_tab) -> None:
        tab = make_tab()
        assert isinstance(tab.controls_panel, DriverControlsPanel)

    def test_start_button_present_and_wired(self, make_tab) -> None:
        tab = make_tab()
        assert isinstance(tab.start_btn, tk.Button)
        assert tab.start_btn.cget("text") == "BEGIN SCRUBBING"

    def test_legacy_execution_mode_row_removed(self, make_tab, parent) -> None:
        make_tab()
        assert _find_labels(parent, "Execution Mode:") == []

    def test_legacy_source_row_removed(self, make_tab, parent) -> None:
        make_tab()
        assert _find_labels(parent, "Source Music Directory:") != []
        # The label now lives exactly once — inside the shared panel.
        assert len(_find_labels(parent, "Source Music Directory:")) == 1


class TestDriverLockedStates:
    def test_standalone_leaves_mode_editable(self, make_tab) -> None:
        tab = make_tab(driver_locked=False)
        assert str(tab.controls_panel.mode_combo.cget("state")) == "readonly"
        assert tab.controls_panel.auto_start_btn.cget("state") == "disabled"
        assert tab.controls_panel.auto_end_btn.cget("state") == "normal"

    def test_driven_locks_all_controls(self, make_tab) -> None:
        tab = make_tab(driver_locked=True)
        panel = tab.controls_panel
        assert panel.source_entry.cget("state") == "disabled"
        assert str(panel.mode_combo.cget("state")) == "disabled"
        assert panel.auto_start_btn.cget("state") == "disabled"
        assert panel.auto_end_btn.cget("state") == "disabled"


class TestDriverOnlyMirrorState:
    """Clear Logs / Parallel mirror driver state but stay inert."""

    def test_mirror_vars_bound_and_disabled(
        self, root: tk.Tk, make_tab, tab_vars
    ) -> None:
        tab = make_tab(driver_locked=True)
        panel = tab.controls_panel
        assert str(panel.clear_logs_btn.cget("state")) == "disabled"
        assert str(panel.parallel_btn.cget("state")) == "disabled"

        # Raw Tcl query — cget("variable") is version-specific on 3.14.
        assert root.tk.eval(str(panel.clear_logs_btn) + " cget -variable") == str(
            tab_vars["clear_logs"]
        )
        assert root.tk.eval(str(panel.parallel_btn) + " cget -variable") == str(
            tab_vars["parallel"]
        )

    def test_standalone_still_inert(self, make_tab) -> None:
        tab = make_tab(driver_locked=False)
        assert tab.controls_panel.clear_logs_btn.cget("state") == "disabled"
        assert tab.controls_panel.parallel_btn.cget("state") == "disabled"


class TestPreserveToggles:
    """Tag-preservation options remain untouched by the panel change."""

    def test_preserve_checkbuttons_present(self, make_tab, parent) -> None:
        make_tab()
        assert _find_labels(parent, "Preserve Lyrics (USLT/SYLT)")
        assert _find_labels(parent, "Preserve Album Artist (TPE2)")
        assert _find_labels(parent, "Preserve Embedded Art (APIC)")

    def test_get_preserve_list_respects_kept_preferences(self, make_tab) -> None:
        tab = make_tab()
        tab.populate_tags({"TITLE", "ARTIST"}, previously_kept={"TITLE"})
        assert sorted(tab.get_preserve_list()) == ["TITLE"]
