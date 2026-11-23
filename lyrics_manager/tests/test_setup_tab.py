"""tests/test_setup_tab.py — Lyrics Manager Setup tab wiring under a hidden Tk root.

Changed in 2.9.0: ``parent`` is the test's own container on the shared root
and the fixture destroys it, so a build cannot leave a second title label on the
session root for the shell contract to count and the module no longer declares
``clean_shared_root``.
"""

from __future__ import annotations

import tkinter as tk
from unittest.mock import MagicMock

from lyrics_manager.ui.setup_tab import build


def _build_tab(parent: tk.Frame, **override: object) -> dict[str, object]:
    """Construct the Setup tab in *parent* and return its widgets."""
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

    def test_row_renders_with_zero_arg_handlers(self, parent: tk.Frame) -> None:
        widgets = _build_tab(parent)
        assert widgets["preset_combo"] is not None
        assert "refresh_preset_list" in widgets

    def test_row_hidden_without_save_handler(self, parent: tk.Frame) -> None:
        widgets = _build_tab(parent, on_save_preset=None)
        assert "preset_combo" not in widgets
        assert "refresh_preset_list" not in widgets

    def test_save_button_is_wired(self, parent: tk.Frame) -> None:
        save = MagicMock()
        widgets = _build_tab(parent, on_save_preset=save)
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

    def test_delete_button_is_wired(self, parent: tk.Frame) -> None:
        delete = MagicMock()
        widgets = _build_tab(parent, on_delete_preset=delete)
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

    def test_refresh_seeds_preset_values(self, parent: tk.Frame) -> None:
        widgets = _build_tab(parent)
        refresh = widgets["refresh_preset_list"]
        assert callable(refresh)
        refresh(["A", "B"])
        assert list(widgets["preset_combo"]["values"]) == ["A", "B"]
