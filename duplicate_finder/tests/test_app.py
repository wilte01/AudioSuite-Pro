# Changed in 2.6.0: exact matching reaches the run and the summary (F-E9).
# Changed in 2.4.0: duplicate dispositions and ASX stubs.
"""Tests for the Duplicate Finder window.

The window is a ``SuiteApp`` on the shared three tabs, so what is checked here
is the part that is this tool's own: the completion handler's row set and the
report it writes, the callbacks the scan's thread queues, the validation a run
must pass before it starts, the driver's pre-fill routes, and --
``TestCompletionSeam`` -- the real scan driven into the handler it binds,
asserting the report the run writes.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.

Changed in 2.9.0: the window composes ``SuiteApp``, so the shells name the
shell's tab frames and the completion is read from the report it writes (C1
stage 2).

Changed in 2.9.0: ``TestQueuedUiUpdates`` locks the queue poller the scan's
thread publishes into (no ``root.after`` and no widget write off the Tk
thread).
"""

from __future__ import annotations

from pathlib import Path
from queue import SimpleQueue
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared import suite_app
from duplicate_finder.core.disposition import DEFAULT_DISPOSITION
from duplicate_finder.core.models import DEFAULT_THRESHOLD
from duplicate_finder.ui import app as app_module
from duplicate_finder.ui.app import (
    DRY_RUN,
    LIVE_UPDATE,
    RUN_REPORT_DRY_RUN,
    RUN_REPORT_LIVE,
    DuplicateFinderApp,
)
from duplicate_finder.utils.cli_args import DuplicateFinderArgs


def shell(
    *,
    mode: str = DRY_RUN,
    tmp_path: Path | None = None,
    folder: str = "",
    threshold: float = DEFAULT_THRESHOLD,
    quarantine: str = "",
    disposition: str = DEFAULT_DISPOSITION,
) -> DuplicateFinderApp:
    """Return a window object without building any widgets.

    Args:
        mode: The run mode the Mode combobox holds.
        tmp_path: Directory for the report path; ``None`` leaves it blank.
        folder: The source folder the entry holds.
        threshold: The similarity threshold the slider holds.
        quarantine: The quarantine folder the entry holds.
        disposition: The duplicate-handling value the combobox holds.

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
    app.disposition = MagicMock()
    app.disposition.get.return_value = disposition
    app.exact_mode = MagicMock()
    app.exact_mode.get.return_value = "off"
    app._launched_from_driver = False
    app._setup_frame = MagicMock()
    app.auto_end = False
    app._ui_updates = SimpleQueue()
    app._run_thread = None
    app._log_path = str(tmp_path / "report.txt") if tmp_path is not None else ""
    app._run_mode = mode
    app._run_disposition = disposition
    app._run_folder = folder
    app._record_run_note = MagicMock()  # type: ignore[method-assign]
    app.start_btn = MagicMock()
    app.notebook = MagicMock()
    app.processing_frame = MagicMock()
    app.results_frame = MagicMock()
    app.file_listbox = MagicMock()
    app._reset_progress_ui = MagicMock()  # type: ignore[method-assign]
    app.overall_status = MagicMock()
    return app


class TestCompletionRows:
    """What the finished run adds to the report and the Results panel."""

    def test_a_dry_run_reports_what_it_would_quarantine(self, tmp_path: Path) -> None:
        app = shell(mode=DRY_RUN, tmp_path=tmp_path)

        app._finish_run(
            header=["h\n"],
            total=7,
            processed=7,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=["line\n"],
            groups=1,
            exact_groups=0,
            duplicates=3,
            quarantined=0,
            deleted=0,
            stubbed=0,
        )

        written = (tmp_path / "report.txt").read_text(encoding="utf-8")
        assert "Duplicate groups: 1" in written
        assert "Exact groups: 0" in written
        assert "Duplicate files: 3" in written
        assert "Files would quarantine: 0" in written
        assert "Without a fingerprint: 0" in written

    def test_a_live_run_reports_what_it_moved(self, tmp_path: Path) -> None:
        app = shell(mode=LIVE_UPDATE, tmp_path=tmp_path)

        app._finish_run(
            header=[],
            total=7,
            processed=7,
            skipped=1,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
            groups=1,
            exact_groups=0,
            duplicates=3,
            quarantined=3,
            deleted=0,
            stubbed=0,
        )

        written = (tmp_path / "report.txt").read_text(encoding="utf-8")
        assert "Files quarantined: 3" in written
        assert "Without a fingerprint: 1" in written

    def test_the_shared_fields_reach_the_report(self, tmp_path: Path) -> None:
        app = shell(tmp_path=tmp_path)

        app._finish_run(
            header=["h\n"],
            total=4,
            processed=4,
            skipped=2,
            errors=1,
            duration_secs=2.5,
            log_entries=["a\n", "b\n"],
            groups=0,
            exact_groups=0,
            duplicates=0,
            quarantined=0,
            deleted=0,
            stubbed=0,
            unexpected="ignored",
        )

        written = (tmp_path / "report.txt").read_text(encoding="utf-8")
        assert written.startswith("h\na\nb\n")
        assert "Total files: 4" in written
        # 4 visited - 2 without a fingerprint - 1 unmoved.
        assert "Files scanned: 1" in written
        assert "Skipped: 2" in written
        assert "Errors: 1" in written
        assert "Time: 00:02" in written

    def test_each_completion_carries_its_own_rows(self, tmp_path: Path) -> None:
        app = shell(tmp_path=tmp_path)

        app._finish_run(
            header=[],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=0.0,
            log_entries=[],
            groups=2,
            exact_groups=1,
            duplicates=5,
            quarantined=0,
            deleted=0,
            stubbed=0,
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
            exact_groups=0,
            duplicates=0,
            quarantined=0,
            deleted=0,
            stubbed=0,
        )

        first = app._ui_updates.get_nowait()
        second = app._ui_updates.get_nowait()
        assert first[0] == second[0] == "complete"
        assert dict(first[-1])["Duplicate groups"] == "2"
        assert dict(second[-1])["Duplicate groups"] == "0"


class TestQueuedUiUpdates:
    """The scan's thread queues its widget writes; the Tk poller applies them.

    ``_run_scan`` is a raw ``threading.Thread``, so it must not call
    ``root.after`` or a widget at all (AGENTS.md): every callback the processor
    publishes is a queue message.
    """

    @staticmethod
    def _app() -> DuplicateFinderApp:
        app = object.__new__(DuplicateFinderApp)
        app.root = MagicMock()
        app._ui_updates = SimpleQueue()
        app._run_thread = None
        app.stats_label = MagicMock()
        app.progress = MagicMock()
        app.file_listbox = MagicMock()
        app.start_btn = MagicMock()
        app.summary_label = MagicMock()
        app._run_mode = DRY_RUN
        app._run_folder = "D:/music"
        app.auto_end = False
        return app

    def test_a_progress_tick_is_queued_not_written(self) -> None:
        app = self._app()

        app._on_progress(4, 10, 2, 1, "song.flac")

        app.root.after.assert_not_called()
        app.stats_label.config.assert_not_called()
        assert app._ui_updates.get_nowait() == ("progress", 4, 10, 2, 1, "song.flac")

    def test_a_run_error_is_queued_not_raised(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dialogs = MagicMock()
        monkeypatch.setattr(suite_app, "messagebox", dialogs)
        app = self._app()

        app._on_error("No supported audio files found.")

        app.root.after.assert_not_called()
        dialogs.showerror.assert_not_called()
        assert app._ui_updates.get_nowait() == (
            "error",
            "No supported audio files found.",
        )

    def test_the_poller_writes_the_queued_tick(self) -> None:
        app = self._app()
        app._on_progress(4, 10, 2, 1, "song.flac")

        app._poll_ui_updates()

        assert app.stats_label.config.call_args.kwargs["text"] == (
            "Processed: 4 | Skipped: 2 | Errors: 1"
        )
        assert app.file_listbox.insert.call_args.args[1] == "song.flac"
        # The run's thread is gone, so the poller stops instead of rescheduling.
        app.root.after.assert_not_called()

    def test_the_poller_writes_the_queued_completion(self) -> None:
        app = self._app()
        app._ui_updates.put(
            ("complete", 7, 7, 0, 0, 65.0, (("Duplicate groups", "1"),))
        )

        app._poll_ui_updates()

        text = app.summary_label.config.call_args.kwargs["text"]
        assert text.startswith("Total: 7 files")
        assert "Duplicate groups: 1" in text
        assert app.completion_text == DuplicateFinderApp.DRY_COMPLETE_LABEL
        # ``render_completion`` records the run's folder for Open Folder.
        assert app._out_dir == "D:/music"

    def test_the_poller_raises_a_queued_error_on_the_tk_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dialogs = MagicMock()
        monkeypatch.setattr(suite_app, "messagebox", dialogs)
        app = self._app()
        app._on_error("No supported audio files found.")

        app._poll_ui_updates()

        dialogs.showerror.assert_called_once_with(
            "Error", "No supported audio files found."
        )
        app.start_btn.config.assert_called_once_with(state="normal")

    def test_the_poller_keeps_polling_while_the_run_thread_lives(self) -> None:
        app = self._app()
        app._run_thread = MagicMock()
        app._run_thread.is_alive.return_value = True

        app._poll_ui_updates()

        app.root.after.assert_called_once_with(
            app_module._UI_POLL_MS, app._poll_ui_updates
        )

    def test_a_run_builds_its_queue_and_starts_the_poller(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(folder=str(tmp_path))
        thread = MagicMock()
        monkeypatch.setattr(app_module, "threading", MagicMock(Thread=thread))

        DuplicateFinderApp.start_processing(app)

        assert isinstance(app._ui_updates, SimpleQueue)
        assert app._run_thread is thread.return_value
        app.root.after.assert_called_once_with(
            app_module._UI_POLL_MS, app._poll_ui_updates
        )


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
                DEFAULT_DISPOSITION,
                "off",
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
            DuplicateFinderArgs(
                threshold=0.05,
                quarantine_dir="D:/q",
                disposition="delete",
                exact_mode="only",
                auto_end=True,
            )
        )

        app.threshold.set.assert_called_once_with(0.05)
        app.quarantine_dir.set.assert_called_once_with("D:/q")
        app.exact_mode.set.assert_called_once_with("only")
        assert app.auto_end is True

    def test_an_absent_option_leaves_the_control_alone(self) -> None:
        app = shell()

        app._apply_tool_cli_options(DuplicateFinderArgs(threshold=0.0, exact_mode=""))

        app.threshold.set.assert_not_called()
        app.quarantine_dir.set.assert_not_called()
        app.exact_mode.set.assert_not_called()
        assert app.auto_end is False


class TestDispositionPrefill:
    """Every route reaches the same update function and the same state."""

    def test_the_update_function_sets_the_variable_and_dependent_controls(
        self,
    ) -> None:
        app = shell()

        DuplicateFinderApp._set_disposition(app, "asx-stub")

        app.disposition.set.assert_called_once_with("asx-stub")
        app._setup_frame.apply_disposition.assert_called_once_with("asx-stub")

    def test_driver_argv_applies_the_disposition(self) -> None:
        app = shell()

        app._apply_tool_cli_options(
            DuplicateFinderArgs(threshold=0.0, disposition="delete")
        )

        app.disposition.set.assert_called_once_with("delete")
        app._setup_frame.apply_disposition.assert_called_once_with("delete")

    def test_a_preset_without_the_key_loads_as_quarantine(self) -> None:
        app = shell(disposition="delete")

        DuplicateFinderApp._apply_preset(app, {"run_mode": DRY_RUN})

        app.disposition.set.assert_called_once_with("quarantine")

    def test_a_delete_run_asks_before_it_starts(
        self, tmp_path: Path, dialogs: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(folder=str(tmp_path), mode=LIVE_UPDATE, disposition="delete")
        dialogs.askyesno.return_value = False
        thread = MagicMock()
        monkeypatch.setattr(app_module, "threading", MagicMock(Thread=thread))

        DuplicateFinderApp.start_processing(app)

        dialogs.askyesno.assert_called_once()
        thread.assert_not_called()

    def test_a_driven_delete_run_does_not_block_on_a_dialog(
        self, tmp_path: Path, dialogs: MagicMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = shell(folder=str(tmp_path), mode=LIVE_UPDATE, disposition="delete")
        app._launched_from_driver = True
        thread = MagicMock()
        monkeypatch.setattr(app_module, "threading", MagicMock(Thread=thread))

        DuplicateFinderApp.start_processing(app)

        dialogs.askyesno.assert_not_called()
        thread.assert_called_once()


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
        self, library: Path, tmp_path: Path
    ) -> None:
        app = shell(mode=DRY_RUN, tmp_path=tmp_path, folder=str(library))

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
