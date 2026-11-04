"""One batch shell, locked against every tool that has adopted it.

PLAN_2026-11-03_2.4.3_structure.md WP-8 replaces eighteen hand-written window
composers with one ``SuiteApp``.  This module is the contract that migration
keeps: for every adopter it builds the *real* window (only the process edge —
bootstrap, CLI parsing, the restored last directory, the persisted settings —
is stubbed) and reads the widgets back, rather than asserting that a class
calls a builder.

What is locked, and why each one is not visible to another check:

* the notebook carries the tool's declared tabs, so a tool cannot quietly keep a
  private second shell beside the shared one;
* the Processing and Results tabs come from the shared builders, so a tool that
  hand-rolls its own progress/results wiring fails here;
* the Help / View Log / Open Folder buttons actually reach the shell's helpers
  (invoked, not inspected through ``cget("command")``, which is a Tcl name);
* the run-controls strip still exposes Mode / Auto Start / Auto End, the
  documented controls the migration must not move or rename;
* the tool's title is shown once — a shell that adds its own title beside the
  Setup tab's would render the name twice;
* the shell receives the tool's manifest identity, so the window, log file and
  saved geometry stay the tool's own;
* a finished run writes the report View Log opens, read back from disk, so a
  tool that only remembers a path fails here.

``MIGRATED`` is frozen.  A newly migrated tool must be added deliberately (the
plan migrates one tool per commit), and a tool that drifts back to its own
``_build_ui`` fails the last test instead of passing silently.

Each adopter may need its own *process edge* stubs, because the tools differ in
where they read it: the converter parses its launcher argv inside the
constructor, the reorganiser receives it as keyword arguments and reads its
persisted settings on construction.  Those stubs are named in ``_stub_edges``
and nowhere else, so a tool cannot opt out of an assertion by stubbing it.

Changed in 2.4.3: initial version (WP-8); WP-8 order #2 adds the reorganiser.
Changed in 2.4.3: adds the run-report lock — the View Log defect fix's lesson is
that the pointer, not the file, is what a test usually asserts (D-16).
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterator
from pathlib import Path
from tkinter import ttk
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from audio_suite_shared import suite_app
from file_reorganizer import app as reorganizer_app
from file_reorganizer.app import FileReorganizerApp
from file_reorganizer.core.engine import ReorganizerStats
from music_format_converter import app as converter_app
from music_format_converter.app import MusicFormatConverterApp
from music_format_converter.utils.cli_args import ConverterArgs

#: The tools that have adopted the shared shell, in migration order.
MIGRATED: tuple[type[suite_app.SuiteApp], ...] = (
    MusicFormatConverterApp,
    FileReorganizerApp,
)
MIGRATED_NAMES: tuple[str, ...] = tuple(cls.__name__ for cls in MIGRATED)


def _stub_converter_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the converter's launcher parse."""
    monkeypatch.setattr(converter_app.cli_args, "parse", lambda: ConverterArgs())


def _stub_reorganizer_edges(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub the reorganiser's persisted settings (it reads them on construction)."""
    monkeypatch.setattr(
        reorganizer_app,
        "load_settings",
        lambda: {
            "dest_dir": "",
            "action": "copy",
            "specific_pattern": "specific",
            "various_pattern": "various",
        },
    )


#: Process-edge stubs per adopter; a tool with none still gets the shared ones.
_STUB_EDGES: dict[type[suite_app.SuiteApp], Callable[[pytest.MonkeyPatch], None]] = {
    MusicFormatConverterApp: _stub_converter_edges,
    FileReorganizerApp: _stub_reorganizer_edges,
}


def _complete_converter_run(app: MusicFormatConverterApp, tmp_path: Path) -> None:
    """Drive the converter's completion: it serialises the report there."""
    app._log_path = str(tmp_path / "conversion_live_log_mp3.txt")
    app._on_complete(
        header=["MUSIC FORMAT CONVERSION REPORT\n", "=" * 60 + "\n"],
        delete=False,
        total=1,
        processed=1,
        converted=1,
        skipped=0,
        errors=0,
        duration_secs=1.0,
        log_entries=["song.mp3 -> song.flac\n"],
        output_dir=str(tmp_path),
    )


def _complete_reorganizer_run(app: FileReorganizerApp, tmp_path: Path) -> None:
    """Drive the reorganiser's completion through ``_finish``."""
    app._log_path = str(tmp_path / "reorganizer_sync_log.txt")
    app._log_entries = ["Artist/Album/01 a.mp3\n"]
    app.stats = ReorganizerStats(files_scanned=1, files_processed=1)
    app._finish()


#: How each adopter reaches the report write at the end of a run.
_RUN_REPORTS: dict[type[suite_app.SuiteApp], Callable[[Any, Path], None]] = {
    MusicFormatConverterApp: _complete_converter_run,
    FileReorganizerApp: _complete_reorganizer_run,
}


def _walk(widget: tk.Misc) -> Iterator[tk.Misc]:
    """Every widget at or under *widget*."""
    yield widget
    for child in widget.winfo_children():
        yield from _walk(child)


@pytest.fixture
def window(
    request: pytest.FixtureRequest,
    root: tk.Tk,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[SimpleNamespace]:
    """Build one migrated tool's window with only the process edge stubbed.

    The helpers the header buttons must reach are replaced with recorders
    *before* construction: the shell binds them while building, so patching
    afterwards would measure nothing.
    """
    cls: type[suite_app.SuiteApp] = request.param
    calls = {"help": 0, "log": 0, "folder": 0}
    bootstrapped: dict[str, Any] = {}

    def _bootstrap(
        the_root: tk.Tk,
        title: str,
        window_key: str,
        program_name: str,
        **_kwargs: Any,
    ) -> tuple[MagicMock, None]:
        bootstrapped.update(
            root=the_root,
            title=title,
            window_key=window_key,
            program_name=program_name,
        )
        return MagicMock(), None

    def _record(name: str) -> Any:
        def _recorded(_self: object) -> None:
            calls[name] += 1

        return _recorded

    monkeypatch.setattr(suite_app, "bootstrap_tool_app", _bootstrap)
    monkeypatch.setattr(cls, "_open_help", _record("help"))
    monkeypatch.setattr(cls, "_open_log", _record("log"))
    monkeypatch.setattr(cls, "_open_folder", _record("folder"))
    # Both tools import the same module object, so one patch covers the pair.
    monkeypatch.setattr(reorganizer_app.suite_config, "load_last_directory", lambda: "")
    stub_edges = _STUB_EDGES.get(cls)
    if stub_edges is not None:
        stub_edges(monkeypatch)

    app = cls(root)
    try:
        yield SimpleNamespace(app=app, cls=cls, calls=calls, bootstrapped=bootstrapped)
    finally:
        app._closing = True
        poll_id = getattr(app, "_poll_id", "")
        if poll_id:
            app.root.after_cancel(poll_id)
            app._poll_id = ""
        for frame in (app.setup_frame, app.processing_frame, app.results_frame):
            frame.destroy()


@pytest.mark.parametrize("window", MIGRATED, ids=MIGRATED_NAMES, indirect=True)
def test_the_notebook_carries_the_tools_declared_tabs(
    window: SimpleNamespace,
) -> None:
    notebook: ttk.Notebook = window.app.notebook
    labels = tuple(
        str(notebook.tab(index, "text")) for index in range(len(notebook.tabs()))
    )
    assert labels == window.cls.tab_labels


@pytest.mark.parametrize("window", MIGRATED, ids=MIGRATED_NAMES, indirect=True)
def test_the_progress_and_results_tabs_are_the_shared_builders(
    window: SimpleNamespace,
) -> None:
    app = window.app
    assert isinstance(app.progress, ttk.Progressbar)
    assert isinstance(app.file_listbox, tk.Listbox)
    assert isinstance(app.summary_label, tk.Label)
    assert isinstance(app.time_label, tk.Label)
    assert str(app.completion_label.cget("text")) == window.cls.completion_text


@pytest.mark.parametrize("window", MIGRATED, ids=MIGRATED_NAMES, indirect=True)
def test_the_header_buttons_reach_the_shell_helpers(
    window: SimpleNamespace,
) -> None:
    buttons = {
        str(widget.cget("text")): widget
        for widget in _walk(window.app.root)
        if isinstance(widget, tk.Button)
    }
    for text in ("Help", "View Log", "Open Folder"):
        assert text in buttons, f"{window.cls.__name__} has no {text!r} button"
        buttons[text].invoke()
    assert window.calls == {"help": 1, "log": 1, "folder": 1}


@pytest.mark.parametrize("window", MIGRATED, ids=MIGRATED_NAMES, indirect=True)
def test_the_run_controls_strip_exposes_mode_start_and_end(
    window: SimpleNamespace,
) -> None:
    panel = window.app.controls_panel
    assert panel is not None, "the Setup tab no longer embeds the run-controls strip"
    assert panel.mode_combo is not None
    assert panel.auto_start_btn is not None
    assert panel.auto_end_btn is not None


@pytest.mark.parametrize("window", MIGRATED, ids=MIGRATED_NAMES, indirect=True)
def test_the_tool_title_is_shown_once(window: SimpleNamespace) -> None:
    titles = [
        widget
        for widget in _walk(window.app.root)
        if isinstance(widget, tk.Label) and str(widget.cget("text")) == window.cls.title
    ]
    assert len(titles) == 1, (
        f"{window.cls.__name__} shows its title {len(titles)} times"
    )


@pytest.mark.parametrize("window", MIGRATED, ids=MIGRATED_NAMES, indirect=True)
def test_the_shell_is_given_the_tools_identity(window: SimpleNamespace) -> None:
    assert window.bootstrapped["root"] is window.app.root
    assert window.bootstrapped["title"] == window.cls.title
    assert window.bootstrapped["window_key"] == window.cls.window_key
    assert window.bootstrapped["program_name"] == window.cls.program_name


@pytest.mark.parametrize("window", MIGRATED, ids=MIGRATED_NAMES, indirect=True)
def test_a_finished_run_leaves_a_report_the_log_button_can_open(
    window: SimpleNamespace, tmp_path: Path
) -> None:
    """View Log must open a file the run wrote, never an empty pointer.

    The defect this locks: the reorganiser finished a live copy with
    ``_log_path`` empty, so the button answered "No log file available yet".
    The assertion is on the artefact, so a writer that only assigns fields
    fails, and so does a completion that writes to the diagnostic log instead.
    """
    drive = _RUN_REPORTS[window.cls]
    drive(window.app, tmp_path)

    report = Path(window.app._log_path)
    assert report.parent == tmp_path, "a run publishes its report in the run's folder"
    assert report.is_file(), f"{window.cls.__name__} finished without writing a report"
    assert "SUMMARY:" in report.read_text(encoding="utf-8")


def test_every_migrated_tool_has_a_run_report_drive() -> None:
    """A newly migrated tool must add its completion drive deliberately."""
    assert set(_RUN_REPORTS) == set(MIGRATED)


def test_the_migrated_table_is_frozen() -> None:
    """Only the tools the plan has migrated adopt the shell, and they keep it."""
    assert MIGRATED_NAMES == ("MusicFormatConverterApp", "FileReorganizerApp")
    for cls in MIGRATED:
        assert issubclass(cls, suite_app.SuiteApp)
        assert "_build_setup_tab" in cls.__dict__, (
            f"{cls.__name__} declares no settings panel for the shell to host"
        )
        assert "_build_ui" not in cls.__dict__, (
            f"{cls.__name__} builds its own shell; the shared shell owns the notebook"
        )
