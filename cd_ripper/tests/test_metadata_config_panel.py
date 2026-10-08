"""
Tests for cd_ripper.ui.metadata_config_panel — album metadata and track editing.

Real ``Toplevel`` off the shared hidden root for widget-level behaviour
(Treeview rows, bbox-driven double-click editor), per the AGENTS Tk-testing
rules; ``object.__new__`` + ``MagicMock`` for the early-return branches that
must not touch Tk at all.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any
from unittest.mock import MagicMock

import pytest

from cd_ripper.ui.metadata_config_panel import MetadataConfigPanel


def _track(
    number: int, title: str = "", artist: str = "", duration: float = 0.0
) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "artist": artist,
        "album": "",
        "year": "",
        "genre": "",
        "duration": duration,
    }


@pytest.fixture()
def panel_root(root: tk.Tk) -> Any:
    top = tk.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


def _row_values(panel: MetadataConfigPanel, iid: str) -> tuple[str, ...]:
    values = panel._tree.item(iid, "values")
    return tuple(str(v) for v in values)


class TestConstruction:
    def test_frame_and_treeview_exist(self, panel_root: tk.Toplevel) -> None:
        panel = MetadataConfigPanel(panel_root)
        assert panel.frame is not None
        assert panel._tree.get_children() == ()

    def test_treeview_has_expected_columns(self, panel_root: tk.Toplevel) -> None:
        panel = MetadataConfigPanel(panel_root)
        assert panel._tree["columns"] == ("#", "Title", "Artist", "Duration")


class TestPopulateAlbumFields:
    def test_fields_take_values_from_first_track(self, panel_root: tk.Toplevel) -> None:
        panel = MetadataConfigPanel(panel_root)
        tracks = [
            {
                "number": 1,
                "title": "One",
                "artist": "Artist A",
                "album": "Album X",
                "year": "1999",
                "genre": "Rock",
                "duration": 10.0,
            },
            {
                "number": 2,
                "title": "Two",
                "artist": "Artist B",
                "album": "Album Y",
                "year": "2001",
                "genre": "Jazz",
                "duration": 20.0,
            },
        ]
        panel.populate_album_fields(tracks)
        assert panel._album_var.get() == "Album X"
        assert panel._artist_var.get() == "Artist A"
        assert panel._year_var.get() == "1999"
        assert panel._genre_var.get() == "Rock"

    def test_missing_keys_render_empty_strings(self, panel_root: tk.Toplevel) -> None:
        panel = MetadataConfigPanel(panel_root)
        panel.populate_album_fields([{"number": 1}])
        assert panel._album_var.get() == ""
        assert panel._artist_var.get() == ""
        assert panel._year_var.get() == ""
        assert panel._genre_var.get() == ""

    def test_empty_track_list_leaves_fields_untouched(
        self, panel_root: tk.Toplevel
    ) -> None:
        panel = MetadataConfigPanel(panel_root)
        panel._album_var.set("KeepMe")
        panel.populate_album_fields([])
        assert panel._album_var.get() == "KeepMe"


class TestPopulateTracks:
    def test_rows_written_with_formatted_duration(
        self, panel_root: tk.Toplevel
    ) -> None:
        panel = MetadataConfigPanel(panel_root)
        tracks = [
            _track(1, "First", "Alpha", 125.0),
            _track(2, "Second", "Beta", 0.0),
        ]
        panel.populate_tracks(tracks)
        assert panel._tree.get_children() == ("1", "2")
        assert _row_values(panel, "1") == ("1", "First", "Alpha", "2:05")
        assert _row_values(panel, "2") == ("2", "Second", "Beta", "--:--")

    def test_second_populate_replaces_existing_rows(
        self, panel_root: tk.Toplevel
    ) -> None:
        panel = MetadataConfigPanel(panel_root)
        panel.populate_tracks([_track(1, "Old")])
        panel.populate_tracks([_track(7, "New")])
        assert panel._tree.get_children() == ("7",)


class TestApplyAlbumToTracks:
    def test_album_fields_written_into_every_track(
        self, panel_root: tk.Toplevel
    ) -> None:
        panel = MetadataConfigPanel(panel_root)
        tracks = [_track(1, "One"), _track(2, "Two", artist="Existing")]
        panel.populate_tracks(tracks)
        panel._album_var.set("Greatest Hits")
        panel._artist_var.set("Compilation Artist")
        panel._year_var.set("2020")
        panel._genre_var.set("Various")

        panel.apply_album_to_tracks()

        for t in tracks:
            assert t["album"] == "Greatest Hits"
            assert t["year"] == "2020"
            assert t["genre"] == "Various"
            assert t["artist"] == "Compilation Artist"
        assert _row_values(panel, "1")[1] == "One"
        assert _row_values(panel, "1")[2] == "Compilation Artist"

    def test_blank_artist_leaves_existing_artist_untouched(
        self, panel_root: tk.Toplevel
    ) -> None:
        panel = MetadataConfigPanel(panel_root)
        tracks = [_track(1, "One", artist="Keep Me")]
        panel.populate_tracks(tracks)
        panel._album_var.set("Album")
        panel._artist_var.set("")

        panel.apply_album_to_tracks()

        assert tracks[0]["artist"] == "Keep Me"
        assert _row_values(panel, "1")[2] == "Keep Me"


class TestTrackDoubleClick:
    """The double-click editor must open on Title/Artist and persist edits."""

    def _open_panel(self, root: tk.Tk) -> tuple[tk.Toplevel, MetadataConfigPanel]:
        top = tk.Toplevel(root)
        panel = MetadataConfigPanel(top)
        panel.frame.pack(fill="both", expand=True)
        panel.populate_tracks(
            [_track(1, "First", "Alpha", 125.0), _track(2, "Second", "Beta")]
        )
        # bbox() needs a mapped widget, and on Windows only the first
        # Toplevel of a session is activated automatically - without
        # focus_force() later windows refuse entry focus and the popup's
        # key bindings never fire.
        top.deiconify()
        top.focus_force()
        top.update()
        return top, panel

    def _popup_entries(self, panel: MetadataConfigPanel) -> list[tk.Entry]:
        return [w for w in panel._tree.winfo_children() if isinstance(w, tk.Entry)]

    def _click(self, panel: MetadataConfigPanel, iid: str, col: str) -> None:
        bbox = panel._tree.bbox(iid, col)
        assert bbox, f"tree cell {iid}/{col} not mapped - cannot drive a real click"
        x, y, w, h = bbox
        # Tk's identify_column window is offset a few pixels from bbox()'s
        # left edge, so click the cell centre where the two agree.
        panel._on_track_double_click(MagicMock(x=x + w // 2, y=y + h // 2))

    def test_title_edit_round_trips_into_track_and_row(self, root: tk.Tk) -> None:
        top, panel = self._open_panel(root)
        try:
            top.update_idletasks()
            self._click(panel, "1", "#2")
            popups = self._popup_entries(panel)
            assert len(popups) == 1
            popup = popups[0]
            assert popup.get() == "First"

            popup.delete(0, "end")
            popup.insert(0, "Renamed")
            # Tk routes key events through the focus widget; event_generate
            # is a no-op on the binding until focus is set and processed.
            popup.focus_set()
            top.update()
            popup.event_generate("<Return>")

            assert panel._tracks[0]["title"] == "Renamed"
            assert _row_values(panel, "1")[1] == "Renamed"
            assert self._popup_entries(panel) == []
        finally:
            top.destroy()

    def test_artist_edit_round_trips_into_track_and_row(self, root: tk.Tk) -> None:
        top, panel = self._open_panel(root)
        try:
            top.update_idletasks()
            self._click(panel, "2", "#3")
            popups = self._popup_entries(panel)
            assert len(popups) == 1
            popup = popups[0]
            assert popup.get() == "Beta"

            popup.delete(0, "end")
            popup.insert(0, "Gamma")
            popup.focus_set()
            top.update()
            popup.event_generate("<Return>")

            assert panel._tracks[1]["artist"] == "Gamma"
            assert _row_values(panel, "2")[2] == "Gamma"
        finally:
            top.destroy()

    def test_escape_discards_the_edit(self, root: tk.Tk) -> None:
        top, panel = self._open_panel(root)
        try:
            top.update_idletasks()
            self._click(panel, "1", "#2")
            popup = self._popup_entries(panel)[0]
            popup.delete(0, "end")
            popup.insert(0, "Doomed")
            popup.focus_set()
            top.update()
            popup.event_generate("<Escape>")

            assert panel._tracks[0]["title"] == "First"
            popup.update_idletasks()
            assert not popup.winfo_exists()
        finally:
            top.destroy()

    def test_non_editable_column_opens_no_editor(self, root: tk.Tk) -> None:
        top, panel = self._open_panel(root)
        try:
            top.update_idletasks()
            for col in ("#1", "#4"):
                self._click(panel, "1", col)
                assert self._popup_entries(panel) == []
        finally:
            top.destroy()

    @staticmethod
    def _shell_panel(tree: MagicMock) -> MetadataConfigPanel:
        panel = object.__new__(MetadataConfigPanel)
        panel._tree = tree
        panel._tracks = [_track(1, "First")]
        return panel

    def test_empty_row_hit_opens_no_editor(self) -> None:
        tree = MagicMock()
        tree.identify_row.return_value = ""
        panel = self._shell_panel(tree)
        panel._on_track_double_click(MagicMock(x=1, y=1))
        tree.identify_row.assert_called_once_with(1)
        # The empty-row check runs before the editor gate: bbox (which
        # guards Entry creation) is never reached and int("") never executes.
        tree.bbox.assert_not_called()

    def test_unknown_track_number_opens_no_editor(self) -> None:
        tree = MagicMock()
        tree.identify_row.return_value = "99"
        tree.identify_column.return_value = "#2"
        panel = self._shell_panel(tree)
        panel._on_track_double_click(MagicMock(x=1, y=1))
        tree.bbox.assert_not_called()

    def test_unmapped_cell_bbox_opens_no_editor(self) -> None:
        tree = MagicMock()
        tree.identify_row.return_value = "1"
        tree.identify_column.return_value = "#2"
        tree.bbox.return_value = ""
        panel = self._shell_panel(tree)
        panel._on_track_double_click(MagicMock(x=1, y=1))
        assert panel._tracks[0]["title"] == "First"
