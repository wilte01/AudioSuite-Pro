"""Tests for cd_ripper.ui.rip_tab — result recording and the re-rip path.

The re-rip action is the D30 half of Item 2.2: it must re-run **only** the
flagged track numbers, and it must replace those tracks' rows rather than
appending duplicates, so the Results tab shows one row per track either way.

The frames are built off the shared hidden root (real widgets, no mainloop);
``RipSession`` is patched so no drive, ffmpeg or thread is involved.

Changed in 1.2.0: new suite for ``re_rip`` / ``_record_result``
(PLAN_feature_expansion.md D30).
"""

from __future__ import annotations

import tkinter as tk
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cd_ripper.ui import rip_tab as rip_mod
from cd_ripper.ui.rip_tab import RipTab


def _tracks(*numbers: int) -> list[dict[str, Any]]:
    return [{"number": n, "title": f"Track {n:02d}"} for n in numbers]


@pytest.fixture()
def tab(root: tk.Tk) -> Any:
    t = RipTab(
        root,
        {"tracks": _tracks(1, 2, 3), "fmt": "FLAC", "out_dir": "/out"},
        MagicMock(),
    )
    t.frame.pack(fill="both", expand=True)
    t.prepare()
    root.update_idletasks()
    try:
        yield t
    finally:
        t.frame.destroy()


class TestResultRecording:
    def test_first_result_is_appended(self, tab: RipTab) -> None:
        tab.state["rip_results"] = []
        tab._record_result(2, True, "/out/02.flac", "Rip-twice verified")
        assert tab.state["rip_results"] == [
            {
                "number": 2,
                "success": True,
                "path": "/out/02.flac",
                "error": "Rip-twice verified",
            }
        ]

    def test_second_result_for_a_track_replaces_the_first(self, tab: RipTab) -> None:
        tab.state["rip_results"] = []
        tab._record_result(2, False, "", "Read failed")
        tab._record_result(2, True, "/out/02.flac", "Accurate (confidence 9)")

        assert len(tab.state["rip_results"]) == 1
        assert tab.state["rip_results"][0]["success"] is True
        assert tab.state["rip_results"][0]["error"] == "Accurate (confidence 9)"

    def test_other_tracks_are_untouched(self, tab: RipTab) -> None:
        tab.state["rip_results"] = []
        tab._record_result(1, False, "", "Read failed")
        tab._record_result(2, True, "/out/02.flac", "Rip-twice verified")

        tab._record_result(1, True, "/out/01.flac", "Accurate (confidence 4)")

        by_number = {r["number"]: r for r in tab.state["rip_results"]}
        assert by_number[1]["success"] is True
        assert by_number[2]["success"] is True
        assert by_number[2]["error"] == "Rip-twice verified"


class TestReRip:
    def test_only_the_flagged_tracks_are_reripped(self, tab: RipTab) -> None:
        sessions: list[Any] = []

        def _fake_session(**kwargs: Any) -> MagicMock:
            session = MagicMock()
            sessions.append(kwargs)
            return session

        with patch.object(rip_mod, "RipSession", side_effect=_fake_session):
            tab.re_rip([2])

        assert len(sessions) == 1
        assert [t["number"] for t in sessions[0]["tracks"]] == [2]

    def test_flagged_order_follows_the_disc_not_the_argument(self, tab: RipTab) -> None:
        sessions: list[Any] = []

        def _fake_session(**kwargs: Any) -> MagicMock:
            sessions.append(kwargs)
            return MagicMock()

        with patch.object(rip_mod, "RipSession", side_effect=_fake_session):
            tab.re_rip([3, 1])

        assert [t["number"] for t in sessions[0]["tracks"]] == [1, 3]

    def test_unknown_numbers_start_nothing(self, tab: RipTab) -> None:
        with patch.object(rip_mod, "RipSession") as session:
            tab.re_rip([99])
        session.assert_not_called()

    def test_progress_totals_count_only_the_flaggged_tracks(self, tab: RipTab) -> None:
        with patch.object(rip_mod, "RipSession", return_value=MagicMock()):
            tab.re_rip([1, 3])
        assert tab._total == 2
        assert tab._completed == 0

    def test_existing_results_are_kept_while_reripping(self, tab: RipTab) -> None:
        tab.state["rip_results"] = [
            {"number": 1, "success": False, "path": "", "error": "Read failed"},
            {"number": 2, "success": True, "path": "/out/02.flac", "error": "OK"},
        ]
        with patch.object(rip_mod, "RipSession", return_value=MagicMock()):
            tab.re_rip([1])

        # Unlike a fresh rip, a re-rip must not clear the table: the rows that
        # are not being re-run have to keep their outcomes.
        assert [r["number"] for r in tab.state["rip_results"]] == [1, 2]

    def test_second_re_rip_is_ignored_while_running(self, tab: RipTab) -> None:
        with patch.object(rip_mod, "RipSession", return_value=MagicMock()) as session:
            tab.re_rip([1])
            tab.re_rip([2])
        assert session.call_count == 1

    def test_session_completion_clears_the_running_guard(self, tab: RipTab) -> None:
        tab.state["rip_results"] = []
        with patch.object(rip_mod, "RipSession", return_value=MagicMock()):
            tab.re_rip([1])
        assert tab._running is True

        tab.frame.after = lambda _ms, fn, *a: fn()  # type: ignore[method-assign]
        tab._on_session_done()

        assert tab._running is False

    def test_a_flagged_row_is_marked_active(self, tab: RipTab) -> None:
        row = tab._rows[1]
        with patch.object(rip_mod, "RipSession", return_value=MagicMock()):
            tab.re_rip([1])
        assert row.status_lbl.cget("text") == "Ripping…"


class TestStartClearsResults:
    def test_fresh_start_clears_previous_results(self, tab: RipTab) -> None:
        tab.state["rip_results"] = [
            {"number": 1, "success": False, "path": "", "error": "Read failed"}
        ]
        with patch.object(rip_mod, "RipSession", return_value=MagicMock()):
            tab._start()
        assert tab.state["rip_results"] == []
        assert tab._total == 3
