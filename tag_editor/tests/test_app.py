"""Tests for tag_editor.ui.app.

Stage 3 item D1 (audit A4): ``tag_editor/ui/app.py`` shipped with a grid built
by hand and no shared pieces.  The constructor/wiring tests run against the
session-scoped hidden Tk root; the behavioural tests use the
``object.__new__`` + ``MagicMock`` shell pattern, so nothing here needs a real
display.

Import discipline: ``tag_editor.ui.app`` is imported lazily, inside functions.
Test modules are all imported at *collection* time, before any test runs, and a
module-level import here would put the real module into ``sys.modules`` for the
rest of the session; other tests exist to witness launcher startup failures
with a stubbed package.  Keep it lazy.

Changed in 2.2.1: covers the rebuilt window (maintenance item U5) — the three
shared tabs, the shared Run Controls strip, the shared browse dialog, the
positional argv handshake, the shared progress/completion handlers, and the run
reports the window writes into the scanned folder (the file View Log opens).
The grid, the single-field/bulk apply paths and the CSV import/export keep the
behaviour coverage they had before the rebuild, driven through the new worker
entry points.

Changed in 2.9.0: covers the migration onto ``SuiteApp`` (C1 stage 2, D8's wave
3).  The window writes its own run reports now, and every callback a run
publishes — the progress tick, the run error, the completion, the grid fill,
the row refresh and the CSV warnings — is a queue message a Tk poller drains,
so the completion tests drive ``_poll_ui_updates`` instead of reading
``root.after``.
"""

from __future__ import annotations

import tkinter
from collections.abc import Generator
from pathlib import Path
from queue import SimpleQueue
from tkinter import ttk
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared import suite_app
from audio_suite_shared.event_pump import DEFAULT_POLL_MS
from audio_suite_shared.ui_common import BaseSetupFrame
from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from tag_editor.core.csv_io import CsvImportPlan
from tag_editor.core.processor import (
    EditResult,
    FieldEdit,
    TagEditorProcessor,
    TagRow,
)


def _ui_app_module():
    """Return the app module (lazily - see the module docstring)."""
    import tag_editor.ui.app as app_module

    return app_module


def _neutral_args(**overrides: Any) -> Any:
    """Return a parsed-argv stand-in with every field at its default."""
    from tag_editor.utils.cli_args import TagEditorArgs

    args = TagEditorArgs()
    for name, value in overrides.items():
        setattr(args, name, value)
    return args


def _make_shell_app() -> Any:
    """Build a TagEditorApp shell with mock attributes."""
    app = object.__new__(_ui_app_module().TagEditorApp)
    app.root = MagicMock()
    app.folder_path = MagicMock()
    app.folder_path.get.return_value = ""
    # The strip's Mode value; the shell runs live so a dry-only assertion
    # cannot pass by accident.
    app.run_mode = MagicMock()
    app.run_mode.get.return_value = "Live Update"
    app.field_var = MagicMock()
    app.field_var.get.return_value = "title"
    app.value_var = MagicMock()
    app.value_var.get.return_value = "New"
    app.clear_var = MagicMock()
    app.clear_var.get.return_value = False
    app.bulk_operation_var = MagicMock()
    app.bulk_operation_var.get.return_value = "Normalize Slashes (TXXX Rule)"
    app.bulk_field_var = MagicMock()
    app.bulk_field_var.get.return_value = "genre"
    app.second_field_var = MagicMock()
    app.second_field_var.get.return_value = "album"
    app.case_mode_var = MagicMock()
    app.case_mode_var.get.return_value = "Title Case"
    app._rows = {}
    # The shared Processing tab's status line.
    app.overall_status = MagicMock()
    # Shared window pieces: the notebook, the grid and the two built tabs.
    app.notebook = MagicMock()
    app.tree = MagicMock()
    app.tree.selection.return_value = ()
    app.progress = MagicMock()
    app.file_listbox = MagicMock()
    app.stats_label = MagicMock()
    app.completion_label = MagicMock()
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app.processing_frame = "processing-tab"
    app.results_frame = "results-tab"
    app._log_path = ""
    app.auto_end = False
    app.start_btn = MagicMock()
    app.stop_btn = MagicMock()
    app.processor = TagEditorProcessor()
    #: A run's messages and its thread: the completion and the poller read them.
    app._ui_updates = SimpleQueue()
    app._run_thread = None
    app._run_mode = "Live Update"
    app._run_folder = ""
    app._pending_extra_entries = ()
    app._pending_extra_summary = ()
    app._pending_warnings = ()
    app.error_logger = None
    app._launched_from_driver = False
    return app


@pytest.fixture(autouse=True)
def _neutral_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep pytest's own argv out of the window's handshake.

    ``__init__`` applies the Master-Driver handshake the way every peer's does
    (``cli_args.parse()`` over ``sys.argv``), and under pytest that argv is the
    test run's -- which would both fail folder validation and look like a
    driven launch, locking the strip in every test.
    """
    cli = _ui_app_module().cli_args
    monkeypatch.setattr(cli, "parse", lambda: _neutral_args())
    monkeypatch.setattr(cli, "was_launched_from_driver", lambda: False)


@pytest.fixture(autouse=True)
def _uncache_ui_app() -> Generator[None, None, None]:
    """Undo the ``sys.modules`` entries an executed test introduced.

    Importing ``tag_editor.ui.app`` caches the module for the rest of the
    session; other suites require its absence, so this module restores
    first-party module state after every test.
    """
    import sys

    before = frozenset(sys.modules)
    try:
        yield
    finally:
        added = [name for name in sys.modules if name not in before]
        for name in added:
            if not name.startswith("tag_editor"):
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


@pytest.fixture()
def stubbed_dialogs(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[MagicMock, MagicMock]:
    """Replace the module's messagebox and filedialog namespaces."""
    app_module = _ui_app_module()
    messagebox = MagicMock()
    filedialog = MagicMock()
    monkeypatch.setattr(app_module, "messagebox", messagebox)
    monkeypatch.setattr(app_module, "filedialog", filedialog)
    return messagebox, filedialog


@pytest.fixture()
def fake_thread(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Capture the worker thread without running it."""
    thread = MagicMock()
    #: Cleared so a test can assert that no run was started at all; the
    #: attribute would otherwise be an auto-created mock on every access.
    thread.target = None
    thread.args = ()
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

    A dedicated toplevel isolates this app's layout without creating a second
    display: the shared root may already be managed by another suite's widgets.
    """
    top = tkinter.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


def _labels(widget: Any) -> list[str]:
    """Return every label text in *widget*'s tree."""
    found: list[str] = []
    for child in widget.winfo_children():
        if isinstance(child, (tkinter.Label, ttk.Label)):
            text = child.cget("text")
            if text:
                found.append(str(text))
        found.extend(_labels(child))
    return found


def _run_scheduled(app: Any, name: str) -> None:
    """Run the ``root.after`` callback named *name*, as the Tk thread would.

    ``render_completion`` marshals the shell's widget writes with
    ``root.after(0, ...)``; a MagicMock root records them instead of running
    them, so a test that reads a Results-tab widget runs that one itself.
    """
    for call in app.root.after.call_args_list:
        callback = call.args[1]
        if getattr(callback, "__name__", "") == name:
            callback(*call.args[2:])
            return
    raise AssertionError(f"{name} was never scheduled: {app.root.after.call_args_list}")


def _widgets(widget: Any, kind: type) -> list[Any]:
    """Return every descendant of *widget* that is an instance of *kind*."""
    found: list[Any] = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found.extend(_widgets(child, kind))
    return found


class TestConstructorWiring:
    """__init__ is exercised against the session-scoped hidden Tk root."""

    def test_wireup(self, app_root) -> None:
        app = _ui_app_module().TagEditorApp(app_root)

        assert isinstance(app.processor, TagEditorProcessor)
        assert isinstance(app.folder_path.get(), str)
        assert app.overall_status.get() == "Ready"
        # Buttons: start enabled, stop disabled until a run starts.
        assert str(app.start_btn.cget("state")) == "normal"
        assert str(app.stop_btn.cget("state")) == "disabled"

    def test_the_window_is_a_peer_scaffold(self, app_root) -> None:
        """The app is the shared window shell, not its own wiring."""
        from audio_suite_shared.suite_app import SuiteApp

        app = _ui_app_module().TagEditorApp(app_root)

        assert isinstance(app, SuiteApp)
        assert "_build_setup_tab" in type(app).__dict__
        assert app.TOOL_ID == "tag_editor"
        assert app.HELP_GUIDE.endswith(".docx")

    def test_the_window_is_three_standard_tabs(self, app_root) -> None:
        app = _ui_app_module().TagEditorApp(app_root)

        assert isinstance(app.notebook, ttk.Notebook)
        labels = [app.notebook.tab(tab, "text").strip() for tab in app.notebook.tabs()]
        assert labels == ["1. Setup", "2. Processing", "3. Results"]

    def test_the_tabs_are_the_shared_builders(self, app_root) -> None:
        app = _ui_app_module().TagEditorApp(app_root)

        assert isinstance(app.progress, ttk.Progressbar)
        assert isinstance(app.file_listbox, tkinter.Listbox)
        assert isinstance(app.stats_label, tkinter.Label)
        for label in (app.completion_label, app.time_label, app.summary_label):
            assert isinstance(label, tkinter.Label)

    def test_the_help_button_opens_the_registered_guide(
        self, app_root, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty help_guide would make the button a silent no-op."""
        app = _ui_app_module().TagEditorApp(app_root)
        opened: list[str] = []
        monkeypatch.setattr(
            app, "_open_help_standard", lambda guide: opened.append(guide)
        )

        help_buttons = [
            button
            for button in _widgets(app.root, tkinter.Button)
            if button.cget("text") == "Help"
        ]
        assert help_buttons, "the window has no Help button"
        help_buttons[0].invoke()

        assert opened == [app.HELP_GUIDE]

    def test_the_guide_is_shipped_where_the_help_button_looks(self, app_root) -> None:
        """The inherited Help path must resolve a real file, not warn."""
        app = _ui_app_module().TagEditorApp(app_root)
        shipped = (
            Path(__file__).resolve().parents[2]
            / "documentation"
            / "user_guides"
            / "individual_programs"
            / "tag_editor"
            / app.HELP_GUIDE
        )

        assert app.HELP_GUIDE.endswith("_User_Guide.docx")
        assert shipped.is_file(), f"the Help button would find no {shipped}"

    def test_a_long_value_is_usable(self, app_root) -> None:
        """The value entry grows instead of clipping a comment."""
        app = _ui_app_module().TagEditorApp(app_root)

        assert int(app.value_entry.pack_info()["expand"]) == 1


class TestRunControlsStrip:
    """The Setup tab is the shared skeleton with the driver's strip."""

    def test_the_setup_tab_is_the_shared_skeleton(self, app_root) -> None:
        app = _ui_app_module().TagEditorApp(app_root)
        panel = app.controls_panel

        assert isinstance(app._setup_frame, BaseSetupFrame)
        assert isinstance(panel, DriverControlsPanel)
        # The suite's primary action is the full-width bottom button.
        assert app.start_btn.pack_info()["fill"] == "x"

    def test_the_mode_offers_the_driver_strings(self, app_root) -> None:
        app = _ui_app_module().TagEditorApp(app_root)
        panel = app.controls_panel
        assert panel is not None

        assert tuple(panel.mode_combo["values"]) == ("Dry Run", "Live Update")
        assert app.run_mode.get() == "Dry Run"

    def test_the_source_entry_shares_the_directory_variable(self, app_root) -> None:
        app = _ui_app_module().TagEditorApp(app_root)
        panel = app.controls_panel
        assert panel is not None

        app.folder_path.set("D:/Music")

        assert panel.source_entry.get() == "D:/Music"

    def test_the_strip_browses_through_the_shared_dialog(
        self, app_root, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Browse is the suite's dialog: initial directory and last-dir memory."""
        app = _ui_app_module().TagEditorApp(app_root)
        calls: list[dict[str, Any]] = []
        monkeypatch.setattr(
            app,
            "_browse_folder_standard",
            lambda **kwargs: calls.append(kwargs),
        )
        panel = app.controls_panel
        assert panel is not None and panel.browse_btn is not None

        panel.browse_btn.invoke()

        assert calls == [
            {
                "title": "Select Music Directory",
                "path_variable": app.folder_path,
                "save_last_dir": True,
            }
        ]


class TestLoadRun:
    """The start button loads the library through the shared run seam."""

    def test_start_processing_refuses_a_blank_folder(
        self, stubbed_dialogs: tuple[MagicMock, MagicMock]
    ) -> None:
        app = _make_shell_app()
        messagebox, _ = stubbed_dialogs

        app.start_processing()

        messagebox.showerror.assert_called_once()
        app.root.after.assert_not_called()  # no run was scheduled

    def test_start_processing_sets_the_report_and_starts_the_worker(
        self, tmp_path: Path, stubbed_dialogs: tuple[MagicMock, MagicMock], fake_thread
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)

        app.start_processing()

        messagebox.showerror.assert_not_called()
        assert app._log_path == str(tmp_path / "tag_editor_scan_log.txt")
        assert fake_thread.target == app._run_scan
        assert fake_thread.args[0] == str(tmp_path)
        app.start_btn.config.assert_called_with(state="disabled")
        app.stop_btn.config.assert_called_with(state=tkinter.NORMAL)
        app.notebook.select.assert_called_once_with("processing-tab")

    def test_the_walk_fills_the_grid_and_writes_the_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The processor's own run reaches this window's handlers end to end."""
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        monkeypatch.setattr(
            "tag_editor.core.processor.read_editable_tags",
            lambda _path: {"title": "One", "artist": None},
        )

        app._log_path = str(tmp_path / "tag_editor_scan_log.txt")
        app._run_scan(str(tmp_path), ["header\n"])

        report = (tmp_path / "tag_editor_scan_log.txt").read_text(encoding="utf-8")
        assert "header" in report
        assert "[READ]      a.mp3 (title='One')" in report, report
        assert "[SKIPPED]" not in report  # unsupported files are not rows
        assert "SUMMARY:" in report
        assert "Audio files: 1 of 2 files" in report

        # The grid fill is queued for the Tk poller, which writes it.
        app._poll_ui_updates()
        iid = str(tmp_path / "a.mp3")
        app.tree.insert.assert_called_once()
        assert app._rows[iid][1]["title"] == "One"

    def test_a_stop_request_ends_the_walk(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stop is cooperative: the walk ends after the file it is reading."""
        from tag_editor.core.processor import count_visited_files, run_scan

        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.mp3").write_bytes(b"x")
        monkeypatch.setattr(
            "tag_editor.core.processor.read_editable_tags", lambda _path: {"title": "T"}
        )
        processor = TagEditorProcessor()
        completed: list[dict[str, Any]] = []

        def _stop_after_first(*_args: Any, **_kwargs: Any) -> None:
            processor.stop()

        assert count_visited_files(tmp_path) == 2
        run_scan(
            str(tmp_path),
            on_progress=_stop_after_first,
            on_complete=lambda **kw: completed.append(kw),
            on_error=lambda message: pytest.fail(message),
            processor=processor,
        )

        assert completed[0]["processed"] == 1
        assert len(completed[0]["rows"]) == 1


class TestApplySelection:
    """The single-field edit applies through an apply run."""

    def _select(self, app: Any, path: Path, values: dict[str, str | None]) -> None:
        app.tree.selection.return_value = (str(path),)
        app._rows[str(path)] = (path, values)

    def test_no_selection_warns(
        self, tmp_path: Path, stubbed_dialogs: tuple[MagicMock, MagicMock]
    ) -> None:
        app = _make_shell_app()
        messagebox, _ = stubbed_dialogs

        app.apply_selection()

        messagebox.showwarning.assert_called_once()

    def test_an_unloaded_grid_warns(
        self, tmp_path: Path, stubbed_dialogs: tuple[MagicMock, MagicMock]
    ) -> None:
        app = _make_shell_app()
        messagebox, _ = stubbed_dialogs
        app.tree.selection.return_value = ("unknown",)

        app.apply_selection()

        messagebox.showwarning.assert_called_once()
        assert "Load the grid" in messagebox.showwarning.call_args.args[1]

    def test_the_selection_becomes_field_edits(
        self, tmp_path: Path, fake_thread: MagicMock
    ) -> None:
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        path = tmp_path / "track.mp3"
        self._select(app, path, {"title": "Old"})

        app.apply_selection()

        edits, is_dry_run, header = fake_thread.args
        assert edits == [FieldEdit(path=path, field="title", value="New")]
        assert is_dry_run is False
        assert "Single field edit: Title" in "".join(header)
        assert fake_thread.target == app._run_apply

    def test_clear_sends_none_and_dry_run_is_honoured(
        self, tmp_path: Path, fake_thread: MagicMock
    ) -> None:
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        app.clear_var.get.return_value = True
        app.value_var.get.return_value = "ignored"
        app.run_mode.get.return_value = "Dry Run"
        path = tmp_path / "track.mp3"
        self._select(app, path, {"title": "Old"})

        app.apply_selection()

        edits = fake_thread.args[0]
        assert [edit.value for edit in edits] == [None]
        assert fake_thread.args[1] is True
        assert app._log_path == str(tmp_path / "tag_editor_dry_run_log.txt")

    def test_an_invalid_field_is_refused_before_the_worker(
        self,
        tmp_path: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        fake_thread: MagicMock,
    ) -> None:
        app = _make_shell_app()
        messagebox, _ = stubbed_dialogs
        app.field_var.get.return_value = "not_a_field"
        path = tmp_path / "track.mp3"
        self._select(app, path, {})

        app.apply_selection()

        messagebox.showerror.assert_called_once()
        assert "Unsupported tag field" in messagebox.showerror.call_args.args[1]
        assert fake_thread.target is None

    def test_the_worker_applies_and_refreshes_the_grid(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The edit reaches the tag API and the row shows the new value."""
        calls: list[tuple[str, str, str | None]] = []
        monkeypatch.setattr(
            "tag_editor.core.processor.read_editable_tags",
            lambda _path: {"title": "Old"},
        )
        monkeypatch.setattr(
            "tag_editor.core.processor.write_editable_tag",
            lambda path, field, value: calls.append((path, field, value)),
        )
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        app._log_path = str(tmp_path / "tag_editor_sync_log.txt")
        path = tmp_path / "track.mp3"
        self._select(app, path, {"title": "Old"})

        app._run_apply(
            [FieldEdit(path=path, field="title", value="New")],
            False,
            ["header\n"],
        )

        assert calls == [(str(path), "title", "New")]
        report = (tmp_path / "tag_editor_sync_log.txt").read_text(encoding="utf-8")
        assert "[WRITTEN] track.mp3: title 'Old' -> 'New'" in report, report

        app._poll_ui_updates()
        app.tree.set.assert_called_once_with(str(path), "title", "New")

    def test_a_failed_edit_is_reported_and_leaves_the_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "tag_editor.core.processor.read_editable_tags",
            lambda _path: {"title": "Old"},
        )

        def _refuse(*_args: Any) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("tag_editor.core.processor.write_editable_tag", _refuse)
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        app._log_path = str(tmp_path / "tag_editor_sync_log.txt")
        path = tmp_path / "track.mp3"
        self._select(app, path, {"title": "Old"})

        app._run_apply(
            [FieldEdit(path=path, field="title", value="New")],
            False,
            ["header\n"],
        )

        report = (tmp_path / "tag_editor_sync_log.txt").read_text(encoding="utf-8")
        assert "[FAILED]" in report
        assert "Errors: 1" in report

        app._poll_ui_updates()
        app.tree.set.assert_not_called()


class TestApplyBulk:
    def test_the_bulk_operation_becomes_field_edits(
        self, tmp_path: Path, fake_thread: MagicMock
    ) -> None:
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = (str(path),)
        app._rows[str(path)] = (path, {"genre": "Rock/Pop"})

        app.apply_bulk_selection()

        edits = fake_thread.args[0]
        assert [(edit.field, edit.value) for edit in edits] == [("genre", "Rock; Pop")]
        assert "Bulk operation: Normalize Slashes" in "".join(fake_thread.args[2])

    def test_a_no_op_bulk_run_says_so(
        self, tmp_path: Path, fake_thread: MagicMock
    ) -> None:
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = (str(path),)
        app._rows[str(path)] = (path, {"genre": "Rock; Pop"})

        app.apply_bulk_selection()

        assert fake_thread.target is None
        app.overall_status.set.assert_called_with(
            "Normalize Slashes (TXXX Rule): no changes — every selected row "
            "already matches."
        )

    def test_a_validation_error_is_shown(
        self,
        tmp_path: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        fake_thread: MagicMock,
    ) -> None:
        app = _make_shell_app()
        messagebox, _ = stubbed_dialogs
        app.bulk_operation_var.get.return_value = "Swap Fields"
        app.bulk_field_var.get.return_value = "title"
        app.second_field_var.get.return_value = "title"
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = (str(path),)
        app._rows[str(path)] = (path, {})

        app.apply_bulk_selection()

        messagebox.showerror.assert_called_once()
        assert fake_thread.target is None

    def test_no_selection_warns(
        self, stubbed_dialogs: tuple[MagicMock, MagicMock]
    ) -> None:
        app = _make_shell_app()
        messagebox, _ = stubbed_dialogs

        app.apply_bulk_selection()

        messagebox.showwarning.assert_called_once()


class TestCsvImportExport:
    def test_import_builds_the_plan_and_starts_the_run(
        self,
        tmp_path: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        fake_thread: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, filedialog = stubbed_dialogs
        filedialog.askopenfilename.return_value = "edits.csv"
        plan = CsvImportPlan(
            edits=[FieldEdit(tmp_path / "a.mp3", "title", "New")],
            row_count=1,
            row_errors=["Row 2: file not found: gone.mp3"],
            ignored_columns=["cover"],
        )
        monkeypatch.setattr(_ui_app_module(), "build_import_plan", lambda *_args: plan)
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)

        app.import_csv()

        edits, _dry, header = fake_thread.args
        assert edits == plan.edits
        assert "CSV import: edits.csv" in "".join(header)
        assert app._pending_extra_entries == (
            "[SKIPPED]   CSV row: Row 2: file not found: gone.mp3\n",
        )
        assert ("CSV rows read", "1") in app._pending_extra_summary
        assert ("Ignored columns", "cover") in app._pending_extra_summary

    def test_import_reports_row_errors_after_the_run(
        self, tmp_path: Path, stubbed_dialogs: tuple[MagicMock, MagicMock]
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app = _make_shell_app()

        app._pending_warnings = ("Row 2: file not found: gone.mp3",)
        app._finish_apply(
            header=["header\n"],
            total=1,
            processed=1,
            skipped=0,
            errors=0,
            duration_secs=1.0,
            log_entries=[],
            results=[],
            changed=1,
            written=1,
        )

        app._poll_ui_updates()
        messagebox.showwarning.assert_called_once()
        assert "gone.mp3" in messagebox.showwarning.call_args.args[1]

    def test_import_requires_a_directory(
        self, stubbed_dialogs: tuple[MagicMock, MagicMock]
    ) -> None:
        app = _make_shell_app()
        messagebox, _ = stubbed_dialogs

        app.import_csv()

        messagebox.showerror.assert_called_once()

    def test_a_cancelled_import_does_nothing(
        self, stubbed_dialogs: tuple[MagicMock, MagicMock], fake_thread: MagicMock
    ) -> None:
        _, filedialog = stubbed_dialogs
        filedialog.askopenfilename.return_value = ""
        app = _make_shell_app()
        app.folder_path.get.return_value = "D:/Music"

        app.import_csv()

        assert fake_thread.target is None

    def test_import_surfaces_a_plan_error(
        self,
        tmp_path: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from audio_suite_shared.exceptions import AudioSuiteError

        _, filedialog = stubbed_dialogs
        filedialog.askopenfilename.return_value = "edits.csv"

        def _fail(*_args: Any) -> None:
            raise AudioSuiteError("CSV must contain a file column.")

        monkeypatch.setattr(_ui_app_module(), "build_import_plan", _fail)
        messagebox, _ = stubbed_dialogs
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)

        app.import_csv()

        messagebox.showerror.assert_called_once()

    def test_export_writes_the_loaded_rows(
        self,
        tmp_path: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _, filedialog = stubbed_dialogs
        filedialog.asksaveasfilename.return_value = "out.csv"
        exporter = MagicMock(return_value=1)
        monkeypatch.setattr(_ui_app_module(), "export_csv", exporter)
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        path = tmp_path / "track.mp3"
        app._rows[str(path)] = (path, {"title": "One", "artist": None})

        app.export_csv()

        rows = exporter.call_args.args[0]
        assert rows[0].path == path
        assert rows[0].values["title"] == "One"
        assert exporter.call_args.args[2] == tmp_path

    def test_export_requires_a_loaded_grid(
        self, stubbed_dialogs: tuple[MagicMock, MagicMock]
    ) -> None:
        app = _make_shell_app()
        messagebox, _ = stubbed_dialogs

        app.export_csv()

        messagebox.showwarning.assert_called_once()


class TestGridInteraction:
    def test_selecting_one_row_fills_the_form(self, tmp_path: Path) -> None:
        app = _make_shell_app()
        path = tmp_path / "track.mp3"
        app.tree.selection.return_value = (str(path),)
        app._rows[str(path)] = (path, {"title": "My Title"})

        app._on_tree_select(None)

        app.value_var.set.assert_called_once_with("My Title")
        app.clear_var.set.assert_called_once_with(False)

    def test_a_multi_row_selection_leaves_the_form_alone(self, tmp_path: Path) -> None:
        app = _make_shell_app()
        app.tree.selection.return_value = ("a", "b")

        app._on_tree_select(None)

        app.value_var.set.assert_not_called()

    def test_updating_a_row_refreshes_the_model_and_the_tree(
        self, tmp_path: Path
    ) -> None:
        app = _make_shell_app()
        path = tmp_path / "track.mp3"
        values: dict[str, str | None] = {"title": "Old"}
        app._rows[str(path)] = (path, values)

        app._update_row(
            EditResult(
                path=path,
                field="title",
                old_value="Old",
                new_value="New",
                changed=True,
                written=True,
            )
        )

        assert values["title"] == "New"
        app.tree.set.assert_called_once_with(str(path), "title", "New")

    def test_updating_an_unknown_row_is_a_no_op(self, tmp_path: Path) -> None:
        app = _make_shell_app()

        app._update_row(
            EditResult(
                path=tmp_path / "missing.mp3",
                field="title",
                old_value=None,
                new_value="New",
                changed=True,
                written=True,
            )
        )

        app.tree.set.assert_not_called()


class TestCompletionSeam:
    """The processor's completion payload lands on this window's handler."""

    @staticmethod
    def _complete(app: Any, tmp_path: Path, **overrides: Any) -> None:
        payload: dict[str, Any] = {
            "header": ["header\n"],
            "total": 4,
            "processed": 4,
            "skipped": 1,
            "errors": 0,
            "duration_secs": 65.0,
            "log_entries": ["[WRITTEN] a.mp3: title 'Old' -> 'New'\n"],
            "results": [],
            "changed": 3,
            "written": 3,
        }
        payload.update(overrides)
        app._log_path = str(tmp_path / "report.txt")
        app._finish_apply(**payload)
        app._poll_ui_updates()
        # The poller renders the finish; the shell marshals its Results-tab
        # writes, which a MagicMock root records rather than runs.
        _run_scheduled(app, "_render_completion")

    def test_the_results_panel_reports_the_shared_counters(
        self, tmp_path: Path
    ) -> None:
        app = _make_shell_app()

        self._complete(app, tmp_path)

        summary = str(app.summary_label.config.call_args.kwargs["text"])
        for fragment in ("4", "3", "1", "Files changed", "Tag edits"):
            assert fragment in summary, summary
        app.time_label.config.assert_called_once_with(text="Total Time: 01:05")

    def test_the_mode_decides_the_completion_caption(self, tmp_path: Path) -> None:
        app = _make_shell_app()
        app._run_mode = "Dry Run"

        self._complete(app, tmp_path)

        assert app.completion_label.config.call_args.kwargs["text"] == (
            "Apply Complete!"
        )

    def test_auto_end_closes_the_window(self, tmp_path: Path) -> None:
        """A driven batch blocks on this process, so Auto End must exit."""
        app = _make_shell_app()
        app.auto_end = True

        self._complete(app, tmp_path)

        app.root.after.assert_any_call(2000, app.root.destroy)

    def test_an_unknown_field_does_not_abort_the_completion(
        self, tmp_path: Path
    ) -> None:
        """A processor field the handler ignores must never raise."""
        app = _make_shell_app()

        self._complete(app, tmp_path, plugin_updates=3)

        assert (tmp_path / "report.txt").is_file(), "the completion never ran"

    def test_the_real_run_drives_the_bound_handler(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The processor's own run reaches this window's handlers end to end."""
        from tag_editor.core.processor import run_apply

        monkeypatch.setattr(
            "tag_editor.core.processor.read_editable_tags",
            lambda _path: {"title": "Old"},
        )
        app = _make_shell_app()
        app._run_mode = "Dry Run"
        app._run_folder = str(tmp_path)
        app.folder_path.get.return_value = str(tmp_path)
        app._log_path = str(tmp_path / "tag_editor_dry_run_log.txt")
        path = tmp_path / "a.mp3"
        path.write_bytes(b"x")

        run_apply(
            [FieldEdit(path=path, field="title", value="New")],
            is_dry_run=True,
            on_progress=app._on_progress,
            on_complete=lambda **kw: app._finish_apply(header=["header\n"], **kw),
            on_error=app._on_error,
            processor=app.processor,
        )
        app._poll_ui_updates()

        text = (tmp_path / "tag_editor_dry_run_log.txt").read_text(encoding="utf-8")
        assert "header" in text
        assert "[WOULD WRITE] a.mp3: title 'Old' -> 'New'" in text
        assert "SUMMARY:" in text
        assert "Tag edits: 1 planned, 0 written" in text


class TestQueuedUiUpdates:
    """A run's thread queues its widget writes; the Tk poller applies them.

    The load walk and every apply run are raw ``threading.Thread`` workers, so
    they must not call ``root.after`` or touch a widget (AGENTS.md): every
    callback the processor publishes is a queue message.
    """

    @staticmethod
    def _app() -> Any:
        app = object.__new__(_ui_app_module().TagEditorApp)
        app.root = MagicMock()
        app._ui_updates = SimpleQueue()
        app._run_thread = None
        app.stats_label = MagicMock()
        app.progress = MagicMock()
        app.file_listbox = MagicMock()
        app.start_btn = MagicMock()
        app.stop_btn = MagicMock()
        app.tree = MagicMock()
        app.summary_label = MagicMock()
        app.completion_label = MagicMock()
        app.time_label = MagicMock()
        app.notebook = MagicMock()
        app.results_frame = MagicMock()
        app.overall_status = MagicMock()
        app._rows = {}
        app._run_mode = "Dry Run"
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

        app._on_error("Not a directory: D:/music")

        app.root.after.assert_not_called()
        dialogs.showerror.assert_not_called()
        assert app._ui_updates.get_nowait() == ("error", "Not a directory: D:/music")

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
            ("complete", 7, 7, 0, 0, 65.0, (("Tag edits", "2 planned, 1 written"),))
        )

        app._poll_ui_updates()

        text = app.summary_label.config.call_args.kwargs["text"]
        assert text.startswith("Total: 7 files")
        assert "Tag edits: 2 planned, 1 written" in text
        assert app.stop_btn.config.call_args.kwargs["state"] == tkinter.DISABLED
        # ``render_completion`` records the run's folder for Open Folder.
        assert app._out_dir == "D:/music"

    def test_the_poller_fills_the_grid_from_a_queued_scan(self) -> None:
        app = self._app()
        row = TagRow(path=Path("a.mp3"), values={"title": "One"})
        app._ui_updates.put(("grid", [row]))

        app._poll_ui_updates()

        app.tree.insert.assert_called_once()
        assert app._rows[str(row.path)][1]["title"] == "One"

    def test_the_poller_raises_a_queued_error_on_the_tk_thread(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dialogs = MagicMock()
        monkeypatch.setattr(suite_app, "messagebox", dialogs)
        app = self._app()
        app._on_error("Not a directory: D:/music")

        app._poll_ui_updates()

        dialogs.showerror.assert_called_once_with("Error", "Not a directory: D:/music")
        app.start_btn.config.assert_called_once_with(state="normal")
        app.stop_btn.config.assert_called_once_with(state=tkinter.DISABLED)

    def test_the_poller_keeps_polling_while_the_run_thread_lives(self) -> None:
        app = self._app()
        app._run_thread = MagicMock()
        app._run_thread.is_alive.return_value = True

        app._poll_ui_updates()

        app.root.after.assert_called_once_with(DEFAULT_POLL_MS, app._poll_ui_updates)

    def test_a_run_builds_its_queue_and_starts_the_poller(
        self, tmp_path: Path, stubbed_dialogs, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        thread = MagicMock()
        monkeypatch.setattr(_ui_app_module(), "threading", MagicMock(Thread=thread))

        app.start_processing()

        assert isinstance(app._ui_updates, SimpleQueue)
        assert app._run_thread is thread.return_value
        app.root.after.assert_called_once_with(DEFAULT_POLL_MS, app._poll_ui_updates)
