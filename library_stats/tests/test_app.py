"""
tests/test_app.py - unit tests for LibraryStatsApp (GUI dashboard).

Stage 3 item D2 (audit A4): ``library_stats/app.py`` is the largest GUI gap
(342 statements at 12%). The tests drive the scan / export / completeness
flows through the app object against the **real core engine**: the walk +
aggregation of ``file_processor.scan_directory``, the completeness analysis
and its CSV/JSON writers, and the ``LibraryCache`` SQLite backend (always)
run for real; only the per-file tag readers are mocked, matching the
established ``test_file_processor.py`` convention. The constructor runs on a
withdrawn ``Toplevel`` off the shared hidden Tk root - no real ``tk.Tk()``.

Chart rendering (the ``HAVE_MPL`` block) is not exercised because matplotlib
is not a declared dependency of this suite; the graceful no-matplotlib branch
of ``_update_charts`` is covered via the flows instead.
"""

from __future__ import annotations

import csv
import json
import tkinter
from collections.abc import Generator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

import library_stats.app as app_module
from library_stats.core.completeness import (
    TAG_FIELDS,
    analyse_completeness,
)
from library_stats.core.file_processor import StatsReport, _FileTags, scan_directory
from library_stats.library_cache import LibraryCache


@pytest.fixture()
def app_root(root: tkinter.Tk) -> Generator[tkinter.Toplevel, None, None]:
    """A fresh withdrawn ``Toplevel`` off the shared hidden Tk root."""
    top = tkinter.Toplevel(root)
    top.withdraw()
    try:
        yield top
    finally:
        top.destroy()


@pytest.fixture()
def fake_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralise the suite-config directory memory during the test."""
    monkeypatch.setattr(app_module.suite_config, "load_last_directory", lambda: "")
    monkeypatch.setattr(app_module.suite_config, "save_last_directory", MagicMock())


@pytest.fixture()
def isolated_cache(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> LibraryCache:
    """Bind the app's default-path cache constructor to a scratch database."""
    cache = LibraryCache(str(tmp_path / "library_cache.db"))

    def _factory(cache_path: str | Path | None = None) -> LibraryCache:
        assert cache_path is None, "the app must use the default-path constructor"
        return cache

    monkeypatch.setattr(app_module, "LibraryCache", _factory)
    return cache


def _make_app(
    app_root: tkinter.Toplevel, isolated_cache: LibraryCache
) -> app_module.LibraryStatsApp:
    return app_module.LibraryStatsApp(app_root)


@pytest.fixture()
def app(
    app_root: tkinter.Toplevel, fake_config: None, isolated_cache: LibraryCache
) -> app_module.LibraryStatsApp:
    """The real app on an isolated root, config and cache."""
    return _make_app(app_root, isolated_cache)


@pytest.fixture()
def library(tmp_path: Path) -> Path:
    """A two-file ``.mp3`` library (walked by the real engine)."""
    (tmp_path / "a.mp3").write_bytes(b"\x00" * 8)
    (tmp_path / "b.mp3").write_bytes(b"\x00" * 8)
    return tmp_path


_A_TAGS = _FileTags(
    artist_album=("Alice", "Sunnydays"),
    album_artist="Alice",
    bpm=128,
    key="Cm",
    genre="House",
    mood="Uplifting",
    tempo_marking="Andante",
    year=2008,
)

_EMPTY_TAGS = _FileTags(
    artist_album=None,
    album_artist=None,
    bpm=None,
    key=None,
    genre=None,
    mood=None,
    tempo_marking=None,
    year=None,
)


@pytest.fixture()
def scan_reads(monkeypatch: pytest.MonkeyPatch, library: Path) -> None:
    """Canned single-pass reads: one fully tagged file, one untagged."""
    tags = {str(library / "a.mp3"): _A_TAGS, str(library / "b.mp3"): _EMPTY_TAGS}

    monkeypatch.setattr(
        "library_stats.core.file_processor._read_file_tags",
        lambda path: tags[str(Path(path))],
    )


@pytest.fixture()
def export_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Canned per-reader values so real ``export_csv`` writes every row.

    ``export_csv`` re-reads each file through the named reader methods; on
    garbage test bytes they would raise and the row would be skipped, so this
    fixture greys them the same way ``test_file_processor`` does.
    """
    names = (
        "read_artist_album",
        "read_album_artist",
        "read_bpm",
        "read_key",
        "read_genre",
        "read_mood",
        "read_tempo_marking",
        "read_tags_raw",
    )
    for name in names:
        monkeypatch.setattr(
            f"library_stats.core.file_processor.{name}",
            lambda full: None,
        )


@pytest.fixture()
def engine_report(
    library: Path, scan_reads: None, isolated_cache: LibraryCache
) -> StatsReport:
    """A real ``StatsReport`` from the real engine, cache isolated off."""
    return scan_directory(str(library), use_cache=False)


@pytest.fixture()
def stubbed_dialogs(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[tuple[MagicMock, MagicMock], None, None]:
    """Replace the app module's messagebox and filedialog bindings."""
    messagebox = MagicMock()
    filedialog = MagicMock()
    monkeypatch.setattr(app_module, "messagebox", messagebox)
    monkeypatch.setattr(app_module, "filedialog", filedialog)
    return messagebox, filedialog


def assert_bound(callback: Any, name: str, app: app_module.LibraryStatsApp) -> None:
    """Assert *callback* is the bound ``*name*`` method of *app*.

    Bound methods are fresh objects per attribute access, so they must be
    compared via ``__self__`` / ``__name__``, never by identity.
    """
    assert getattr(callback, "__self__", None) is app
    assert callback.__name__ == name


def _patch_after(
    app: app_module.LibraryStatsApp, monkeypatch: pytest.MonkeyPatch
) -> MagicMock:
    """Capture what the worker schedules onto the main thread."""
    after = MagicMock()
    monkeypatch.setattr(app.root, "after", after)
    return after


class TestInitialState:
    def test_summary_tabs_and_buttons(self, app: app_module.LibraryStatsApp) -> None:
        assert app.folder_path.get() == ""
        assert app._report is None
        assert app._completeness_report is None
        assert app._scanning is False
        assert app._use_cache.get() is True
        assert str(app.root.title()) == "Library Statistics Dashboard"
        tabs = [app._notebook.tab(i, "text") for i in range(4)]
        assert tabs == ["Summary", "Charts", "Missing Data", "Completeness"]
        # Stat cards render the placeholder until the first scan.
        assert app._summary_labels["total_files"].cget("text") == "\u2014"
        assert str(app._export_btn.cget("state")) == "disabled"
        assert str(app._comp_csv_btn.cget("state")) == "disabled"
        assert str(app._comp_json_btn.cget("state")) == "disabled"
        assert app._status_var.get().startswith("Ready.")

    def test_preset_folder_schedules_auto_scan(
        self,
        app_root: tkinter.Toplevel,
        isolated_cache: LibraryCache,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        monkeypatch.setattr(
            app_module.suite_config, "load_last_directory", lambda: str(tmp_path)
        )
        after = MagicMock()
        monkeypatch.setattr(app_root, "after", after)
        app = _make_app(app_root, isolated_cache)
        assert app.folder_path.get() == str(tmp_path)
        call = after.call_args
        assert call is not None
        assert call.args[0] == 500
        assert_bound(call.args[1], "_start_scan", app)


class TestBrowse:
    def test_browse_sets_and_saves(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, filedialog = stubbed_dialogs
        filedialog.askdirectory.return_value = str(Path("D:/Music"))

        app._browse()

        assert app.folder_path.get() == str(Path("D:/Music"))
        app_module.suite_config.save_last_directory.assert_called_once_with(
            str(Path("D:/Music"))
        )
        messagebox.showwarning.assert_not_called()

    def test_cancelled_browse_keeps_path(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        _, filedialog = stubbed_dialogs
        filedialog.askdirectory.return_value = ""

        app._browse()

        assert app.folder_path.get() == ""


class TestScanValidation:
    def test_invalid_folder_warns_before_scanning(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app.folder_path.set(str(Path("D:/nonexistent_lib")))

        app._start_scan()

        messagebox.showwarning.assert_called_once()
        assert app._scanning is False

    def test_refresh_invalid_folder_warns(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, _ = stubbed_dialogs

        app._start_refresh()

        messagebox.showwarning.assert_called_once()


class TestScanFlow:
    """Real engine (walk + aggregation + SQLite cache), mocked tag reads."""

    def test_full_scan_flow_renders_dashboard(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        after = _patch_after(app, monkeypatch)
        fake_threading = MagicMock()
        monkeypatch.setattr(app_module, "threading", fake_threading)
        app.folder_path.set(str(library))
        app._use_cache.set(False)

        app._start_scan(refresh=False)

        assert app._scanning is True
        assert str(app._scan_btn.cget("state")) == "disabled"
        assert app._status_var.get().startswith("Scanning...")
        thread = fake_threading.Thread
        assert_bound(thread.call_args.kwargs["target"], "_do_scan", app)
        thread.return_value.start.assert_called_once()

        # Run the worker directly (no mainloop): this is the real engine.
        app._do_scan(str(library), refresh=False)

        assert app.root.after.call_args is not None
        assert_bound(app.root.after.call_args.args[1], "_on_scan_complete", app)
        report, completeness = app.root.after.call_args.args[2:]
        assert report.total_files == 2

        app._on_scan_complete(report, completeness)

        assert app._report is report
        assert app._scanning is False
        assert str(app._export_btn.cget("state")) == "normal"
        del after
        assert app._summary_labels["total_files"].cget("text") == "2"
        assert ".mp3" in app._fmt_text.get("1.0", "end")
        assert "Minor" in app._km_text.get("1.0", "end")  # "Cm" classified
        assert "Alice" in app._art_text.get("1.0", "end")
        assert "Missing BPM" in app._missing_text.get("1.0", "end")
        assert app._status_var.get().startswith("Scanned 2 files")
        # The real completeness analysis ran over the same library.
        assert completeness.total_files == 2
        assert app._comp_overall_var.get().startswith("Overall")

    def test_uses_cache_when_enabled(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
        isolated_cache: LibraryCache,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _patch_after(app, monkeypatch)
        app.folder_path.set(str(library))

        app._start_scan(refresh=False)
        app._do_scan(str(library), refresh=False)

        assert app.root.after.call_args is not None
        report, completeness = app.root.after.call_args.args[2:]
        app._on_scan_complete(report, completeness)

        cached_rows = app._cache.row_count(str(library))
        assert cached_rows == 2, "the real cache backend must store both files"
        assert f"{cached_rows} cached" in app._status_var.get()

    def test_refresh_ignores_cache(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
        isolated_cache: LibraryCache,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        after = _patch_after(app, monkeypatch)
        fake_threading = MagicMock()
        monkeypatch.setattr(app_module, "threading", fake_threading)
        app.folder_path.set(str(library))

        # Seed the cache with a normal scan, then force a full refresh.
        app._start_scan(refresh=False)
        app._do_scan(str(library), refresh=False)
        assert after.call_args is not None
        report, completeness = after.call_args.args[2:]
        app._on_scan_complete(report, completeness)
        cached_rows = app._cache.row_count(str(library))
        assert cached_rows == 2
        assert app._status_var.get().startswith("Scanned 2 files")

        app._start_refresh()

        # The refresh flag reaches the worker thread, not the completion
        # callback, so it is asserted where it is actually propagated.
        assert app._status_var.get() == "Scanning... (full refresh)"
        thread_args = fake_threading.Thread.call_args.kwargs["args"]
        assert thread_args == (str(library), True), thread_args

        app._do_scan(str(library), refresh=True)
        refresh_complete = after.call_args
        assert refresh_complete is not None
        assert_bound(refresh_complete.args[1], "_on_scan_complete", app)
        report_refresh, completeness_refresh = refresh_complete.args[2:]
        app._on_scan_complete(report_refresh, completeness_refresh)
        assert app._status_var.get().startswith("Scanned 2 files")

    def test_scan_error_resets_ui(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        messagebox, _ = stubbed_dialogs
        show_error = MagicMock()
        monkeypatch.setattr(app_module, "show_error_from_exception", show_error)
        after = _patch_after(app, monkeypatch)
        fake_threading = MagicMock()
        monkeypatch.setattr(app_module, "threading", fake_threading)
        app.folder_path.set(str(library))

        from audio_suite_shared.exceptions import AudioSuiteError

        def _raise(*_a: Any, **_k: Any) -> Any:
            raise AudioSuiteError("scan exploded")

        monkeypatch.setattr(app_module, "scan_directory", _raise)

        app._start_scan(refresh=False)
        app._do_scan(str(library), refresh=False)

        error_call = after.call_args
        assert error_call is not None
        assert_bound(error_call.args[1], "_on_scan_error", app)
        exc = error_call.args[2]
        assert isinstance(exc, AudioSuiteError)
        assert app._scanning is True, "the callback is scheduled, not executed"

        # The main thread then runs the scheduled callback (no mainloop here).
        app._on_scan_error(exc)

        assert app._scanning is False
        assert str(app._scan_btn.cget("state")) == "normal"
        assert app._status_var.get().startswith("Scan failed")
        show_error.assert_called_once()
        messagebox.showwarning.assert_not_called()


class TestExport:
    """CSV header + rows and JSON shape, written to real files (read back)."""

    def test_no_report_export_warns(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, filedialog = stubbed_dialogs
        app._report = None

        app._export()

        messagebox.showwarning.assert_called_once()
        filedialog.asksaveasfilename.assert_not_called()

    def test_empty_report_export_warns(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, _ = stubbed_dialogs
        app._report = StatsReport()  # total_files == 0

        app._export()

        messagebox.showwarning.assert_called_once()

    def test_csv_export_writes_header_and_rows(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        engine_report: StatsReport,
        export_reads: None,
        tmp_path: Path,
    ) -> None:
        filedialog = stubbed_dialogs[1]
        app._report = engine_report
        out = tmp_path / "export.csv"
        filedialog.asksaveasfilename.return_value = str(out)

        app._export()

        assert out.exists(), "the export button must write a real CSV file"
        with open(out, encoding="utf-8", newline="") as f:
            rows = list(csv.reader(f))
        assert rows[0] == [
            "path",
            "format",
            "bpm",
            "key",
            "genre",
            "mood",
            "tempo_marking",
            "album_artist",
            "artist_album",
            "year",
        ]
        assert len(rows) == 3, "header + one row per walked audio file"
        paths = {row[0] for row in rows[1:]}
        assert paths == {
            str(Path(str(engine_report.scan_path), "a.mp3")),
            str(Path(str(engine_report.scan_path), "b.mp3")),
        }
        assert app._status_var.get() == "Exported to export.csv"

    def test_json_export_shape(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        engine_report: StatsReport,
        tmp_path: Path,
    ) -> None:
        filedialog = stubbed_dialogs[1]
        app._report = engine_report
        out = tmp_path / "export.json"
        filedialog.asksaveasfilename.return_value = str(out)

        app._export()

        assert out.exists()
        data = json.loads(out.read_text(encoding="utf-8"))
        assert data["total_files"] == engine_report.total_files
        assert data["duration_str"] == engine_report.to_dict()["duration_str"]
        assert "format_breakdown" in data
        assert app._status_var.get() == "Exported to export.json"

    def test_export_failure_is_surfaced(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        engine_report: StatsReport,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        messagebox, filedialog = stubbed_dialogs
        show_error = MagicMock()
        monkeypatch.setattr(app_module, "show_error_from_exception", show_error)

        def _export_error(report: StatsReport, path: str) -> None:
            raise OSError("cannot find scan path")

        monkeypatch.setattr(app_module, "export_csv", _export_error)

        engine_report.scan_path = str(Path("D:/definitely_gone"))
        app._report = engine_report
        out = tmp_path / "export.csv"
        filedialog.asksaveasfilename.return_value = str(out)

        app._export()

        assert not out.exists()
        messagebox.showwarning.assert_not_called()  # valid report, write attempted
        show_error.assert_called_once()

    def test_cancelled_export_writes_nothing(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        engine_report: StatsReport,
        tmp_path: Path,
    ) -> None:
        filedialog = stubbed_dialogs[1]
        app._report = engine_report
        out = tmp_path / "export.csv"
        filedialog.asksaveasfilename.return_value = ""  # user cancelled

        app._export()

        assert not out.exists()


class TestCompletenessExports:
    def test_no_data_warns(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, _ = stubbed_dialogs

        app._export_completeness_csv()
        app._export_completeness_json()

        assert messagebox.showwarning.call_count == 2

    def test_csv_and_json_export_real_files(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
        library: Path,
        scan_reads: None,
        tmp_path: Path,
    ) -> None:
        filedialog = stubbed_dialogs[1]
        completeness = analyse_completeness(str(library))
        app._completeness_report = completeness
        assert completeness.total_files == 2
        csv_out = tmp_path / "comp.csv"
        json_out = tmp_path / "comp.json"
        filedialog.asksaveasfilename.side_effect = [str(csv_out), str(json_out)]

        app._export_completeness_csv()
        app._export_completeness_json()

        assert csv_out.exists() and json_out.exists()
        with open(csv_out, encoding="utf-8", newline="") as f:
            csv_rows = list(csv.reader(f))
        assert csv_rows[0] == [
            "tag",
            "total",
            "present",
            "missing",
            "pct_complete",
        ]
        assert len(csv_rows) == 1 + len(TAG_FIELDS), "one row per tracked field"
        json_data = json.loads(json_out.read_text(encoding="utf-8"))
        assert "tag_results" in json_data
        assert app._status_var.get() == "Exported to comp.json"

    def test_cancelled_save_does_nothing(
        self,
        app: app_module.LibraryStatsApp,
        stubbed_dialogs: tuple[MagicMock, MagicMock],
    ) -> None:
        messagebox, filedialog = stubbed_dialogs
        app._completeness_report = MagicMock(total_files=2)
        filedialog.asksaveasfilename.return_value = ""  # user cancelled

        app._export_completeness_csv()
        app._export_completeness_json()

        assert filedialog.asksaveasfilename.call_count == 2
        messagebox.showwarning.assert_not_called()


class TestCompletenessRendering:
    def test_bar_colour_boundaries_and_unmapped_canvas(
        self, app: app_module.LibraryStatsApp
    ) -> None:
        assert app._colour_for_pct(85.0) == "#22c55e"
        assert app._colour_for_pct(80.0) == "#f59e0b"
        assert app._colour_for_pct(49.9) == "#ef4444"

        canvas = MagicMock()
        canvas.winfo_width.return_value = 1  # not mapped yet
        app._draw_bar(canvas, MagicMock(pct_complete=90.0))
        canvas.create_rectangle.assert_not_called()

        canvas.winfo_width.return_value = 200
        canvas.winfo_height.return_value = 20
        app._draw_bar(canvas, MagicMock(pct_complete=90.0))
        assert canvas.create_rectangle.call_count == 1

    def test_render_and_missing_text(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
    ) -> None:
        completeness = analyse_completeness(str(library))

        app._update_completeness(completeness)

        assert app._comp_overall_var.get().startswith("Overall")
        missing_text = app._comp_missing_text.get("1.0", "end")
        assert "missing" in missing_text

    def test_empty_library_message(
        self,
        app: app_module.LibraryStatsApp,
        tmp_path: Path,
    ) -> None:
        empty = tmp_path / "empty_dir"
        empty.mkdir()
        app._update_completeness(analyse_completeness(str(empty)))

        assert "No audio files found" in app._comp_missing_text.get("1.0", "end")
        assert app._comp_overall_var.get() == ""
