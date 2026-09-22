"""
tests/test_ui.py
Smoke tests for tempo_analyzer UI tab builders.

Each build() function is exercised with a real (headless) tkinter root to
confirm the widget tree is constructed without error and that required widget
references are returned.  No display is required; tkinter works in
non-interactive mode when withdraw() is called.

audio_suite_shared is stubbed via conftest.py.
"""

import tkinter as tk

import pytest

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tk_root():
    """Provide a hidden tkinter root and destroy it after the test."""
    try:
        root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"tkinter not available: {exc}")
    root.withdraw()
    yield root
    try:
        root.destroy()
    except tk.TclError:
        pass


# ---------------------------------------------------------------------------
# setup_tab.build
# ---------------------------------------------------------------------------


class TestSetupTabBuild:
    def _build(self, tk_root: tk.Tk) -> dict:
        from tempo_analyzer.core.tempo_schemes import TEMPO_SCHEMES
        from tempo_analyzer.ui.setup_tab import build

        frame = tk.Frame(tk_root)
        scheme_names = list(TEMPO_SCHEMES.keys())
        return build(
            parent=frame,
            folder_path=tk.StringVar(tk_root),
            run_mode=tk.StringVar(tk_root, value="dry"),
            tempo_scheme=tk.StringVar(tk_root, value=scheme_names[0]),
            scheme_names=scheme_names,
            auto_start_var=tk.BooleanVar(tk_root),
            auto_end_var=tk.BooleanVar(tk_root),
            clear_logs_var=tk.BooleanVar(tk_root),
            parallel_var=tk.BooleanVar(tk_root),
            on_browse=lambda: None,
            on_start=lambda: None,
            on_scheme_change=lambda: None,
            on_preset_select=lambda n: None,
            on_save_preset=lambda n: None,
            on_delete_preset=lambda n: None,
        )

    def test_build_returns_dict(self, tk_root):
        result = self._build(tk_root)
        assert isinstance(result, dict)
        assert set(result) == {
            "start_btn",
            "update_reference",
            "refresh_preset_list",
            "preset_combo",
            "controls_panel",
        }

    def test_first_element_is_button(self, tk_root):
        assert isinstance(self._build(tk_root)["start_btn"], tk.Button)

    def test_second_element_is_callable(self, tk_root):
        assert callable(self._build(tk_root)["update_reference"])

    def test_update_reference_callable_accepts_markings(self, tk_root):
        from tempo_analyzer.core.tempo_schemes import TEMPO_SCHEMES

        update_ref = self._build(tk_root)["update_reference"]
        markings = TEMPO_SCHEMES[next(iter(TEMPO_SCHEMES))]
        update_ref(markings)  # Must not raise


# ---------------------------------------------------------------------------
# processing_tab.build
# ---------------------------------------------------------------------------


class TestProcessingTabBuild:
    def test_build_returns_dict(self, tk_root):
        from tempo_analyzer.ui.processing_tab import build

        frame = tk.Frame(tk_root)
        result = build(frame)
        assert isinstance(result, dict)

    def test_build_with_slot_vars_does_not_raise(self, tk_root):
        from tempo_analyzer.ui.processing_tab import build

        frame = tk.Frame(tk_root)
        slot_vars = [tk.StringVar(tk_root, value="idle") for _ in range(4)]
        result = build(frame, slot_vars=slot_vars)
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# results_tab.build
# ---------------------------------------------------------------------------


class TestResultsTabBuild:
    def test_build_returns_dict(self, tk_root):
        from tempo_analyzer.ui.results_tab import build

        frame = tk.Frame(tk_root)
        result = build(
            parent=frame,
            on_open_log=lambda: None,
            on_open_folder=lambda: None,
        )
        assert isinstance(result, dict)
