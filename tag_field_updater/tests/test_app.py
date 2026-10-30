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
selects Dry Run, the pattern box is read in order, a bad pattern is refused
before the worker starts, and saved action groups load and save through the
shared config.
Changed in 2.2.1: covers the rebuilt window (maintenance item U1) - the three
shared tabs, the guide the Help button opens, the progress surface the worker
drives, and the directory entry and pattern box growing with the window.
Changed in 2.2.1: the bar's denominator is pinned to the unit the scan counts
(files visited), not to the supported extensions alone.
Changed in 2.2.1: covers the Run Controls strip (U3) - the mode the strip owns
and the lock a driven launch applies.
Changed in 2.2.1: covers the peer scaffold (U4) - the shared browse dialog and
its last-directory memory, the positional argv handshake, the shared
progress/completion handlers, and the run report the window writes into the
scanned folder (the file View Log opens).
"""

from __future__ import annotations

import threading
import tkinter
from collections.abc import Generator
from pathlib import Path
from tkinter import ttk
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared import ui_helpers
from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.run_outcome import read_outcome
from audio_suite_shared.ui_common import BaseSetupFrame
from audio_suite_shared.ui_driver_controls import DriverControlsPanel
from tag_field_updater.core.processor import TagProcessor


def _ui_app_module():
    """Return the app module (lazily - see the module docstring)."""
    import tag_field_updater.ui.app as app_module

    return app_module


def _make_shell_app() -> Any:
    """Build a TagFieldUpdaterApp shell with mock attributes."""
    app = object.__new__(_ui_app_module().TagFieldUpdaterApp)
    app.root = MagicMock()
    app.folder_path = MagicMock()
    app.folder_path.get.return_value = ""
    # The strip's Mode value; the shell runs live so a dry-only assertion
    # cannot pass by accident.
    app.run_mode = MagicMock()
    app.run_mode.get.return_value = "Live Update"
    # Filename-source widgets (F-01): the shell must carry them or
    # ``start_processing`` cannot ask which source was selected.
    app.filename_mode = MagicMock()
    app.filename_mode.get.return_value = False
    app.only_fill_blanks = MagicMock()
    app.only_fill_blanks.get.return_value = True
    app.patterns_text = MagicMock()
    app.action_group = MagicMock()
    app.group_combo = MagicMock()
    #: The shared Processing tab's status line.
    app.overall_status = MagicMock()
    # Shared window pieces: the notebook and the two built tabs.
    app.notebook = MagicMock()
    app.progress = MagicMock()
    app.file_listbox = MagicMock()
    app.stats_label = MagicMock()
    app.completion_label = MagicMock()
    app.time_label = MagicMock()
    app.summary_label = MagicMock()
    app._tab_processing = "processing-tab"
    app._tab_results = "results-tab"
    app._log_path = ""
    app.auto_end = False
    app.start_btn = MagicMock()
    app.stop_btn = MagicMock()
    app.processor = TagProcessor()
    app._summary_rows = ()
    app.error_logger = None
    app._launched_from_driver = False
    return app


def bound_name(callback: Any) -> str:
    """Return the method name a bound callback or a mock records."""
    return str(getattr(callback, "__name__", ""))


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
    """Replace the module's messagebox and simpledialog namespaces."""
    app_module = _ui_app_module()
    messagebox = MagicMock()
    simpledialog = MagicMock()
    monkeypatch.setattr(app_module, "messagebox", messagebox)
    monkeypatch.setattr(app_module, "simpledialog", simpledialog)
    return messagebox, simpledialog


@pytest.fixture()
def fake_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[MagicMock, None, None]:
    """Capture the scan worker thread without running it."""
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
def _neutral_argv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep pytest's own argv out of the window's handshake.

    ``__init__`` applies the Master-Driver handshake the way every peer's does
    (``cli_args.parse()`` over ``sys.argv``), and under pytest that argv is the
    test run's -- which would both fail folder validation and look like a
    driven launch, locking the strip in every test.  A test that wants a
    handshake patches both helpers itself, on top of this.
    """
    cli = _ui_app_module().cli_args
    monkeypatch.setattr(cli, "parse", lambda: _neutral_args())
    monkeypatch.setattr(cli, "was_launched_from_driver", lambda: False)


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
        assert isinstance(app.folder_path.get(), str)
        assert app.overall_status.get() == "Ready"
        # Buttons: scan enabled, stop disabled until a run starts.
        assert str(app.start_btn.cget("state")) == "normal"
        assert str(app.stop_btn.cget("state")) == "disabled"

    def test_the_window_is_a_peer_scaffold(self, app_root) -> None:
        """The app is the shared analysis/tag scaffold, not its own wiring."""
        from audio_suite_shared.tool_app_base import AnalysisTagToolApp

        app = _ui_app_module().TagFieldUpdaterApp(app_root)

        assert isinstance(app, AnalysisTagToolApp)
        assert app.TOOL_ID == "tag_field_updater"
        assert app.HELP_GUIDE.endswith(".docx")

    def test_the_rules_panel_points_at_the_guide(self, app_root) -> None:
        """The field list stays; the rules themselves live in the Help guide."""
        app = _ui_app_module().TagFieldUpdaterApp(app_root)

        texts = _labels(app.root)
        joined = "".join(texts)
        # The fields it touches are still named in the window.
        for field in ("ALBUMARTISTGENRE", "ALBUMGENRE", "ARTISTGENRE", "TIT1"):
            assert field in joined, (field, joined)
        # The duplicated rule prose is gone, replaced by a pointer.
        assert "DO NOT replace ' / '" not in joined, joined
        assert "Help guide" in joined, joined


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


def _widgets(widget: Any, kind: type) -> list[Any]:
    """Return every descendant of *widget* that is an instance of *kind*."""
    found: list[Any] = []
    for child in widget.winfo_children():
        if isinstance(child, kind):
            found.append(child)
        found.extend(_widgets(child, kind))
    return found


class TestSharedLayout:
    """The window is built on the suite's shared pieces (maintenance item U1)."""

    def test_the_window_is_three_standard_tabs(self, app_root) -> None:
        app = _ui_app_module().TagFieldUpdaterApp(app_root)

        assert isinstance(app.notebook, ttk.Notebook)
        labels = [app.notebook.tab(tab, "text").strip() for tab in app.notebook.tabs()]
        assert labels == ["1. Setup", "2. Processing", "3. Results"]

    def test_the_tabs_are_the_shared_builders(self, app_root) -> None:
        app = _ui_app_module().TagFieldUpdaterApp(app_root)

        assert isinstance(app.progress, ttk.Progressbar)
        assert isinstance(app.file_listbox, tkinter.Listbox)
        assert isinstance(app.stats_label, tkinter.Label)
        for label in (app.completion_label, app.time_label, app.summary_label):
            assert isinstance(label, tkinter.Label)

    def test_the_help_button_opens_the_registered_guide(
        self, app_root, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty help_guide would make the button a silent no-op."""
        app = _ui_app_module().TagFieldUpdaterApp(app_root)
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
        app = _ui_app_module().TagFieldUpdaterApp(app_root)
        shipped = (
            Path(__file__).resolve().parents[2]
            / "documentation"
            / "user_guides"
            / "individual_programs"
            / "tag_field_updater"
            / app.HELP_GUIDE
        )

        assert app.HELP_GUIDE.endswith("_User_Guide.docx")
        assert shipped.is_file(), f"the Help button would find no {shipped}"

    def test_a_long_path_and_pattern_list_are_usable(self, app_root) -> None:
        """The entry and the box grow; the box scrolls instead of clipping."""
        app = _ui_app_module().TagFieldUpdaterApp(app_root)

        entries = _widgets(app.root, tkinter.Entry)
        assert entries, "the Setup tab has no directory entry"
        assert int(entries[0].pack_info()["expand"]) == 1

        assert int(app.patterns_text.pack_info()["expand"]) == 1
        assert app.patterns_text.cget("yscrollcommand"), (
            "the pattern box must scroll: a long pattern list is otherwise cut off"
        )


class TestRunControlsStrip:
    """The Setup tab is the shared skeleton with the driver's strip (U3)."""

    def test_the_setup_tab_is_the_shared_skeleton(self, app_root) -> None:
        app = _ui_app_module().TagFieldUpdaterApp(app_root)
        panel = app.controls_panel

        assert isinstance(app.setup_frame, BaseSetupFrame)
        assert isinstance(panel, DriverControlsPanel)
        # The suite's primary action is the full-width bottom button, not a
        # mid-tab one beside Stop.
        assert app.start_btn.pack_info()["fill"] == "x"

    def test_the_mode_offers_the_driver_strings(self, app_root) -> None:
        app = _ui_app_module().TagFieldUpdaterApp(app_root)
        panel = app.controls_panel
        assert panel is not None

        assert tuple(panel.mode_combo["values"]) == ("Dry Run", "Live Update")
        assert app.run_mode.get() == "Dry Run"

    def test_the_source_entry_shares_the_directory_variable(self, app_root) -> None:
        app = _ui_app_module().TagFieldUpdaterApp(app_root)
        panel = app.controls_panel
        assert panel is not None

        app.folder_path.set("D:/Music")

        assert panel.source_entry.get() == "D:/Music"

    def test_a_standalone_launch_leaves_the_strip_editable(self, app_root) -> None:
        app = _ui_app_module().TagFieldUpdaterApp(app_root)
        panel = app.controls_panel
        assert panel is not None

        assert str(panel.source_entry.cget("state")) == "normal"
        assert str(panel.mode_combo.cget("state")) == "readonly"
        # Auto Start is driver-owned in both modes.
        assert str(panel.auto_start_btn.cget("state")) == "disabled"

    def test_a_driven_launch_locks_the_strip(
        self, app_root, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The driver's source and mode must not be editable mid-batch."""
        app_module = _ui_app_module()
        monkeypatch.setattr(app_module.cli_args, "parse", lambda: _neutral_args())
        monkeypatch.setattr(
            app_module.cli_args, "was_launched_from_driver", lambda: True
        )
        app = app_module.TagFieldUpdaterApp(app_root)
        panel = app.controls_panel
        assert panel is not None

        assert str(panel.source_entry.cget("state")) == "disabled"
        assert str(panel.mode_combo.cget("state")) == "disabled"
        assert panel.browse_btn is not None
        assert str(panel.browse_btn.cget("state")) == "disabled"


def _neutral_args(**overrides: Any) -> BaseCLIArgs:
    """Return the 'no handshake' args every folder tool's parser can produce."""
    args = _ui_app_module().cli_args.TagFieldUpdaterArgs()
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


class TestBrowseUsesTheSharedDialog:
    """The Browse button is the suite's, so it opens where it last looked."""

    @staticmethod
    def _spy(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
        spy = MagicMock()
        monkeypatch.setattr(ui_helpers, "browse_folder_dialog", spy)
        return spy

    def test_it_passes_the_current_path_as_the_initial_directory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spy = self._spy(monkeypatch)
        app = _make_shell_app()
        app.folder_path.get.return_value = "D:/Music"

        app._browse_folder()

        assert spy.call_args.kwargs["initial_dir"] == "D:/Music"

    def test_it_saves_the_last_directory_for_the_next_launch(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A peer remembers where it was; a raw askdirectory does not."""
        spy = self._spy(monkeypatch)
        app = _make_shell_app()

        app._browse_folder()

        assert spy.call_args.kwargs["save_last_dir"] is True
        assert spy.call_args.kwargs["path_variable"] is app.folder_path


class TestProgressSurfacing:
    """The processor's progress payload reaches the shared Processing tab."""

    def test_on_progress_marshals_onto_main_thread(self) -> None:
        """Worker threads must not touch Tk vars directly; after(0, ...) only."""
        app = _make_shell_app()

        app._on_progress(
            processed=3,
            total=10,
            skipped=1,
            errors=0,
            display_text="song.mp3",
        )

        call = app.root.after.call_args
        assert call is not None, "progress must be marshalled via root.after"
        assert call.args[0] == 0
        assert_bound(call.args[1], "_update_progress_ui", app)
        assert call.args[2:] == (3, 10, 1, 0, "song.mp3")

    def test_the_update_ui_drives_the_shared_tab(self) -> None:
        app = _make_shell_app()

        app._update_progress_ui(7, 10, 2, 1, "song.mp3")

        app.progress.__setitem__.assert_any_call("maximum", 10)
        app.progress.__setitem__.assert_any_call("value", 7)
        text = str(app.stats_label.config.call_args.kwargs["text"])
        for fragment in ("7", "2", "1"):
            assert fragment in text, text
        app.file_listbox.insert.assert_called_once()
        app.file_listbox.see.assert_called_once()


class TestStartProcessing:
    def test_empty_directory_shows_error(self, stubbed_dialogs) -> None:
        messagebox, _ = stubbed_dialogs
        app = _make_shell_app()
        app.folder_path.get.return_value = "  "

        app.start_processing()

        messagebox.showerror.assert_called_once()
        assert messagebox.showerror.call_args.args[0] == "No Directory Selected"

    def test_missing_directory_shows_error(self, stubbed_dialogs) -> None:
        messagebox, _ = stubbed_dialogs
        app = _make_shell_app()
        app.folder_path.get.return_value = str(Path("D:/nonexistent_xyz"))

        app.start_processing()

        messagebox.showerror.assert_called_once()
        assert messagebox.showerror.call_args.args[0] == "Directory Not Found"

    def test_a_file_path_shows_error(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        messagebox, _ = stubbed_dialogs
        marker = tmp_path / "file.txt"
        marker.write_text("x", encoding="utf-8")
        app = _make_shell_app()
        app.folder_path.get.return_value = str(marker)

        app.start_processing()

        assert messagebox.showerror.call_args.args[0] == "Invalid Directory"
        fake_thread.start.assert_not_called()

    def test_valid_directory_resets_and_starts(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)

        app.start_processing()

        app.file_listbox.delete.assert_called_once()
        app.progress.__setitem__.assert_any_call("value", 0)
        app.start_btn.config.assert_called_once_with(state="disabled")
        app.stop_btn.config.assert_called_once_with(state="normal")
        app.overall_status.set.assert_called_once_with("Scanning...")
        # The run reports itself on the Processing tab while it runs.
        app.notebook.select.assert_called_once_with(app._tab_processing)
        assert_bound(fake_thread.target, "_run_scan", app)
        fake_thread.start.assert_called_once_with()

    def test_the_worker_runs_the_processor_entry_point(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        """The window hands the run to ``run_scan``, not to the raw walker."""
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)

        app.start_processing()

        folder, is_dry_run, patterns, header = fake_thread.args
        assert folder == str(tmp_path)
        assert is_dry_run is False  # the shell runs Live Update
        assert patterns == ()
        assert header[0] == "TAG FIELD UPDATE REPORT\n"
        assert "LIVE UPDATE" in header[1]


class TestRunReport:
    """The run writes its report into the scanned folder, as every peer does."""

    @staticmethod
    def _run(tmp_path: Path, *, dry_run: bool) -> Any:
        app = _make_shell_app()
        app.run_mode.get.return_value = "Dry Run" if dry_run else "Live Update"
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        app._run_scan(str(tmp_path), dry_run, (), ["TAG FIELD UPDATE REPORT\n"])

        return app

    def test_the_dry_run_report_is_named_for_the_mode(self, tmp_path: Path) -> None:
        app = self._run(tmp_path, dry_run=True)

        report = tmp_path / "tag_field_updater_dry_run_log.txt"
        assert report.is_file(), f"no run report at {report}"
        assert app._log_path == str(report)
        text = report.read_text(encoding="utf-8")
        assert "TAG FIELD UPDATE REPORT" in text
        assert "notes.txt" in text, text
        assert "SUMMARY:" in text, text

    def test_the_live_report_is_named_for_its_mode(self, tmp_path: Path) -> None:
        """The two modes must not overwrite each other's report."""
        app = self._run(tmp_path, dry_run=False)

        report = tmp_path / "tag_field_updater_sync_log.txt"
        assert report.is_file()
        assert app._log_path == str(report)

    def test_view_log_opens_the_report_the_run_wrote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        opened: list[str] = []
        monkeypatch.setattr(ui_helpers, "open_log_file", opened.append)
        app = self._run(tmp_path, dry_run=True)

        app._open_log()

        assert opened == [app._log_path]


class TestStopProcessing:
    def test_requests_processor_stop(self) -> None:
        app = _make_shell_app()
        processor = MagicMock()
        app.processor = processor  # type: ignore[assignment]

        app.stop_processing()

        processor.stop.assert_called_once()
        app.overall_status.set.assert_called_once_with("Stopping...")


class TestCompletionSeam:
    """The processor's completion payload lands on the shared handlers."""

    @staticmethod
    def _complete(app: Any, **overrides: Any) -> None:
        payload: dict[str, Any] = {
            "header": ["header\n"],
            "total": 10,
            "processed": 10,
            "skipped": 2,
            "errors": 1,
            "duration_secs": 65.0,
            "log_entries": ["[UNCHANGED] a.mp3\n"],
            "updated": 7,
            "audio_files": 8,
        }
        payload.update(overrides)
        app._finish_run(**payload)

    def test_the_results_panel_reports_the_shared_counters(
        self, tmp_path: Path
    ) -> None:
        app = _make_shell_app()
        app._log_path = str(tmp_path / "report.txt")

        self._complete(app)
        # The base writes the report and schedules the panel update.
        app._update_ui_on_complete(10, 7, 2, 1, 1, 5, list(app._summary_extras()))

        summary = str(app.summary_label.config.call_args.kwargs["text"])
        for fragment in ("10", "7", "2", "1", "Files updated"):
            assert fragment in summary, summary
        app.time_label.config.assert_called_once_with(text="Total Time: 01:05")
        assert app.completion_label.config.call_args.kwargs["text"] == (
            "Tag Update Complete!"
        )

    def test_the_mode_decides_the_completion_caption(self, tmp_path: Path) -> None:
        app = _make_shell_app()
        app.run_mode.get.return_value = "Dry Run"
        app._log_path = str(tmp_path / "report.txt")

        self._complete(app)
        app._update_ui_on_complete(10, 7, 2, 1, 0, 0)

        assert app.completion_label.config.call_args.kwargs["text"] == (
            "Scan Complete!"
        )

    def test_auto_end_closes_the_window(self, tmp_path: Path) -> None:
        """A driven batch blocks on this process, so Auto End must exit."""
        app = _make_shell_app()
        app._log_path = str(tmp_path / "report.txt")
        app.auto_end = True

        self._complete(app)
        app._update_ui_on_complete(10, 7, 2, 1, 0, 0)

        app.root.after.assert_any_call(2000, app.root.destroy)

    def test_an_unknown_field_does_not_abort_the_completion(
        self, tmp_path: Path
    ) -> None:
        """A processor field the handler ignores must never raise."""
        app = _make_shell_app()
        app._log_path = str(tmp_path / "report.txt")

        self._complete(app, plugin_updates=3)

        assert app._summary_rows, "the completion never ran"

    def test_the_real_run_drives_the_bound_handler(self, tmp_path: Path) -> None:
        """The processor's own run reaches this window's handlers end to end.

        The static locks prove the payloads agree; only driving ``run_scan``
        into the bound handler proves the report the run writes is the one this
        window asked for.
        """
        from tag_field_updater.core.processor import run_scan

        app = _make_shell_app()
        app.run_mode.get.return_value = "Dry Run"
        (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
        (tmp_path / "broken.mp3").write_bytes(b"not an MPEG stream")
        app._log_path = str(tmp_path / "report.txt")

        run_scan(
            str(tmp_path),
            is_dry_run=True,
            on_progress=app._on_progress,
            on_complete=lambda **kw: app._finish_run(header=["header\n"], **kw),
            on_error=app._on_error,
            processor=app.processor,
        )

        text = (tmp_path / "report.txt").read_text(encoding="utf-8")
        assert "header" in text
        assert "notes.txt" in text
        assert "SUMMARY:" in text
        assert "Audio files" in text, text
        assert app._summary_rows


class TestDriverHandshake:
    """The window applies the driver's argv itself, as every peer does."""

    def test_the_driver_arguments_reach_the_strip(
        self, monkeypatch: pytest.MonkeyPatch, app_root, fake_thread, tmp_path: Path
    ) -> None:
        app_module = _ui_app_module()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: _neutral_args(
                folder_path=str(tmp_path),
                live_mode=True,
                auto_start=False,
                auto_end=True,
                clear_logs=True,
                parallel_run=True,
            ),
        )
        monkeypatch.setattr(
            app_module.cli_args, "was_launched_from_driver", lambda: True
        )

        app = app_module.TagFieldUpdaterApp(app_root)

        assert app.run_mode.get() == "Live Update"
        assert app.auto_start_var.get() is False
        assert app.auto_end_var.get() is True
        assert app.clear_logs_var.get() is True
        assert app.parallel_var.get() is True
        assert app.auto_end is True
        assert app._launched_from_driver is True
        assert app.folder_path.get() == str(tmp_path)
        fake_thread.start.assert_not_called()

    def test_auto_start_schedules_the_run(
        self, monkeypatch: pytest.MonkeyPatch, app_root, tmp_path: Path
    ) -> None:
        app_module = _ui_app_module()
        monkeypatch.setattr(
            app_module.cli_args,
            "parse",
            lambda: _neutral_args(folder_path=str(tmp_path), auto_start=True),
        )
        monkeypatch.setattr(
            app_module.cli_args, "was_launched_from_driver", lambda: True
        )

        scheduled = MagicMock()
        monkeypatch.setattr(app_root, "after", scheduled)

        app = app_module.TagFieldUpdaterApp(app_root)

        # The shared handshake schedules the scan rather than starting it
        # inside __init__, so the window is drawn first.
        runs = [call for call in scheduled.mock_calls if call.args[:1] == (1500,)]
        assert runs, scheduled.mock_calls
        assert bound_name(runs[0].args[1]) == "start_processing"
        assert app.folder_path.get() == str(tmp_path)


class TestRunNote:
    """A finished run leaves its skipped and failed files where a batch sees them."""

    @staticmethod
    def _finish(app: Any, **overrides: Any) -> None:
        payload: dict[str, Any] = {
            "header": ["header\n"],
            "total": 10,
            "processed": 10,
            "skipped": 0,
            "errors": 0,
            "duration_secs": 1.0,
            "log_entries": [],
            "updated": 0,
            "audio_files": 0,
        }
        payload.update(overrides)
        app._finish_run(**payload)

    def test_skipped_and_failed_files_are_reported(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_shell_app()
        app._log_path = str(tmp_path / "report.txt")

        self._finish(app, skipped=2, errors=2)

        assert read_outcome("tag_field_updater") == (
            "2 of 10 files could not be updated; 2 of 10 files were skipped "
            "(unsupported format or no readable tags)"
        )

    def test_a_clean_scan_reports_nothing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_shell_app()
        app._log_path = str(tmp_path / "report.txt")

        self._finish(app)

        assert read_outcome("tag_field_updater") == ""

    def test_a_later_clean_scan_clears_an_earlier_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("AUDIOSUITE_LOG_DIR", str(tmp_path))
        app = _make_shell_app()
        app._log_path = str(tmp_path / "report.txt")
        self._finish(app, errors=1)
        assert read_outcome("tag_field_updater") == "1 of 10 files could not be updated"

        self._finish(app)

        assert read_outcome("tag_field_updater") == ""


class TestMain:
    def test_main_without_directory_enters_the_loop(
        self,
        monkeypatch: pytest.MonkeyPatch,
        app_root,
        fake_thread,
    ) -> None:
        import sys

        app_module = _ui_app_module()
        monkeypatch.setattr(tkinter, "Tk", lambda: app_root)
        monkeypatch.setattr(app_module, "bootstrap_theme", MagicMock())
        monkeypatch.setattr(sys, "argv", ["tag_field_updater"])
        monkeypatch.setattr(app_module.cli_args, "parse", lambda: _neutral_args())
        loop = MagicMock()
        monkeypatch.setattr(app_root, "mainloop", loop)

        app_module.main()

        loop.assert_called_once_with()
        fake_thread.start.assert_not_called()  # no auto-start without a directory

    def test_main_rejects_missing_directory(
        self,
        monkeypatch: pytest.MonkeyPatch,
        app_root,
        stubbed_dialogs,
    ) -> None:
        app_module = _ui_app_module()
        monkeypatch.setattr(tkinter, "Tk", lambda: app_root)
        monkeypatch.setattr(app_module, "bootstrap_theme", MagicMock())

        with pytest.raises(SystemExit) as exit_exc:
            app_module.main(directory=str(Path("D:/definitely_not_a_dir_12345")))

        assert exit_exc.value.code == 1

    def test_main_prepopulates_and_starts(
        self,
        monkeypatch: pytest.MonkeyPatch,
        app_root,
        stubbed_dialogs,
        fake_thread,
        tmp_path: Path,
    ) -> None:
        app_module = _ui_app_module()
        app_cls = app_module.TagFieldUpdaterApp
        monkeypatch.setattr(tkinter, "Tk", lambda: app_root)
        monkeypatch.setattr(app_module, "bootstrap_theme", MagicMock())
        monkeypatch.setattr(app_root, "mainloop", MagicMock())
        captured: dict[str, Any] = {}
        real_init = app_cls.__init__

        def _intercept_init(self: Any, tk_root: Any, **kwargs: Any) -> None:
            real_init(self, tk_root, **kwargs)
            captured["app"] = self

        monkeypatch.setattr(app_cls, "__init__", _intercept_init)

        app_module.main(directory=str(tmp_path))

        assert captured["app"].folder_path.get() == str(tmp_path)
        assert_bound(fake_thread.target, "_run_scan", captured["app"])
        fake_thread.start.assert_called_once_with()

    def test_main_rejects_a_file_path(
        self,
        monkeypatch: pytest.MonkeyPatch,
        app_root,
        stubbed_dialogs,
        tmp_path: Path,
    ) -> None:
        """A path that exists but is not a directory exits 1 without scanning."""
        app_module = _ui_app_module()
        marker = tmp_path / "file.txt"
        marker.write_text("x", encoding="utf-8")
        monkeypatch.setattr(tkinter, "Tk", lambda: app_root)
        monkeypatch.setattr(app_module, "bootstrap_theme", MagicMock())
        started = threading.Event()
        threading_ns = MagicMock()
        threading_ns.Thread = lambda *a, **k: started.set()  # pragma: no cover
        monkeypatch.setattr(app_module, "threading", threading_ns)

        with pytest.raises(SystemExit) as exit_exc:
            app_module.main(directory=str(marker))

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
    def test_enabling_the_mode_selects_dry_run(self) -> None:
        """A mis-parse must not be written because the mode was switched on."""
        app = _make_shell_app()
        app.filename_mode = MagicMock()
        app.filename_mode.get.return_value = True
        app.run_mode = MagicMock()

        app._on_filename_mode_toggled()

        app.run_mode.set.assert_called_once_with("Dry Run")
        assert "dry run" in app.overall_status.set.call_args.args[0].lower()

    def test_disabling_the_mode_leaves_the_choice_alone(self) -> None:
        app = _make_shell_app()
        app.filename_mode = MagicMock()
        app.filename_mode.get.return_value = False
        app.run_mode = MagicMock()

        app._on_filename_mode_toggled()

        app.run_mode.set.assert_not_called()

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
        app.folder_path.get.return_value = str(tmp_path)

        app.start_processing()

        assert app.processor.patterns == ("%disc%-%track% %artist% - %title%",)
        assert app.processor.only_fill_blanks is True
        fake_thread.start.assert_called_once_with()

    def test_an_empty_pattern_box_does_not_start(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app = _filename_shell("\n  \n")
        app.folder_path.get.return_value = str(tmp_path)

        app.start_processing()

        messagebox.showwarning.assert_called_once()
        fake_thread.start.assert_not_called()
        assert app.processor.patterns == ()

    def test_an_invalid_pattern_is_reported_before_scanning(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app = _filename_shell("%artst% - %title%\n")
        app.folder_path.get.return_value = str(tmp_path)

        app.start_processing()

        messagebox.showerror.assert_called_once()
        assert "artst" in messagebox.showerror.call_args.args[1]
        fake_thread.start.assert_not_called()
        assert app.processor.patterns == ()

    def test_the_slash_rule_is_restored_when_the_mode_is_off(
        self, stubbed_dialogs, fake_thread, tmp_path: Path
    ) -> None:
        app = _make_shell_app()
        app.folder_path.get.return_value = str(tmp_path)
        app.processor.use_filename_patterns(("%artist% - %title%",))

        app.start_processing()

        assert app.processor.patterns == ()
        fake_thread.start.assert_called_once_with()


class TestActionGroupsInTheGui:
    def test_saving_refuses_an_empty_pattern_box(self, stubbed_dialogs) -> None:
        messagebox, _ = stubbed_dialogs
        app = _filename_shell("\n")

        app.save_action_group()

        messagebox.showwarning.assert_called_once()

    def test_saving_stores_the_box_under_the_chosen_name(
        self, stubbed_dialogs, isolated_config: Path
    ) -> None:
        messagebox, simpledialog = stubbed_dialogs
        simpledialog.askstring.return_value = "Bandcamp"
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
        app.run_mode.set.assert_called_once_with("Dry Run")

    def test_loading_a_group_that_vanished_warns(
        self, stubbed_dialogs, isolated_config: Path
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app = _filename_shell()
        app.action_group.get.return_value = "Gone"

        app.load_action_group()

        messagebox.showwarning.assert_called_once()
        app.patterns_text.insert.assert_not_called()
