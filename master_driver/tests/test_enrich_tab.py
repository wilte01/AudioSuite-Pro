"""Tests for ``master_driver.ui.enrich_tab``'s grouping.

The Enrich tab is a single-column stack of collapsible panels, one full-width
caption per group.  The groups are contiguous runs of the enrich order, so
these tests freeze three things together: the cards that render, the captions
and their membership, and the fact that grouping did not reorder the run the
tab's LAUNCH button hands to a sequential batch.

Changed in 2.6.0: initial version, with the Enrich tab's grouping
(PLAN_2026-11-08_enrich_card_grouping.md).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest

from audio_suite_shared.tool_plugin import get_registry
from master_driver.state.app_state import AppState
from master_driver.ui import enrich_tab
from master_driver.ui.group_caption import GroupCaption

#: The Enrich tab's order, frozen.  It is the display order *and* the
#: sequential batch order, and the dependency-vetted one: Tempo Analyzer reads
#: the BPM tag BPM Analyzer writes.
EXPECTED_ENRICH_ORDER: tuple[str, ...] = (
    "scrubber",
    "fingerprinter",
    "replaygain",
    "album_genre",
    "genre_sync",
    "bpm",
    "tempo",
    "key",
    "mood_analyzer",
    "art",
    "lyrics_manager",
)

#: The captions, in render order, with the ids each one introduces.
EXPECTED_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Tag Cleanup", ("scrubber",)),
    ("Identification", ("fingerprinter",)),
    ("Loudness & Genre", ("replaygain", "album_genre", "genre_sync")),
    ("Analysis", ("bpm", "tempo", "key", "mood_analyzer")),
    ("Artwork & Lyrics", ("art", "lyrics_manager")),
)


@dataclass
class _Tab:
    """One built Enrich tab, with the pieces the tests reach into."""

    frame: tk.Frame
    state: AppState
    run_button: tk.Button


@pytest.fixture()
def tab(root: tk.Misc) -> Iterator[_Tab]:
    frame = tk.Frame(root)
    state = AppState()
    run_button = enrich_tab.build(frame, state, on_run=lambda: None)
    frame.update_idletasks()
    try:
        yield _Tab(frame=frame, state=state, run_button=run_button)
    finally:
        frame.destroy()


def _find(widget: tk.Misc, kind: type) -> list[Any]:
    found: list[Any] = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found.extend(_find(child, kind))
    return found


def _scroll_frame(tab: _Tab) -> tk.Frame:
    canvases = _find(tab.frame, tk.Canvas)
    assert len(canvases) == 1
    children = canvases[0].winfo_children()
    assert len(children) == 1
    scroll_frame: tk.Frame = children[0]
    return scroll_frame


def _captions(tab: _Tab) -> list[GroupCaption]:
    """The group captions, in render order."""
    captions: list[GroupCaption] = [
        child
        for child in _scroll_frame(tab).winfo_children()
        if isinstance(child, GroupCaption)
    ]
    return captions


def _card_count(tab: _Tab) -> int:
    """Frames in the scroll area that are not the LAUNCH button's container."""
    frames = [
        child
        for child in _scroll_frame(tab).winfo_children()
        if isinstance(child, tk.Frame)
    ]
    launch_holder = tab.run_button.master
    return len([frame for frame in frames if frame is not launch_holder])


class TestGroupedSections:
    """Every card sits under a visible caption, in the frozen order."""

    def test_the_tab_order_is_the_frozen_order(self, tab) -> None:
        ids = tuple(
            manifest.id for manifest in get_registry().driver_by_category("enrich")
        )

        assert ids == EXPECTED_ENRICH_ORDER

    def test_one_card_per_enrich_tool(self, tab) -> None:
        assert _card_count(tab) == len(EXPECTED_ENRICH_ORDER)

    def test_every_group_renders_one_caption_in_order(self, tab) -> None:
        assert [caption.cget("text") for caption in _captions(tab)] == [
            heading.upper() for heading, _ids in EXPECTED_GROUPS
        ]

    def test_captions_span_the_full_width(self, tab) -> None:
        for caption in _captions(tab):
            assert caption.pack_info()["fill"] == "x"

    def test_each_caption_takes_its_own_run_of_cards(self, tab) -> None:
        """Caption, its cards, next caption: nothing may sit between them."""
        runs: list[int] = []
        current: int | None = None
        for child in _scroll_frame(tab).winfo_children():
            if isinstance(child, GroupCaption):
                if current is not None:
                    runs.append(current)
                current = 0
            elif isinstance(child, tk.Frame) and child is not tab.run_button.master:
                assert current is not None, "a card rendered before any caption"
                current += 1
        if current is not None:
            runs.append(current)

        assert runs == [len(ids) for _heading, ids in EXPECTED_GROUPS]

    def test_the_launch_button_follows_the_last_group(self, tab) -> None:
        children = _scroll_frame(tab).winfo_children()
        launch_index = children.index(tab.run_button.master)

        assert tab.run_button.cget("text") == "LAUNCH ENRICH PROCESS"
        assert launch_index > children.index(_captions(tab)[-1])


class TestCaptionDropping:
    """A caption over nothing would read as a broken group."""

    def test_a_group_with_no_built_card_loses_its_caption(
        self, root: tk.Misc, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real_builder = enrich_tab._build_card

        def _skip_the_scrubber(tool_id: str, parent: tk.Frame, state: AppState) -> bool:
            if tool_id == "scrubber":
                return False
            return real_builder(tool_id, parent, state)

        monkeypatch.setattr(enrich_tab, "_build_card", _skip_the_scrubber)
        frame = tk.Frame(root)
        try:
            run_button = enrich_tab.build(frame, AppState(), on_run=lambda: None)
            frame.update_idletasks()
            built = _Tab(frame=frame, state=AppState(), run_button=run_button)
            texts = [caption.cget("text") for caption in _captions(built)]

            assert "TAG CLEANUP" not in texts
            assert texts == [
                heading.upper()
                for heading, _ids in EXPECTED_GROUPS
                if heading != "Tag Cleanup"
            ]
        finally:
            frame.destroy()
