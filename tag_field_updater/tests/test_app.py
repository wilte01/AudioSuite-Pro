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
