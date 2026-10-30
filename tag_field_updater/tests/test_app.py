"""
tests/test_app.py - unit tests for TagFieldUpdaterApp (GUI orchestrator).

Stage 3 item D1 (audit A4): ``tag_field_updater/ui/app.py`` shipped at 0%
coverage. The constructor/wiring test runs against the session-scoped hidden
Tk root; the behavioural tests use the ``object.__new__`` + ``MagicMock``
shell pattern, so nothing here needs a real display.

Import discipline: ``tag_field_updater.ui.app`` is imported lazily, inside
functions. Test modules are all imported at *collection* time, before any
test runs; a module-level import of ``ui.app`` here would put the real module
into ``sys.modules`` and silently change
``tests/test_pyw_launchers.py::TestGenericStartupFailureIsWitnessed
[Tag_Field_Updater.pyw-tag_field_updater]``, which requires that import to
fail while its launcher-stub contract is exercised. Keep it lazy.

Changed in 1.0.1: adds the Dry Run checkbox coverage.
Changed in 1.2.0: covers the run note a finished scan leaves for the Master
Driver batch report (the files it skipped and the ones it could not update).
Changed in 2.2.0: covers the filename source's GUI surface (F-01) - the mode
checks Dry Run, the pattern box is read in order, a bad pattern is refused
before the worker starts, and saved action groups load and save through the
shared config.
"""

from __future__ import annotations

import logging
import threading
import tkinter
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.run_outcome import read_outcome
from tag_field_updater.core.processor import ProcessingStats, TagProcessor


def _ui_app_module():
    """Return the app module (lazily - see the module docstring)."""
    import tag_field_updater.ui.app as app_module

    return app_module


def _make_shell_app() -> Any:
    """Build a TagFieldUpdaterApp shell with mock attributes."""
    app = object.__new__(_ui_app_module().TagFieldUpdaterApp)
    app.root = MagicMock()
    app.directory = MagicMock()
    app.dry_run = MagicMock()
    # Filename-source widgets (F-01): the shell must carry them or
    # ``start_scanning`` cannot ask which source was selected.
    app.filename_mode = MagicMock()
    app.filename_mode.get.return_value = False
    app.only_fill_blanks = MagicMock()
    app.only_fill_blanks.get.return_value = True
    app.patterns_text = MagicMock()
    app.action_group = MagicMock()
    app.group_combo = MagicMock()
    app.scanning = MagicMock()
    app.current_file = MagicMock()
    app.processed_count = MagicMock()
    app.updated_count = MagicMock()
    app.error_count = MagicMock()
    app.status_var = MagicMock()
    app.start_button = MagicMock()
    app.stop_button = MagicMock()
    app.processor = TagProcessor()
    return app


def assert_bound(callback: Any, name: str, app: Any) -> None:
    """Assert *callback* is the bound ``*name*`` method of *app*.

    Bound methods are fresh objects per attribute access, so they must be
    compared via ``__self__`` / ``__name__``, never by identity.
    """
    assert getattr(callback, "__self__", None) is app
    assert callback.__name__ == name


@pytest.fixture()
def stubbed_dialogs(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Replace the module's messagebox and filedialog namespaces."""
    app_module = _ui_app_module()
    messagebox = MagicMock()
    filedialog = MagicMock()
    monkeypatch.setattr(app_module, "messagebox", messagebox)
    monkeypatch.setattr(app_module, "filedialog", filedialog)
    return messagebox, filedialog


@pytest.fixture()
def fake_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[MagicMock, None, None]:
    """Capture the scan worker thread without running it.

    The patch replaces the ``threading`` binding inside the app module only,
    so the real standard-library module is untouched.
    """
    thread = MagicMock()
    threading_ns = MagicMock()
    threading_ns.Thread = lambda *args, **kwargs: (
        setattr(thread, "target", kwargs.get("target")),
        setattr(thread, "args", kwargs.get("args")),
        thread,
    )[-1]
    monkeypatch.setattr(_ui_app_module(), "threading", threading_ns)
    return thread


@pytest.fixture()
def app_root(root):
    """A fresh withdrawn ``Toplevel`` off the shared hidden root.

    Some tools' suites leave ``pack``-managed widgets inside the shared root,
    and ``setup_ui`` grids into its window, so constructing on the root itself
    mixes geometry managers across suites (``cannot use geometry manager
    "grid" inside ".": pack is already managing...``). A dedicated toplevel
    isolates this app's layout without creating a second display.
    """
    top = tkinter.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


@pytest.fixture(autouse=True)
def _uncache_ui_app():
    """Undo the ``sys.modules`` entries an executed test introduced.

    Importing ``tag_field_updater.ui.app`` caches the module for the rest of
    the session; other tests (``tests/test_pyw_launchers.py``'s launcher-stub
    contract) require the *absence* of that cache, so this test module must
    restore first-party module state after every test. Deleting a child also
    scrubs the attribute its parent package got during the import, otherwise
    ``from tag_field_updater import ui`` would later bind a stale module
    object and two class copies would coexist.
    """
    import sys
    from contextlib import contextmanager

    @contextmanager
    def _scope():
        before = frozenset(sys.modules)
        try:
            yield
        finally:
            added = [name for name in sys.modules if name not in before]
            for name in added:
                if not name.startswith("tag_field_updater"):
                    continue
                module = sys.modules.get(name)
                if module is None:
                    continue
                parent_name, _, attr = name.rpartition(".")
                if parent_name:
                    parent = sys.modules.get(parent_name)
                    if parent is not None and getattr(parent, attr, None) is module:
                        delattr(parent, attr)
                del sys.modules[name]

    with _scope():
        yield


class TestConstructorWiring:
    """__init__ is exercised against the session-scoped hidden Tk root."""

    def test_wireup(self, app_root) -> None:
        app = _ui_app_module().TagFieldUpdaterApp(app_root)

        assert isinstance(app.processor, TagProcessor)
        assert isinstance(app.stats, ProcessingStats)
        assert app.directory.get() == ""
        assert app.scanning.get() is False
        assert app.processed_count.get() == 0
        assert app.updated_count.get() == 0
        assert app.error_count.get() == 0
        assert app.status_var.get() == "Ready"
        # Buttons: scan enabled, stop disabled until a scan starts.
        assert app.start_button.instate(["!disabled"])
        assert app.stop_button.instate(["disabled"])

    def test_info_text_lists_the_update_rules(self, app_root) -> None:
        """The field-help text survives UI edits (the tool's contract)."""
        app = _ui_app_module().TagFieldUpdaterApp(app_root)

        labels: list[Any] = []

        def _collect(widget: Any) -> None:
            for child in widget.winfo_children():
                if child.winfo_class() == "TLabel" and child.cget("text"):
                    labels.append(child)
                _collect(child)

        _collect(app.root)
        texts = "".join(str(label.cget("text")) for label in labels)
        # '/' is rewritten and ' / ' is preserved - both rules must stay.
        assert "DO NOT replace ' / '" in texts, texts
        assert "existing values" in texts, texts


class TestBrowseDirectory:
    def test_populates_directory(self, stubbed_dialogs) -> None:
        _, filedialog = stubbed_dialogs
        app = _make_shell_app()
        filedialog.askdirectory.return_value = str(Path("D:/Music"))

        app.browse_directory()

        app.directory.set.assert_called_once_with(str(Path("D:/Music")))
        filedialog.askdirectory.assert_called_once()

    def test_cancelled_picker_leaves_directory(self, stubbed_dialogs) -> None:
        _, filedialog = stubbed_dialogs
        app = _make_shell_app()
        filedialog.askdirectory.return_value = ""

        app.browse_directory()

        filedialog.askdirectory.assert_called_once()
        app.directory.set.assert_not_called()


class TestProgressMarshalling:
    def test_on_progress_marshals_onto_main_thread(self) -> None:
        """Worker threads must not touch Tk vars directly; after(0, ...) only."""
        app = _make_shell_app()
        stats = ProcessingStats(processed_files=3, updated_files=2, error_files=1)

        app._on_progress("song.mp3", stats)

        call = app.root.after.call_args
        assert call is not None, "progress must be marshalled via root.after"
        assert call.args[0] == 0
        assert_bound(call.args[1], "_apply_progress_update", app)
        assert call.args[2:] == ("song.mp3", 3, 2, 1)

    def test_apply_progress_update_sets_all_vars(self) -> None:
        app = _make_shell_app()

        app._apply_progress_update("song.mp3", 7, 4, 1)

        app.current_file.set.assert_called_once_with("song.mp3")
        app.processed_count.set.assert_called_once_with(7)
        app.updated_count.set.assert_called_once_with(4)
        app.error_count.set.assert_called_once_with(1)


class TestStartScanning:
    def test_empty_directory_shows_error(self, stubbed_dialogs) -> None:
        messagebox, _ = stubbed_dialogs
        app = _make_shell_app()
        app.directory.get.return_value = "  "

        app.start_scanning()

        messagebox.showerror.assert_called_once()
        app.scanning.set.assert_not_called()

    def test_missing_directory_shows_error(self, stubbed_dialogs) -> None:
        messagebox, _ = stubbed_dialogs
        app = _make_shell_app()
        app.directory.get.return_value = str(Path("D:/nonexistent_xyz"))

        app.start_scanning()

        messagebox.showerror.assert_called_once()

    def test_valid_directory_resets_and_starts(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        app = _make_shell_app()
        app.directory.get.return_value = str(tmp_path)
        app.stats = ProcessingStats(processed_files=9, updated_files=9)

        app.start_scanning()

        assert isinstance(app.stats, ProcessingStats)
        assert app.stats.processed_files == 0
        app.processed_count.set.assert_called_once_with(0)
        app.updated_count.set.assert_called_once_with(0)
        app.error_count.set.assert_called_once_with(0)
        app.scanning.set.assert_called_once_with(True)
        app.start_button.config.assert_called_once_with(state="disabled")
        app.stop_button.config.assert_called_once_with(state="normal")
        app.status_var.set.assert_called_once_with("Scanning...")
        assert_bound(fake_thread.target, "_scan_thread", app)
        fake_thread.start.assert_called_once_with()


class TestScanThread:
    def test_scan_runs_in_batch_and_schedules_finish(self, tmp_path: Path) -> None:
        """Empty directory: real processor, wrapped in the undo batch context."""
        app = _make_shell_app()
        app.scanning.get.return_value = True

        app._scan_thread(str(tmp_path), dry_run=False)

        call = app.root.after.call_args
        assert call is not None
        assert call.args[0] == 0
        assert_bound(call.args[1], "finish_scanning", app)

    def test_scan_error_is_logged_not_raised(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        app = _make_shell_app()
        app.scanning.get.return_value = True
        failures = {"count": 0}

        def _boom(*_a: Any, **_k: Any) -> None:
            failures["count"] += 1
            raise RuntimeError("scan exploded")

        monkeypatch.setattr(app.processor, "scan_directory", _boom)

        with caplog.at_level(logging.ERROR, logger="tag_field_updater.ui.app"):
            app._scan_thread(str(Path("D:/whatever")), dry_run=False)

        assert failures["count"] == 1
        assert any(
            r.levelno == logging.ERROR and r.exc_info is not None
            for r in caplog.records
        ), "the unhandled scan error must carry a traceback"
        call = app.root.after.call_args
        assert call is not None
        (
            assert_bound(call.args[1], "finish_scanning", app),
            "finish must be scheduled from finally even after a failure",
        )


class TestStopScanning:
    def test_requests_processor_stop(self) -> None:
        app = _make_shell_app()
        processor = MagicMock()
        app.processor = processor  # type: ignore[assignment]

        app.stop_scanning()

        processor.stop.assert_called_once()
        app.status_var.set.assert_called_once_with("Stopping...")


class TestFinishScanning:
    def test_reset_ui_and_summary(self, stubbed_dialogs) -> None:
        messagebox, _ = stubbed_dialogs
        app = _make_shell_app()
        app.processor = MagicMock()
        stats = ProcessingStats(
            processed_files=10, updated_files=6, error_files=2, skipped_files=2
        )
        app.processor.stats = stats

        app.finish_scanning()

        app.scanning.set.assert_called_once_with(False)
        app.start_button.config.assert_called_once_with(state="normal")
        app.stop_button.config.assert_called_once_with(state="disabled")
        app.current_file.set.assert_called_once_with("")
        app.status_var.set.assert_called_once_with("Scan Complete")
        messagebox.showinfo.assert_called_once()
        summary = str(messagebox.showinfo.call_args.args[1])
        for fragment in ("10", "6", "2"):
            assert fragment in summary

    def test_dialog_failure_is_logged_not_raised(
        self, stubbed_dialogs, caplog: pytest.LogCaptureFixture
    ) -> None:
        messagebox, _ = stubbed_dialogs
        messagebox.showinfo.side_effect = RuntimeError("tk is broken")
        app = _make_shell_app()
        app.processor = MagicMock()
        app.processor.stats = ProcessingStats()

        with caplog.at_level(logging.ERROR, logger="tag_field_updater.ui.app"):
            app.finish_scanning()

        assert any(
            r.levelno == logging.ERROR and "finish_scanning" in r.getMessage()
            for r in caplog.records
        )


class TestRunNote:
    """A finished scan leaves its skipped and failed files where a batch sees them."""

    @staticmethod
    def _app(stubbed_dialogs, stats: ProcessingStats) -> Any:
        app = _make_shell_app()
        app.processor = MagicMock()
        app.processor.stats = stats
        return app

    def test_skipped_and_failed_files_are_reported(
        self, stubbed_dialogs, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = self._app(
            stubbed_dialogs,
            ProcessingStats(
                total_files=10,
                processed_files=10,
                updated_files=6,
                skipped_files=2,
                error_files=2,
            ),
        )

        app.finish_scanning()

        assert read_outcome("tag_field_updater") == (
            "2 of 10 files could not be updated; 2 of 10 files were skipped "
            "(unsupported format or no readable tags)"
        )

    def test_a_clean_scan_reports_nothing(
        self, stubbed_dialogs, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = self._app(
            stubbed_dialogs,
            ProcessingStats(total_files=5, processed_files=5, updated_files=5),
        )

        app.finish_scanning()

        assert read_outcome("tag_field_updater") == ""

    def test_a_later_clean_scan_clears_an_earlier_note(
        self, stubbed_dialogs, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        self._app(
            stubbed_dialogs,
            ProcessingStats(total_files=5, processed_files=5, error_files=1),
        ).finish_scanning()
        assert read_outcome("tag_field_updater") == "1 of 5 files could not be updated"

        self._app(
            stubbed_dialogs,
            ProcessingStats(total_files=5, processed_files=5, updated_files=5),
        ).finish_scanning()

        assert read_outcome("tag_field_updater") == ""


class TestRunAndMain:
    def test_run_enters_mainloop(self) -> None:
        app = _make_shell_app()

        app.run()

        app.root.mainloop.assert_called_once_with()

    def test_main_without_directory_starts_and_runs(
        self,
        monkeypatch: pytest.MonkeyPatch,
        app_root,
        stubbed_dialogs,
        fake_thread,
    ) -> None:
        """main() builds the app, skips the auto-start, and enters the loop."""
        import sys

        main = _ui_app_module().main
        app_cls = _ui_app_module().TagFieldUpdaterApp
        monkeypatch.setattr(tkinter, "Tk", lambda: app_root)
        monkeypatch.setattr(sys, "argv", ["tag_field_updater"])
        app_tracker: dict[str, Any] = {}

        real_init = app_cls.__init__

        def _intercept_init(self: Any, tk_root: Any) -> None:
            real_init(self, tk_root)
            app_tracker["app"] = self
            self.run = MagicMock()  # type: ignore[method-assign]

        monkeypatch.setattr(app_cls, "__init__", _intercept_init)

        main()

        assert "app" in app_tracker
        app_tracker["app"].run.assert_called_once_with()
        fake_thread.start.assert_not_called()  # no auto-start without a directory

    def test_main_rejects_missing_directory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        app_root,
        stubbed_dialogs,
    ) -> None:
        main = _ui_app_module().main
        monkeypatch.setattr(tkinter, "Tk", lambda: app_root)

        with pytest.raises(SystemExit) as exit_exc:
            main(directory=str(Path("D:/definitely_not_a_dir_12345")))

        assert exit_exc.value.code == 1

    def test_main_prepopulates_and_auto_starts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        app_root,
        stubbed_dialogs,
        fake_thread,
        tmp_path: Path,
    ) -> None:
        main = _ui_app_module().main
        app_cls = _ui_app_module().TagFieldUpdaterApp
        monkeypatch.setattr(tkinter, "Tk", lambda: app_root)
        final: dict[str, Any] = {}

        real_init = app_cls.__init__

        def _intercept_init(self: Any, tk_root: Any) -> None:
            real_init(self, tk_root)
            final["app"] = self
            self.run = MagicMock()  # type: ignore[method-assign]

        monkeypatch.setattr(app_cls, "__init__", _intercept_init)

        main(directory=str(tmp_path))

        app = final["app"]
        assert app.directory.get() == str(tmp_path)
        assert_bound(fake_thread.target, "_scan_thread", app)
        fake_thread.start.assert_called_once_with()

    def test_main_rejects_a_file_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        app_root,
        stubbed_dialogs,
        tmp_path: Path,
    ) -> None:
        """A path that exists but is not a directory exits 1 without scanning."""
        main = _ui_app_module().main
        marker = tmp_path / "file.txt"
        marker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(tkinter, "Tk", lambda: app_root)
        started = threading.Event()
        threading_ns = MagicMock()
        threading_ns.Thread = lambda *a, **k: started.set()  # pragma: no cover
        monkeypatch.setattr(_ui_app_module(), "threading", threading_ns)

        with pytest.raises(SystemExit) as exit_exc:
            main(directory=str(marker))

        assert exit_exc.value.code == 1
        assert not started.is_set()


# ---------------------------------------------------------------------------
# The filename source's GUI surface (F-01)
# ---------------------------------------------------------------------------


def _filename_shell(patterns: str = "%artist% - %title%\n") -> Any:
    """Build the shell app with the filename widgets wired to real behaviour."""
    app = _make_shell_app()
    app.filename_mode = MagicMock()
    app.filename_mode.get.return_value = True
    app.only_fill_blanks = MagicMock()
    app.only_fill_blanks.get.return_value = True
    app.patterns_text = MagicMock()
    app.patterns_text.get.return_value = patterns
    app.action_group = MagicMock()
    app.action_group.get.return_value = ""
    app.group_combo = MagicMock()
    return app


@pytest.fixture()
def isolated_config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the shared suite config at *tmp_path*, never the shipped file."""
    from audio_suite_shared import suite_config

    path = tmp_path / "audio_suite_config.json"
    monkeypatch.setattr(suite_config, "CONFIG_PATH", path)
    monkeypatch.setattr(suite_config, "_LOCK_PATH", path.with_suffix(".json.lock"))
    suite_config._invalidate_cache()
    yield path
    suite_config._invalidate_cache()


class TestFilenameModeDefaultsToDry:
    def test_enabling_the_mode_checks_dry_run(self) -> None:
        """A mis-parse must not be written because the mode was switched on."""
        app = _make_shell_app()
        app.filename_mode = MagicMock()
        app.filename_mode.get.return_value = True
        app.dry_run = MagicMock()

        app._on_filename_mode_toggled()

        app.dry_run.set.assert_called_once_with(True)
        assert "dry run" in app.status_var.set.call_args.args[0].lower()

    def test_disabling_the_mode_leaves_the_choice_alone(self) -> None:
        app = _make_shell_app()
        app.filename_mode = MagicMock()
        app.filename_mode.get.return_value = False
        app.dry_run = MagicMock()

        app._on_filename_mode_toggled()

        app.dry_run.set.assert_not_called()

    def test_the_pattern_box_lists_patterns_in_order(self) -> None:
        app = _filename_shell("  %track%. %artist% - %title% \n\n%artist% - %title%\n")
        assert app._patterns_from_box() == (
            "%track%. %artist% - %title%",
            "%artist% - %title%",
        )


class TestFilenameStart:
    def test_a_filename_run_configures_the_processor(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        app = _filename_shell("%disc%-%track% %artist% - %title%\n")
        app.directory.get.return_value = str(tmp_path)

        app.start_scanning()

        assert app.processor.patterns == ("%disc%-%track% %artist% - %title%",)
        assert app.processor.only_fill_blanks is True
        fake_thread.start.assert_called_once_with()

    def test_an_empty_pattern_box_does_not_start(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app = _filename_shell("\n  \n")
        app.directory.get.return_value = str(tmp_path)

        app.start_scanning()

        messagebox.showwarning.assert_called_once()
        fake_thread.start.assert_not_called()
        assert app.processor.patterns == ()

    def test_an_invalid_pattern_is_reported_before_scanning(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app = _filename_shell("%artst% - %title%\n")
        app.directory.get.return_value = str(tmp_path)

        app.start_scanning()

        messagebox.showerror.assert_called_once()
        assert "artst" in messagebox.showerror.call_args.args[1]
        fake_thread.start.assert_not_called()
        assert app.processor.patterns == ()

    def test_the_slash_rule_is_restored_when_the_mode_is_off(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        app = _make_shell_app()
        app.directory.get.return_value = str(tmp_path)
        app.processor.use_filename_patterns(("%artist% - %title%",))

        app.start_scanning()

        assert app.processor.patterns == ()
        fake_thread.start.assert_called_once_with()


class TestActionGroupsInTheGui:
    def test_saving_refuses_an_empty_pattern_box(self, stubbed_dialogs) -> None:
        messagebox, _ = stubbed_dialogs
        app = _filename_shell("\n")

        app.save_action_group()

        messagebox.showwarning.assert_called_once()

    def test_saving_stores_the_box_under_the_chosen_name(
        self, stubbed_dialogs, isolated_config: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app_module = _ui_app_module()
        simpledialog = MagicMock()
        simpledialog.askstring.return_value = "Bandcamp"
        monkeypatch.setattr(app_module, "simpledialog", simpledialog)
        app = _filename_shell("%track% %artist% - %title%\n")

        app.save_action_group()

        from tag_field_updater.utils import config as action_config

        group = action_config.get_action_group("Bandcamp")
        assert group is not None
        assert group.patterns == ("%track% %artist% - %title%",)
        app.group_combo.__setitem__.assert_called_once()

    def test_loading_fills_the_box_and_checks_the_mode(
        self, stubbed_dialogs, isolated_config: Path
    ) -> None:
        from tag_field_updater.utils import config as action_config

        action_config.save_action_group("Bandcamp", ("%track% %artist% - %title%",))
        app = _filename_shell()
        app.action_group.get.return_value = "Bandcamp"

        app.load_action_group()

        app.patterns_text.insert.assert_called_once_with(
            "1.0", "%track% %artist% - %title%"
        )
        app.filename_mode.set.assert_called_once_with(True)
        app.dry_run.set.assert_called_once_with(True)

    def test_loading_a_group_that_vanished_warns(
        self, stubbed_dialogs, isolated_config: Path
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app = _filename_shell()
        app.action_group.get.return_value = "Gone"

        app.load_action_group()

        messagebox.showwarning.assert_called_once()
        app.patterns_text.insert.assert_not_called()
