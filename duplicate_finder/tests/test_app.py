"""Tests for the Duplicate Finder window.

The window is an ``AnalysisTagToolApp`` on the shared three tabs, so what is
checked here is the part that is this tool's own: the completion handler's row
set, the validation a run must pass before it starts, the driver's pre-fill
routes, and -- ``TestCompletionSeam`` -- the real scan driven into the handler it
binds, asserting the report the run writes.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from duplicate_finder.core.models import DEFAULT_THRESHOLD
from duplicate_finder.ui import app as app_module
from duplicate_finder.ui.app import (
    DRY_RUN,
    LIVE_UPDATE,
    RUN_REPORT_DRY_RUN,
    RUN_REPORT_LIVE,
    DuplicateFinderApp,
)


def shell(
    *,
    mode: str = DRY_RUN,
    tmp_path: Path | None = None,
    folder: str = "",
    threshold: float = DEFAULT_THRESHOLD,
    quarantine: str = "",
) -> DuplicateFinderApp:
    """Return a window object without building any widgets.

    Args:
        mode: The run mode the Mode combobox holds.
        tmp_path: Directory for the report path; ``None`` leaves it blank.
        folder: The source folder the entry holds.
        threshold: The similarity threshold the slider holds.
        quarantine: The quarantine folder the entry holds.

    Returns:
        The shell, ready for a handler call.
    """
    app = object.__new__(DuplicateFinderApp)
    app.root = MagicMock()
    app.run_mode = MagicMock()
    app.run_mode.get.return_value = mode
    app.folder_path = MagicMock()
    app.folder_path.get.return_value = folder
    app.threshold = MagicMock()
    app.threshold.get.return_value = threshold
    app.quarantine_dir = MagicMock()
    app.quarantine_dir.get.return_value = quarantine
    app.auto_end = False
    app._summary_rows = ()
    app._log_path = str(tmp_path / "report.txt") if tmp_path is not None else ""
    app._notes = []
    app._record_run_note = MagicMock()  # type: ignore[method-assign]
    app.start_btn = MagicMock()
    app.notebook = MagicMock()
    app._tab_processing = MagicMock()
    app._tab_results = MagicMock()
    app.file_listbox = MagicMock()
    app._reset_progress_ui = MagicMock()  # type: ignore[method-assign]
    app.overall_status = MagicMock()
    return app


class TestCompletionRows:
    """What the finished run adds to the report and the Results panel."""

    def test_a_dry_run_reports_what_it_would_quarantine(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(mode=DRY_RUN, tmp_path=tmp_path)
        forwarded: list[dict[str, Any]] = []
        monkeypatch.setattr(
            app_module.AnalysisTagToolApp,
            "_on_complete",
            lambda _self, **kwargs: forwarded.append(kwargs),
        )

        app._finish_run(
            header=["h\n"],
            total=7,
            processed=7,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=["line\n"],
            groups=1,
            duplicates=3,
            quarantined=0,
        )

        assert app._summary_extras() == [
            ("Duplicate groups", "1"),
            ("Duplicate files", "3"),
            ("Files would quarantine", "0"),
            ("Without a fingerprint", "0"),
        ]

    def test_a_live_run_reports_what_it_moved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(mode=LIVE_UPDATE, tmp_path=tmp_path)
        monkeypatch.setattr(
            app_module.AnalysisTagToolApp, "_on_complete", lambda _self, **kwargs: None
        )

        app._finish_run(
            header=[],
            total=7,
            processed=7,
            skipped=1,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
            groups=1,
            duplicates=3,
            quarantined=3,
        )

        rows = dict(app._summary_extras())
        assert rows["Files quarantined"] == "3"
        assert rows["Without a fingerprint"] == "1"

    def test_the_shared_fields_reach_the_base_handler(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(tmp_path=tmp_path)
        forwarded: list[dict[str, Any]] = []
        monkeypatch.setattr(
            app_module.AnalysisTagToolApp,
            "_on_complete",
            lambda _self, **kwargs: forwarded.append(kwargs),
        )

        app._finish_run(
            header=["h\n"],
            total=4,
            processed=4,
            skipped=2,
            errors=1,
            duration_secs=2.5,
            log_entries=["a\n", "b\n"],
            groups=0,
            duplicates=0,
            quarantined=0,
            unexpected="ignored",
        )

        (payload,) = forwarded
        assert payload["header"] == ["h\n"]
        assert payload["total"] == 4
        assert payload["processed"] == 4
        assert payload["skipped"] == 2
        assert payload["errors"] == 1
        assert payload["duration_secs"] == 2.5
        assert payload["log_entries"] == ["a\n", "b\n"]
        assert payload["unexpected"] == "ignored"

    def test_one_run_s_rows_do_not_survive_into_the_next(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(tmp_path=tmp_path)
        monkeypatch.setattr(
            app_module.AnalysisTagToolApp, "_on_complete", lambda _self, **kwargs: None
        )

        app._finish_run(
            header=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=0.0,
            log_entries=[],
            groups=2,
            duplicates=5,
            quarantined=0,
        )
        app._finish_run(
            header=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=0.0,
            log_entries=[],
            groups=0,
            duplicates=0,
            quarantined=0,
        )

        assert dict(app._summary_extras())["Duplicate groups"] == "0"


class TestRunNote:
    """What the driver learns about a run that did not cover everything."""

    def test_a_clean_run_records_no_caveat(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(tmp_path=tmp_path)
        recorded: list[tuple[str, ...]] = []
        monkeypatch.setattr(
            app_module, "record_caveats", lambda *_args: recorded.append(_args)
        )

        DuplicateFinderApp._record_run_note(app, total=4, skipped=0, errors=0)

        assert recorded == [("duplicate_finder", "", "")]

    def test_unreadable_and_unmoved_files_are_named(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(tmp_path=tmp_path)
        recorded: list[tuple[str, ...]] = []
        monkeypatch.setattr(
            app_module, "record_caveats", lambda *_args: recorded.append(_args)
        )

        DuplicateFinderApp._record_run_note(app, total=10, skipped=2, errors=1)

        (_tool, move_note, fingerprint_note) = recorded[0]
        assert "1 of 10 files could not be quarantined" in move_note
        assert "2 of 10 files had no readable fingerprint" in fingerprint_note


@pytest.fixture()
def dialogs(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Replace the module's messagebox so no modal dialog is ever shown.

    A real ``showerror`` blocks on a modal window the test can never click,
    which hangs the run instead of failing it.
    """
    messagebox = MagicMock()
    monkeypatch.setattr(app_module, "messagebox", messagebox)
    return messagebox


class TestStartValidation:
    """A run that cannot work says so without touching the library."""

    def test_an_empty_folder_is_refused(self, dialogs: MagicMock) -> None:
        app = shell(folder="")

        DuplicateFinderApp.start_processing(app)

        assert "No Directory Selected" in str(dialogs.showerror.call_args)

    def test_a_missing_folder_is_refused(
        self, tmp_path: Path, dialogs: MagicMock
    ) -> None:
        app = shell(folder=str(tmp_path / "nope"))

        DuplicateFinderApp.start_processing(app)

        assert "Directory Not Found" in str(dialogs.showerror.call_args)

    def test_an_out_of_range_threshold_is_refused(
        self, tmp_path: Path, dialogs: MagicMock
    ) -> None:
        app = shell(folder=str(tmp_path), threshold=2.0)

        DuplicateFinderApp.start_processing(app)

        assert "Invalid Threshold" in str(dialogs.showerror.call_args)
        assert app.start_btn.config.call_count == 0

    def test_the_quarantine_folder_cannot_be_the_scanned_folder(
        self, tmp_path: Path, dialogs: MagicMock
    ) -> None:
        app = shell(folder=str(tmp_path), mode=LIVE_UPDATE, quarantine=str(tmp_path))

        DuplicateFinderApp.start_processing(app)

        assert "Invalid Quarantine Folder" in str(dialogs.showerror.call_args)
        assert app.notebook.select.call_count == 0

    def test_the_scan_starts_on_a_worker_thread(
        self, tmp_path: Path, dialogs: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(folder=str(tmp_path), mode=DRY_RUN)
        started: list[tuple[Any, ...]] = []
        thread = MagicMock()
        monkeypatch.setattr(
            app_module,
            "threading",
            MagicMock(
                Thread=lambda **kwargs: (
                    started.append(kwargs["args"]),
                    thread,
                )[1]
            ),
        )

        DuplicateFinderApp.start_processing(app)

        assert started == [
            (
                str(tmp_path),
                True,
                DEFAULT_THRESHOLD,
                str(tmp_path / "duplicate_quarantine"),
            )
        ]
        assert thread.start.call_count == 1
        assert app._log_path == str(tmp_path / RUN_REPORT_DRY_RUN)
        app.notebook.select.assert_called_once()


class TestDriverOptions:
    """Every pre-fill route writes the widget the user would have edited."""

    def test_the_threshold_and_quarantine_folder_are_mirrored(self) -> None:
        app = shell()

        app._apply_tool_cli_options(
            MagicMock(threshold=0.05, quarantine_dir="D:/q", auto_end=True)
        )

        app.threshold.set.assert_called_once_with(0.05)
        app.quarantine_dir.set.assert_called_once_with("D:/q")
        assert app.auto_end is True

    def test_an_absent_option_leaves_the_control_alone(self) -> None:
        app = shell()

        app._apply_tool_cli_options(
            MagicMock(threshold=0.0, quarantine_dir="", auto_end=False)
        )

        app.threshold.set.assert_not_called()
        app.quarantine_dir.set.assert_not_called()
        assert app.auto_end is False


class TestPresets:
    """A saved preset round-trips the settings the tool owns."""

    def test_collect_and_apply_round_trip(self) -> None:
        app = shell(mode=LIVE_UPDATE, threshold=0.05, quarantine="D:/q")

        settings = DuplicateFinderApp._collect_settings(app)
        app.threshold.set.reset_mock()
        app.quarantine_dir.set.reset_mock()
        app.run_mode.set.reset_mock()
        DuplicateFinderApp._apply_preset(app, settings)

        app.threshold.set.assert_called_once_with(0.05)
        app.quarantine_dir.set.assert_called_once_with("D:/q")
        app.run_mode.set.assert_called_once_with(LIVE_UPDATE)


class TestRunReportNames:
    """The names the guide quotes, and the mode that decides between them."""

    def test_the_two_report_names_are_the_tool_s_own(self) -> None:
        assert RUN_REPORT_DRY_RUN == "duplicate_finder_dry_run_log.txt"
        assert RUN_REPORT_LIVE == "duplicate_finder_sync_log.txt"

    def test_the_help_guide_and_tool_id_are_the_declared_ones(self) -> None:
        # ``platform_utils.open_help`` maps this file name to ``duplicate_finder``;
        # tests/test_suite_docs_tool_coverage.py holds the whole registry, so the
        # window only has to name the same guide the registry knows.
        assert DuplicateFinderApp.HELP_GUIDE == "Duplicate_Finder_User_Guide.docx"
        assert DuplicateFinderApp.TOOL_ID == "duplicate_finder"


@pytest.mark.integration
class TestCompletionSeam:
    """The real scan into the handler the window binds."""

    def test_the_run_writes_the_report_it_reports(
        self, library: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(mode=DRY_RUN, tmp_path=tmp_path, folder=str(library))
        monkeypatch.setattr(
            app_module.AnalysisTagToolApp,
            "_on_complete",
            app_module.AnalysisTagToolApp._on_complete,
        )

        from duplicate_finder.core.file_processor import run_duplicate_scan
        from duplicate_finder.core.models import ScanSettings

        run_duplicate_scan(
            str(library),
            True,
            ScanSettings(quarantine_dir=str(tmp_path / "quarantine")),
            on_complete=app._finish_run,
        )

        written = (tmp_path / "report.txt").read_text(encoding="utf-8")
        assert "DUPLICATE REPORT" in written
        assert "Mode: DRY RUN" in written
        assert "[KEEP]" in written and "song.flac" in written
        assert "Duplicate groups: 1" in written
        assert "Duplicate files: 3" in written
        assert "Files would quarantine: 0" in written
        assert "Files scanned: 7" in written
