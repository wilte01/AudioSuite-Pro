"""Tests for ``master_driver.ui.utilities_window`` layout.

The Utilities tab is a grid, not a stack: nineteen cards in two weighted
columns, one full-width caption per group, the card whose Settings are open
spanning both columns, and the LAUNCH button pinned below the scrolling area.
These tests build the real tab with the real :class:`AppState` and assert the
resulting geometry *structure* (grid cell, column span, pack side) rather than
pixel heights, so they do not depend on the host's screen size or theme.

Changed in 2.0.0: initial version - locks the two-column reflow and the
pinned launch button (PLAN_feature_expansion.md D119).
Changed in 2.1.0: locks the plugin card path - the plugin's own ``ui`` entry,
its generic fallback and the fallback when that entry raises (Sprint 7).
Changed in 2.3.1: an expanded card always starts a fresh row at column 0, so
the right column's Settings span the window too; the reflow tests now assert
that cell's column and rendered width, not only its span (L-01).

Changed in 2.3.1 (U-03, released in 2.6.0): the card population is
``driver_by_category`` (the fifteen manifests with ``driver_card=True``), not
every utility manifest, so the five retired DSP cards no longer count towards
the grid's cells.

Changed in 2.6.0: the cards are grouped, so the grid also carries one caption
row per group.  ``EXPECTED_UTILITY_ORDER`` freezes the displayed order (which
is the sequential batch order too) and ``EXPECTED_GROUPS`` freezes the captions
and their membership, so a reorder or a re-grouping is a deliberate diff here
rather than a side effect of a manifest edit.
"""

from __future__ import annotations

import math
import tkinter as tk
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.plugin_system import PluginError
from audio_suite_shared.tool_plugin import ToolManifest, get_registry
from master_driver.state.app_state import AppState
from master_driver.ui import utilities_window
from master_driver.ui.group_caption import GroupCaption

#: The cards the tab renders, in registry order.  It is the driver's utility
#: population, not every utility manifest: five DSP tools still ship (and are
#: still in ``by_category``) without a card, because REFINE runs their work.
_UTILITY_IDS: tuple[str, ...] = tuple(
    manifest.id for manifest in get_registry().driver_by_category("utility")
)

#: The Utilities tab's order, frozen.  This is the display order *and* the
#: sequential batch order, so a reorder is a user-visible change in two places
#: at once and has to be a deliberate, reviewable diff.
EXPECTED_UTILITY_ORDER: tuple[str, ...] = (
    "asx_extractor",
    "cd_ripper",
    "converter",
    "album_art_normalizer",
    "tag_editor",
    "tag_field_updater",
    "undo_tag_edits",
    "library_stats",
    "mood_analysis_batch",
    "spectral_viewer",
    "channel_tools",
    "duplicate_finder",
    "ml_denoiser",
    "restoration",
    "stem_separator",
    "audio_joiner",
    "file_reorganizer",
    "track_splitter",
    "example_tool",
)

#: The captions, in render order, with the ids each one introduces.
EXPECTED_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Convert & Import", ("asx_extractor", "cd_ripper", "converter")),
    (
        "Tags & Artwork",
        ("album_art_normalizer", "tag_editor", "tag_field_updater", "undo_tag_edits"),
    ),
    (
        "Analysis & Inspection",
        ("library_stats", "mood_analysis_batch", "spectral_viewer"),
    ),
    (
        "Repair & Processing",
        (
            "channel_tools",
            "duplicate_finder",
            "ml_denoiser",
            "restoration",
            "stem_separator",
        ),
    ),
    (
        "Organise & File Handling",
        ("audio_joiner", "file_reorganizer", "track_splitter"),
    ),
    ("Plugins", ("example_tool",)),
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


def _captions(tab: _Tab) -> list[tk.Label]:
    """The group captions, in render order."""
    return [
        child
        for child in _grid_host(tab).winfo_children()
        if isinstance(child, GroupCaption)
    ]


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
    """Nineteen captioned cards fill two columns, not one row each."""

    def test_one_cell_per_registry_card(self, tab) -> None:
        assert len(_cells(tab)) == len(_UTILITY_IDS)

    def test_host_has_two_weighted_columns(self, tab) -> None:
        host = _grid_host(tab)
        for column in range(utilities_window._CARD_COLUMNS):
            assert host.columnconfigure(column)["weight"] == 1

    def test_cards_fill_columns_left_to_right(self, tab) -> None:
        first, second, third = (_cell_at(tab, index) for index in range(3))
        top = first.grid_info()["row"]

        assert first.grid_info()["column"] == 0
        assert (second.grid_info()["row"], second.grid_info()["column"]) == (top, 1)
        assert (third.grid_info()["row"], third.grid_info()["column"]) == (top + 1, 0)

    def test_last_card_lands_on_the_expected_row(self, tab) -> None:
        """A one-column stack would need one row per card."""
        expected_rows = sum(
            1 + math.ceil(len(ids) / utilities_window._CARD_COLUMNS)
            for _heading, ids in EXPECTED_GROUPS
        )
        rows = {cell.grid_info()["row"] for cell in _cells(tab)}

        assert max(rows) + 1 == expected_rows
        assert expected_rows < len(_UTILITY_IDS)


class TestGroupedSections:
    """Every card sits under a visible caption, in the frozen order."""

    def test_the_tab_order_is_the_frozen_order(self, tab) -> None:
        assert _UTILITY_IDS == EXPECTED_UTILITY_ORDER

    def test_every_group_renders_one_caption_in_order(self, tab) -> None:
        assert [caption.cget("text") for caption in _captions(tab)] == [
            heading.upper() for heading, _ids in EXPECTED_GROUPS
        ]

    def test_each_caption_spans_both_columns_from_the_left_edge(self, tab) -> None:
        captions = _captions(tab)

        assert len(captions) == len(EXPECTED_GROUPS)
        for caption in captions:
            assert caption.grid_info()["column"] == 0
            assert caption.grid_info()["columnspan"] == utilities_window._CARD_COLUMNS

    def test_each_caption_sits_directly_above_its_group(self, tab) -> None:
        """Caption, then its cards: nothing may sit between them."""
        items = list(_grid_host(tab).winfo_children())
        cursor = 0
        for heading, ids in EXPECTED_GROUPS:
            caption = items[cursor]
            assert isinstance(caption, GroupCaption)
            assert caption.cget("text") == heading.upper()
            for offset, tool_id in enumerate(ids):
                cell = items[cursor + 1 + offset]
                assert cell is _cell_at(tab, _UTILITY_IDS.index(tool_id))
            cursor += 1 + len(ids)

    def test_the_first_card_of_a_group_starts_a_fresh_row(self, tab) -> None:
        for heading, ids in EXPECTED_GROUPS:
            caption = next(
                c for c in _captions(tab) if c.cget("text") == heading.upper()
            )
            first = _cell_at(tab, _UTILITY_IDS.index(ids[0]))

            assert first.grid_info()["column"] == 0
            assert first.grid_info()["row"] == caption.grid_info()["row"] + 1

    def test_the_plugin_group_renders_last(self, tab) -> None:
        assert _captions(tab)[-1].cget("text") == "PLUGINS"
        assert _UTILITY_IDS[-1] == "example_tool"


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
        top = first.grid_info()["row"]
        assert (second.grid_info()["row"], second.grid_info()["column"]) == (top + 1, 0)
        assert (third.grid_info()["row"], third.grid_info()["column"]) == (top + 1, 1)

    def test_collapsing_restores_the_pairing(self, tab) -> None:
        first, second = (_cell_at(tab, index) for index in range(2))
        settings = _expand_button(first)

        settings.invoke()
        tab.frame.update_idletasks()
        settings.invoke()
        tab.frame.update_idletasks()

        top = first.grid_info()["row"]
        assert first.grid_info()["columnspan"] == 1
        assert (second.grid_info()["row"], second.grid_info()["column"]) == (top, 1)

    def test_a_right_column_card_opens_across_the_window(self, tab) -> None:
        """L-01: a card opened from the right column spans like the left one.

        A spanning cell gridded at column 1 claims columns 1 and 2, and column
        2 is an implicit third column nothing weights, so the card kept the
        right half - measured as 274 px of a 548 px host before the fix.
        Asserting the rendered width (not only the span) is what catches that.
        """
        right = _cell_at(tab, 1)
        host = _grid_host(tab)

        _expand_button(right).invoke()
        tab.frame.update_idletasks()

        assert right.grid_info()["column"] == 0
        assert right.grid_info()["columnspan"] == utilities_window._CARD_COLUMNS
        assert host.winfo_width() > 0, "no rendered geometry to measure"
        assert right.winfo_x() == 0
        assert right.winfo_width() == host.winfo_width()

    def test_a_left_column_card_opens_across_the_window(self, tab) -> None:
        """Counter-case for L-01: the left column's numbers must not move."""
        left = _cell_at(tab, 0)
        host = _grid_host(tab)

        _expand_button(left).invoke()
        tab.frame.update_idletasks()

        assert left.grid_info()["column"] == 0
        assert left.grid_info()["columnspan"] == utilities_window._CARD_COLUMNS
        assert host.winfo_width() > 0, "no rendered geometry to measure"
        assert left.winfo_x() == 0
        assert left.winfo_width() == host.winfo_width()

    def test_the_cards_after_a_right_column_card_reflow(self, tab) -> None:
        """The wrapped card takes a fresh row and the pair behind it follows."""
        # Four cards from one group: the pair behind must share a row without
        # the next group's caption forcing a break between them.
        first, second, third, fourth = (_cell_at(tab, index) for index in range(3, 7))
        top = first.grid_info()["row"]

        _expand_button(second).invoke()
        tab.frame.update_idletasks()

        assert (first.grid_info()["row"], first.grid_info()["column"]) == (top, 0)
        assert (second.grid_info()["row"], second.grid_info()["column"]) == (top + 1, 0)
        assert (third.grid_info()["row"], third.grid_info()["column"]) == (top + 2, 0)
        assert (fourth.grid_info()["row"], fourth.grid_info()["column"]) == (top + 2, 1)

    def test_collapsing_a_right_column_card_restores_the_pairing(self, tab) -> None:
        """Collapsing the right card pairs the first row again, as the left does."""
        first, second = (_cell_at(tab, index) for index in range(2))
        settings = _expand_button(second)

        settings.invoke()
        tab.frame.update_idletasks()
        settings.invoke()
        tab.frame.update_idletasks()

        top = first.grid_info()["row"]
        assert second.grid_info()["columnspan"] == 1
        assert (first.grid_info()["row"], first.grid_info()["column"]) == (top, 0)
        assert (second.grid_info()["row"], second.grid_info()["column"]) == (top, 1)

    def test_two_cards_open_at_once_still_span(self, tab) -> None:
        """Expansion is per card: opening a second one does not narrow the first."""
        first, second = (_cell_at(tab, index) for index in range(2))

        _expand_button(first).invoke()
        tab.frame.update_idletasks()
        _expand_button(second).invoke()
        tab.frame.update_idletasks()

        assert first.grid_info()["columnspan"] == utilities_window._CARD_COLUMNS
        assert second.grid_info()["columnspan"] == utilities_window._CARD_COLUMNS
        assert first.grid_info()["column"] == 0
        assert second.grid_info()["column"] == 0
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


class TestPluginCards:
    """A plugin tool always reaches a card, and never breaks the tab.

    Three shapes matter: the plugin ships its own builder (the shipped example
    does), it ships none (the generic card renders), and its builder raises
    (the generic card renders and the tab survives).  Without the fallback the
    tab logs ``No card UI for tool``, drops the cell and the plugin becomes
    unreachable — the silent-degradation class this tab has shipped before.
    """

    @staticmethod
    def _texts(widget: tk.Misc) -> list[str]:
        """Return every ``text`` a widget or its descendants carry."""
        found: list[str] = []
        text = widget.cget("text") if "text" in widget.keys() else None
        if isinstance(text, str):
            found.append(text)
        for child in widget.winfo_children():
            found.extend(TestPluginCards._texts(child))
        return found

    def test_the_example_plugin_renders_its_own_card(self, root: tk.Misc) -> None:
        frame = tk.Frame(root)
        state = AppState(root)
        try:
            utilities_window._build_card("example_tool", frame, state)

            texts = self._texts(frame)
        finally:
            frame.destroy()

        assert any("Example Tool" in text for text in texts)
        assert any("Plugin card:" in text for text in texts)
        assert not any("Plugin card (generic)" in text for text in texts), (
            "the example plugin declares a ui entry, so the generic card must "
            "not render"
        )

    def test_a_plugin_without_a_ui_entry_gets_the_generic_card(
        self, root: tk.Misc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manifest = ToolManifest(
            id="generic_tool",
            name="Generic Plugin Tool",
            category="utility",
            pyw_filename="plugins/demo/Demo.pyw",
            description="A plugin with no card of its own",
            plugin=True,
            origin="/plugins/demo",
        )
        registry = MagicMock()
        registry.get.return_value = manifest
        monkeypatch.setattr(utilities_window, "get_registry", lambda: registry)
        frame = tk.Frame(root)
        state = AppState(root)
        state.module_toggles[manifest.id] = tk.BooleanVar(root, value=False)
        try:
            utilities_window._build_card(manifest.id, frame, state)

            texts = self._texts(frame)
        finally:
            frame.destroy()

        assert any("Generic Plugin Tool" in text for text in texts)
        assert any("Plugin card (generic)" in text for text in texts)

    def test_a_failing_plugin_card_falls_back_to_the_generic_card(
        self, root: tk.Misc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manifest = ToolManifest(
            id="broken_ui_tool",
            name="Broken UI Tool",
            category="utility",
            pyw_filename="plugins/demo/Demo.pyw",
            plugin=True,
            origin="/plugins/demo",
            ui_entry="demo.ui:build",
        )
        registry = MagicMock()
        registry.get.return_value = manifest

        class _Plugins:
            def resolve(self, entry: str) -> object:
                raise PluginError("boom")

        monkeypatch.setattr(utilities_window, "get_registry", lambda: registry)
        monkeypatch.setattr(utilities_window, "get_plugins", lambda: _Plugins())
        frame = tk.Frame(root)
        state = AppState(root)
        state.module_toggles[manifest.id] = tk.BooleanVar(root, value=False)
        try:
            utilities_window._build_card(manifest.id, frame, state)

            texts = self._texts(frame)
        finally:
            frame.destroy()

        assert any("Plugin card (generic)" in text for text in texts)
