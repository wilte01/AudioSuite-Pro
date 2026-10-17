"""
Tests for cd_ripper.ui.results_tab — result rows, folder/eject actions,
double-click reveal.

Real Tk widgets off the shared hidden root for ``refresh``; shell panels
(``object.__new__`` + MagicMock tree) for the early-return branches of
``_on_row_double``. Platform branches are driven by patching ``os.name``
(repo precedent: test_disc_core.py), with ``startfile``/``CREATE_NO_WINDOW``
created for cross-platform CI.

Changed in 1.2.0: covers the confidence wording and the manual
"Re-rip flagged tracks" action.
"""

from __future__ import annotations

import tkinter as tk
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cd_ripper.ui import results_tab as results_mod
from cd_ripper.ui.results_tab import ResultsTab


def _result(
    number: int,
    *,
    success: bool = True,
    error: str = "",
    path: str = "",
) -> dict[str, Any]:
    return {"number": number, "path": path, "success": success, "error": error}


@pytest.fixture()
def tab(root: tk.Tk) -> Any:
    t = ResultsTab(root, {})
    t.frame.pack(fill="both", expand=True)
    root.update_idletasks()
    try:
        yield t
    finally:
        t.frame.destroy()


class TestRefresh:
    def test_rows_summary_and_tags(self, tab: ResultsTab) -> None:
        tab.state["tracks"] = [{"number": 1, "title": "First"}]
        tab.state["rip_results"] = [
            _result(2, success=False, error="Read failed"),
            _result(1, path="C:/out/first.flac"),
        ]

        tab.refresh()

        assert tab._tree.get_children() == ("1", "2")
        assert tab._tree.item("1", "values") == (
            "1",
            "First",
            "first.flac",
            "✓  OK",
        )
        assert tab._tree.item("1", "tags") == ("ok",)
        assert tab._tree.item("2", "tags") == ("fail",)
        assert tab._summary_lbl.cget("text") == (
            "Rip complete  —  1 succeeded,  1 failed"
        )
        assert tab._summary_lbl.cget("fg") == "#cc3333"

    def test_all_ok_summary_uses_main_colour(self, tab: ResultsTab) -> None:
        tab.state["rip_results"] = [_result(1, path="/tmp/a.flac")]

        tab.refresh()

        assert tab._summary_lbl.cget("text") == (
            "Rip complete  —  1 succeeded,  0 failed"
        )
        assert tab._summary_lbl.cget("fg") != "#cc3333"

    def test_verification_statuses_aggregate_into_summary(
        self, tab: ResultsTab
    ) -> None:
        tab.state["rip_results"] = [
            _result(1, error="AR verified"),
            _result(2, error="AR verified"),
            _result(3, error="No AccurateRip entry"),
        ]

        tab.refresh()

        assert tab._summary_lbl.cget("text") == (
            "Rip complete  —  3 succeeded "
            "(2 AR verified, 1 No AccurateRip entry),  0 failed"
        )
        assert tab._tree.item("1", "values")[3] == "✓  AR verified"

    def test_track_title_and_path_fallbacks(self, tab: ResultsTab) -> None:
        tab.state["rip_results"] = [_result(9, path="")]

        tab.refresh()

        values = tab._tree.item("9", "values")
        assert values[1] == "Track 09"
        assert values[2] == "—"

    def test_refresh_clears_previous_rows(self, tab: ResultsTab) -> None:
        tab.state["rip_results"] = [_result(1), _result(2)]
        tab.refresh()
        tab.state["rip_results"] = [_result(3)]

        tab.refresh()

        assert tab._tree.get_children() == ("3",)


class TestOpenFolder:
    def test_empty_out_dir_is_a_no_op(self, tab: ResultsTab) -> None:
        with (
            patch.object(results_mod.os, "startfile", create=True) as startfile,
            patch.object(results_mod, "run_secure_subprocess") as secure,
        ):
            tab._open_folder()
        startfile.assert_not_called()
        secure.assert_not_called()

    def test_missing_directory_is_a_no_op(self, tab: ResultsTab, tmp_path: Any) -> None:
        tab.state["out_dir"] = str(tmp_path / "does-not-exist")
        with (
            patch.object(results_mod.os, "startfile", create=True) as startfile,
            patch.object(results_mod, "run_secure_subprocess") as secure,
        ):
            tab._open_folder()
        startfile.assert_not_called()
        secure.assert_not_called()

    def test_windows_path_opens_with_startfile(
        self, tab: ResultsTab, tmp_path: Any
    ) -> None:
        tab.state["out_dir"] = str(tmp_path)
        with (
            patch.object(results_mod.os, "name", "nt"),
            patch.object(results_mod.os, "startfile", create=True) as startfile,
        ):
            tab._open_folder()
        startfile.assert_called_once_with(str(tmp_path))

    def test_posix_path_opens_with_xdg_open(
        self, tab: ResultsTab, tmp_path: Any
    ) -> None:
        tab.state["out_dir"] = str(tmp_path)
        with (
            patch.object(results_mod.os, "name", "posix"),
            patch.object(results_mod, "run_secure_subprocess") as secure,
        ):
            tab._open_folder()
        secure.assert_called_once_with(
            "xdg-open", [str(tmp_path)], capture_output=True, check=False
        )


class TestEject:
    @staticmethod
    def _shell_tab(state: dict[str, Any]) -> ResultsTab:
        t = object.__new__(ResultsTab)
        t.state = state
        return t

    def test_no_drive_is_a_no_op(self) -> None:
        t = self._shell_tab({})
        with patch.object(results_mod.subprocess, "Popen") as popen:
            t._eject()
        popen.assert_not_called()

    def test_windows_drive_ejects_via_powershell(self) -> None:
        t = self._shell_tab({"drive": "D:\\"})
        with (
            patch.object(results_mod.os, "name", "nt"),
            patch.object(results_mod.subprocess, "Popen") as popen,
            patch.object(results_mod.subprocess, "CREATE_NO_WINDOW", 0, create=True),
        ):
            t._eject()
        args = popen.call_args.args[0]
        assert args[0] == "powershell"
        assert '"D:' in args[2]

    def test_posix_drive_ejects_via_eject_binary(self) -> None:
        t = self._shell_tab({"drive": "/dev/sr0"})
        with (
            patch.object(results_mod.os, "name", "posix"),
            patch.object(results_mod.subprocess, "Popen") as popen,
        ):
            t._eject()
        popen.assert_called_once_with(["eject", "/dev/sr0"])


class TestRowDouble:
    @staticmethod
    def _shell_tab(tree: MagicMock, state: dict[str, Any]) -> ResultsTab:
        t = object.__new__(ResultsTab)
        t._tree = tree
        t.state = state
        return t

    def test_blank_row_is_a_no_op(self) -> None:
        tree = MagicMock()
        tree.identify_row.return_value = ""
        t = self._shell_tab(tree, {})
        t._on_row_double(MagicMock(y=5))
        tree.identify_row.assert_called_once_with(5)

    def test_unknown_row_number_is_a_no_op(self) -> None:
        tree = MagicMock()
        tree.identify_row.return_value = "42"
        t = self._shell_tab(tree, {"rip_results": [_result(1)]})
        with patch.object(results_mod.subprocess, "Popen") as popen:
            t._on_row_double(MagicMock(y=5))
        popen.assert_not_called()

    def test_missing_file_is_a_no_op(self, tmp_path: Any) -> None:
        tree = MagicMock()
        tree.identify_row.return_value = "1"
        state = {"rip_results": [_result(1, path=str(tmp_path / "gone.flac"))]}
        t = self._shell_tab(tree, state)
        with patch.object(results_mod.subprocess, "Popen") as popen:
            t._on_row_double(MagicMock(y=5))
        popen.assert_not_called()

    def test_windows_row_reveals_file_in_explorer(self, tmp_path: Any) -> None:
        target = tmp_path / "track.flac"
        target.write_bytes(b"x")
        tree = MagicMock()
        tree.identify_row.return_value = "1"
        state = {"rip_results": [_result(1, path=str(target))]}
        t = self._shell_tab(tree, state)
        with (
            patch.object(results_mod.os, "name", "nt"),
            patch.object(results_mod.subprocess, "Popen") as popen,
            patch.object(results_mod.subprocess, "CREATE_NO_WINDOW", 0, create=True),
        ):
            t._on_row_double(MagicMock(y=5))
        popen.assert_called_once_with(
            ["explorer", f"/select,{target}"],
            creationflags=0,
        )

    def test_posix_row_opens_file_directory(self, tmp_path: Any) -> None:
        target = tmp_path / "track.flac"
        target.write_bytes(b"x")
        tree = MagicMock()
        tree.identify_row.return_value = "1"
        state = {"rip_results": [_result(1, path=str(target))]}
        t = self._shell_tab(tree, state)
        with (
            patch.object(results_mod.os, "name", "posix"),
            patch.object(results_mod, "run_secure_subprocess") as secure,
        ):
            t._on_row_double(MagicMock(y=5))
        secure.assert_called_once_with(
            "xdg-open",
            [str(tmp_path)],
            capture_output=True,
            check=False,
        )


class TestBuild:
    @staticmethod
    def _buttons(tab: ResultsTab) -> list[tk.Button]:
        found: list[tk.Button] = []
        stack: list[Any] = [tab.frame]
        while stack:
            widget = stack.pop()
            for w in widget.winfo_children():
                if isinstance(w, tk.Button):
                    found.append(w)
                stack.append(w)
        return found

    def test_open_folder_button_is_wired_to_the_handler(
        self, tab: ResultsTab, tmp_path: Any
    ) -> None:
        tab.state["out_dir"] = str(tmp_path)
        button = next(
            b for b in self._buttons(tab) if "Open Output Folder" in b.cget("text")
        )
        with (
            patch.object(results_mod.os, "name", "nt"),
            patch.object(results_mod.os, "startfile", create=True) as startfile,
        ):
            button.invoke()
        startfile.assert_called_once_with(str(tmp_path))

    def test_eject_button_is_wired_to_the_handler(self, tab: ResultsTab) -> None:
        tab.state["drive"] = "D:"
        button = next(b for b in self._buttons(tab) if "Eject Disc" in b.cget("text"))
        with (
            patch.object(results_mod.os, "name", "nt"),
            patch.object(results_mod.subprocess, "Popen") as popen,
            patch.object(results_mod.subprocess, "CREATE_NO_WINDOW", 0, create=True),
        ):
            button.invoke()
        assert popen.call_count == 1

    def test_row_double_binding_attached(self, tab: ResultsTab) -> None:
        assert tab._tree.bind("<Double-1>")

    def test_refresh_reports_zero_results(self, tab: ResultsTab) -> None:
        tab.refresh()
        assert tab._tree.get_children() == ()
        assert tab._summary_lbl.cget("text") == (
            "Rip complete  —  0 succeeded,  0 failed"
        )


class TestVerificationLabels:
    """D30: the row and the summary show the EAC wording, confidence included."""

    def test_confidence_is_visible_in_the_row_and_summary(
        self, tab: ResultsTab
    ) -> None:
        tab.state["rip_results"] = [
            _result(1, error="Accurate (confidence 12)"),
            _result(2, error="Accurate (confidence 12)"),
            _result(3, error="Not accurate"),
        ]

        tab.refresh()

        assert tab._tree.item("1", "values")[3] == "✓  Accurate (confidence 12)"
        assert tab._summary_lbl.cget("text") == (
            "Rip complete  —  3 succeeded "
            "(2 Accurate (confidence 12), 1 Not accurate),  0 failed"
        )

    def test_every_outcome_wording_reaches_a_row(self, tab: ResultsTab) -> None:
        labels = [
            "Accurate (confidence 1)",
            "Rip-twice verified",
            "Not in database",
            "Unavailable (offline)",
        ]
        tab.state["rip_results"] = [
            _result(number, error=label) for number, label in enumerate(labels, start=1)
        ]

        tab.refresh()

        shown = [tab._tree.item(str(n), "values")[3] for n in range(1, 5)]
        assert shown == [f"✓  {label}" for label in labels]


class TestReRipAction:
    """The re-rip action is manual, and only ever names flagged tracks."""

    @staticmethod
    def _buttons(tab: ResultsTab) -> list[tk.Button]:
        found: list[tk.Button] = []
        stack: list[Any] = [tab.frame]
        while stack:
            widget = stack.pop()
            for w in widget.winfo_children():
                if isinstance(w, tk.Button):
                    found.append(w)
                stack.append(w)
        return found

    def _rerip_button(self, tab: ResultsTab) -> tk.Button:
        return next(b for b in self._buttons(tab) if "Re-rip flagged" in b.cget("text"))

    def test_flagged_numbers_lists_only_failures_in_disc_order(
        self, tab: ResultsTab
    ) -> None:
        tab.state["rip_results"] = [
            _result(3, success=False, error="Read failed"),
            _result(1, path="/out/01.flac", error="Rip-twice verified"),
            _result(2, success=False, error="Not accurate: CRC not found"),
        ]
        assert tab.flagged_numbers() == [2, 3]

    def test_no_failures_leaves_the_button_disabled(self, tab: ResultsTab) -> None:
        tab.state["rip_results"] = [
            _result(1, path="/out/01.flac", error="Accurate (confidence 4)")
        ]
        tab.refresh()
        assert str(self._rerip_button(tab).cget("state")) == "disabled"

    def test_a_failure_enables_the_button(self, tab: ResultsTab) -> None:
        tab.state["on_rerip"] = MagicMock()
        tab.state["rip_results"] = [
            _result(1, path="/out/01.flac", error="Accurate (confidence 4)"),
            _result(2, success=False, error="Not accurate: CRC not found"),
        ]
        tab.refresh()
        assert str(self._rerip_button(tab).cget("state")) == "normal"

    def test_clicking_passes_the_flagged_numbers(self, tab: ResultsTab) -> None:
        callback = MagicMock()
        tab.state["on_rerip"] = callback
        tab.state["rip_results"] = [
            _result(1, success=False, error="Read failed"),
            _result(2, path="/out/02.flac", error="OK"),
            _result(3, success=False, error="Not accurate"),
        ]
        tab.refresh()

        self._rerip_button(tab).invoke()

        callback.assert_called_once_with([1, 3])

    def test_click_without_a_callback_is_a_no_op(self, tab: ResultsTab) -> None:
        tab.state["rip_results"] = [_result(1, success=False, error="Read failed")]
        tab.refresh()
        # Must not raise: an un-wired tab is a valid construction order.
        self._rerip_button(tab).invoke()

    def test_click_with_nothing_flagged_is_a_no_op(self, tab: ResultsTab) -> None:
        callback = MagicMock()
        tab.state["on_rerip"] = callback
        tab.state["rip_results"] = [_result(1, path="/out/01.flac", error="OK")]
        tab.refresh()
        self._rerip_button(tab).invoke()
        callback.assert_not_called()
