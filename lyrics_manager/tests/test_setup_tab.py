"""tests/test_setup_tab.py — Lyrics Manager Setup tab wiring under a hidden Tk root."""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

import pytest

from lyrics_manager.ui.setup_tab import build


def _build_tab(root: tk.Tk, **override: object) -> dict[str, object]:
    """Construct the Setup tab with real Tk variables and return its widgets."""
    parent = tk.Frame(root)
    kwargs: dict[str, object] = dict(
        folder_path=tk.StringVar(),
        run_mode=tk.StringVar(value="Dry Run"),
        provider=tk.StringVar(),
        request_timeout=tk.StringVar(value="10.0"),
        skip_existing=tk.BooleanVar(value=True),
        plain_fallback=tk.BooleanVar(value=True),
        auto_start_var=tk.BooleanVar(),
        auto_end_var=tk.BooleanVar(),
        clear_logs_var=tk.BooleanVar(),
        parallel_var=tk.BooleanVar(),
        on_browse=MagicMock(),
        on_start=MagicMock(),
        parallel_mode=tk.BooleanVar(),
        max_workers=tk.IntVar(value=4),
        on_save_preset=MagicMock(),
        on_delete_preset=MagicMock(),
    )
    kwargs.update(override)
    return build(parent, **kwargs)  # type: ignore[arg-type]


class TestPresetRow:
    """The zero-argument preset callbacks must survive the base constructor
    and render the preset row (regression: the base __init__ used to clobber
    the subclass-set callbacks with its own None defaults, so the row was
    never created in the real window)."""

    @staticmethod
    @pytest.fixture(autouse=True)
    def setup_tk(tk_root: tk.Tk) -> tk.Tk:
        return tk_root

    def test_row_renders_with_zero_arg_handlers(self, setup_tk: tk.Tk) -> None:
        widgets = _build_tab(setup_tk)
        assert widgets["preset_combo"] is not None
        assert "refresh_preset_list" in widgets

    def test_row_hidden_without_save_handler(self, setup_tk: tk.Tk) -> None:
        widgets = _build_tab(setup_tk, on_save_preset=None)
        assert "preset_combo" not in widgets
        assert "refresh_preset_list" not in widgets

    def test_save_button_is_wired(self, setup_tk: tk.Tk) -> None:
        save = MagicMock()
        widgets = _build_tab(setup_tk, on_save_preset=save)
        combo = widgets["preset_combo"]
        assert combo is not None
        buttons = [
            child
            for child in combo.master.winfo_children()
            if isinstance(child, tk.Button)
        ]
        save_button = next(
            button for button in buttons if button.cget("text") == "Save"
        )
        assert save_button is not None

    def test_delete_button_is_wired(self, setup_tk: tk.Tk) -> None:
        delete = MagicMock()
        widgets = _build_tab(setup_tk, on_delete_preset=delete)
        combo = widgets["preset_combo"]
        assert combo is not None
        buttons = [
            child
            for child in combo.master.winfo_children()
            if isinstance(child, tk.Button)
        ]
        delete_button = next(
            button for button in buttons if button.cget("text") == "Delete"
        )
        assert delete_button is not None

    def test_refresh_seeds_preset_values(self, setup_tk: tk.Tk) -> None:
        widgets = _build_tab(setup_tk)
        refresh = widgets["refresh_preset_list"]
        assert callable(refresh)
        refresh(["A", "B"])
        assert list(widgets["preset_combo"]["values"]) == ["A", "B"]
