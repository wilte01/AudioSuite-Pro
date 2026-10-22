"""Tests for ``master_driver.ui.utilities_window`` layout.

The Utilities tab is a grid, not a stack: seventeen cards in two weighted
columns, the card whose Settings are open spanning both, and the LAUNCH
button pinned below the scrolling area.  These tests build the real tab with
the real :class:`AppState` and assert the resulting geometry *structure*
(grid cell, column span, pack side) rather than pixel heights, so they do not
depend on the host's screen size or theme.

Changed in 2.0.0: initial version - locks the two-column reflow and the
pinned launch button (PLAN_feature_expansion.md D119).
"""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from audio_suite_shared.tool_plugin import get_registry
from master_driver.state.app_state import AppState
from master_driver.ui import utilities_window

_UTILITY_IDS: tuple[str, ...] = tuple(
    manifest.id for manifest in get_registry().by_category("utility")
)


@dataclass
class _Tab:
    """One built Utilities tab, with the pieces the tests reach into."""

    frame: tk.Frame
    state: AppState
    run_button: tk.Button


def _build_tab(
    root: tk.Misc,
    on_run: Callable[[], None] | None = None,
    on_open_undo: Callable[[], None] | None = None,
) -> _Tab:
    """Build the Utilities tab into a fresh frame."""
    frame = tk.Frame(root)
    state = AppState()
    run_button = utilities_window.build(
        frame,
        state,
        on_run=on_run if on_run is not None else (lambda: None),
        on_open_undo=on_open_undo if on_open_undo is not None else (lambda: None),
    )
    frame.update_idletasks()
    return _Tab(frame=frame, state=state, run_button=run_button)


@pytest.fixture()
def tab(root: tk.Misc) -> Iterator[_Tab]:
    built = _build_tab(root)
    yield built
    built.frame.destroy()


def _find(widget: tk.Misc, kind: type) -> list[Any]:
    found: list[Any] = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found.extend(_find(child, kind))
    return found


def _canvas(tab: _Tab) -> tk.Canvas:
    canvases = _find(tab.frame, tk.Canvas)
    assert len(canvases) == 1
    canvas: tk.Canvas = canvases[0]
    return canvas


def _scroll_frame(tab: _Tab) -> tk.Frame:
    children = _canvas(tab).winfo_children()
    assert len(children) == 1
    scroll_frame: tk.Frame = children[0]
    return scroll_frame


def _grid_host(tab: _Tab) -> tk.Frame:
    host: tk.Frame = _scroll_frame(tab).winfo_children()[0]
    return host


def _cells(tab: _Tab) -> list[tk.Frame]:
    cells = [
        child
        for child in _grid_host(tab).winfo_children()
        if isinstance(child, tk.Frame)
    ]
    return cells


def _cell_at(tab: _Tab, index: int) -> tk.Frame:
    return _cells(tab)[index]


def _undo_cell(tab: _Tab) -> tk.Frame:
    return _cell_at(tab, _UTILITY_IDS.index("undo_tag_edits"))


def _outer(cell: tk.Frame) -> tk.Frame:
    outer: tk.Frame = cell.winfo_children()[0]
    return outer


def _header(cell: tk.Frame) -> tk.Frame:
    header: tk.Frame = _outer(cell).winfo_children()[0]
    return header


def _body(cell: tk.Frame) -> tk.Frame:
    body: tk.Frame = _outer(cell).winfo_children()[1]
    return body


def _expand_button(cell: tk.Frame) -> tk.Button:
    """The Settings button is the header's only plain Button."""
    buttons = [w for w in _header(cell).winfo_children() if isinstance(w, tk.Button)]
    assert len(buttons) == 1
    expand: tk.Button = buttons[0]
    return expand


def _ancestors(widget: tk.Misc) -> list[tk.Misc]:
    chain: list[tk.Misc] = []
    current: tk.Misc | None = widget
    while current is not None:
        chain.append(current)
        parent = current.master
        current = parent if isinstance(parent, tk.Misc) else None
    return chain


class TestCardGrid:
    """Seventeen cards cost nine rows, not seventeen."""

    def test_one_cell_per_registry_card(self, tab) -> None:
        assert len(_cells(tab)) == len(_UTILITY_IDS)

    def test_host_has_two_weighted_columns(self, tab) -> None:
        host = _grid_host(tab)
        for column in range(utilities_window._CARD_COLUMNS):
            assert host.columnconfigure(column)["weight"] == 1

    def test_cards_fill_columns_left_to_right(self, tab) -> None:
        first, second, third = (_cell_at(tab, index) for index in range(3))

        assert (first.grid_info()["row"], first.grid_info()["column"]) == (0, 0)
        assert (second.grid_info()["row"], second.grid_info()["column"]) == (0, 1)
        assert (third.grid_info()["row"], third.grid_info()["column"]) == (1, 0)

    def test_last_card_lands_on_the_expected_row(self, tab) -> None:
        """A one-column stack would need one row per card."""
        expected_rows = math.ceil(len(_UTILITY_IDS) / utilities_window._CARD_COLUMNS)
        rows = {cell.grid_info()["row"] for cell in _cells(tab)}

        assert max(rows) + 1 == expected_rows
        assert expected_rows < len(_UTILITY_IDS)


class TestExpansionReflow:
    """Opening a card's Settings gives it the full width and moves the rest."""

    def test_expanded_card_spans_both_columns(self, tab) -> None:
        cell = _cell_at(tab, 0)

        _expand_button(cell).invoke()
        tab.frame.update_idletasks()

        assert cell.grid_info()["columnspan"] == utilities_window._CARD_COLUMNS

    def test_the_cards_after_it_reflow_behind(self, tab) -> None:
        first, second, third = (_cell_at(tab, index) for index in range(3))

        _expand_button(first).invoke()
        tab.frame.update_idletasks()

        # The opened card took the whole first row, so the pair behind it
        # starts a fresh row rather than sharing one with it.
        assert (second.grid_info()["row"], second.grid_info()["column"]) == (1, 0)
        assert (third.grid_info()["row"], third.grid_info()["column"]) == (1, 1)

    def test_collapsing_restores_the_pairing(self, tab) -> None:
        first, second = (_cell_at(tab, index) for index in range(2))
        settings = _expand_button(first)

        settings.invoke()
        tab.frame.update_idletasks()
        settings.invoke()
        tab.frame.update_idletasks()

        assert first.grid_info()["columnspan"] == 1
        assert (second.grid_info()["row"], second.grid_info()["column"]) == (0, 1)

    def test_two_cards_open_at_once_still_span(self, tab) -> None:
        """Expansion is per card: opening a second one does not narrow the first."""
        first, second = (_cell_at(tab, index) for index in range(2))

        _expand_button(first).invoke()
        tab.frame.update_idletasks()
        _expand_button(second).invoke()
        tab.frame.update_idletasks()

        assert first.grid_info()["columnspan"] == utilities_window._CARD_COLUMNS
        assert second.grid_info()["columnspan"] == utilities_window._CARD_COLUMNS
        assert first.grid_info()["row"] < second.grid_info()["row"]


class TestPinnedLaunchButton:
    """LAUNCH is the primary action, so it is outside the scrolling area."""

    def test_button_is_not_inside_the_scroll_area(self, tab) -> None:
        chain = _ancestors(tab.run_button)

        assert _canvas(tab) not in chain
        assert _scroll_frame(tab) not in chain

    def test_button_sits_at_the_bottom_of_the_tab(self, tab) -> None:
        holder = tab.run_button.master

        assert holder is not None
        assert holder.master is tab.frame
        assert holder.pack_info()["side"] == "bottom"

    def test_button_invokes_the_run_callback(self, root: tk.Misc) -> None:
        calls: list[str] = []
        built = _build_tab(root, on_run=lambda: calls.append("run"))
        try:
            built.run_button.invoke()
        finally:
            built.frame.destroy()

        assert calls == ["run"]

    def test_button_keeps_the_shared_label(self, tab) -> None:
        assert tab.run_button.cget("text") == "LAUNCH UTILITY PROCESS"


class TestUndoCard:
    """Undo is one header row at rest, with its description in the body."""

    def test_undo_card_starts_collapsed(self, tab) -> None:
        # An unpacked body has no geometry manager; asserting on the manager
        # rather than winfo_ismapped() keeps this independent of mapping.
        assert _body(_undo_cell(tab)).winfo_manager() == ""

    def test_undo_card_renders_no_module_checkbox(self, tab) -> None:
        assert _find(_undo_cell(tab), tk.Checkbutton) == []

    def test_undo_card_is_one_row_tall_at_rest(self, tab) -> None:
        undo_cell = _undo_cell(tab)
        neighbour = _cell_at(tab, 0)

        # Both are collapsed headers, so neither may be taller than the other.
        assert abs(undo_cell.winfo_reqheight() - neighbour.winfo_reqheight()) <= 4

    def test_open_undo_is_reachable_once_expanded(self, root: tk.Misc) -> None:
        calls: list[str] = []
        built = _build_tab(root, on_open_undo=lambda: calls.append("open"))
        try:
            cell = _undo_cell(built)
            _expand_button(cell).invoke()
            built.frame.update_idletasks()

            buttons = [
                b for b in _find(cell, tk.Button) if b.cget("text") == "Open Undo"
            ]
            assert len(buttons) == 1
            buttons[0].invoke()
        finally:
            built.frame.destroy()

        assert calls == ["open"]


def _is_descendant(widget: tk.Misc | None, ancestor: tk.Misc) -> bool:
    return widget is not None and ancestor in _ancestors(widget)


class TestConverterCard:
    """The converter's Settings still attach their widgets to the shared state."""

    def test_checking_the_toggle_rescans_the_folder(
        self, root: tk.Misc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shell's checkbox keeps the converter's re-scan command."""
        calls: list[str] = []
        monkeypatch.setattr(
            utilities_window,
            "update_format_detection",
            lambda _state: calls.append("scan"),
        )
        built = _build_tab(root)
        try:
            cell = _cell_at(built, _UTILITY_IDS.index("converter"))
            checkbox = _find(cell, tk.Checkbutton)[0]
            checkbox.invoke()
            checkbox.invoke()
        finally:
            built.frame.destroy()

        # On, then off: only the tick that enables the converter re-scans.
        assert calls == ["scan"]

    def test_detected_label_and_format_menu_live_in_the_card_body(self, tab) -> None:
        body = _body(_cell_at(tab, _UTILITY_IDS.index("converter")))

        # The converter now renders through the shared shell; its two state
        # references must still point at widgets inside the collapsible body
        # `update_format_detection` writes to.
        assert _is_descendant(tab.state._converter_detected_label, body)
        assert _is_descendant(tab.state._converter_format_menu, body)
