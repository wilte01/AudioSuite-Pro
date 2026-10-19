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

Chart rendering is exercised for real since Sprint 3 (PLAN_feature_expansion.md
D37): matplotlib is a declared dependency now, so ``TestChartRendering`` builds
the four-panel figure through the real ``_update_charts`` and asserts what the
axes actually contain, rather than trusting that a canvas object exists. A
separate test asserts ``HAVE_MPL`` is True so a half-installed interpreter fails
loudly instead of silently taking the fallback branch.

Changed in 1.3.0: adds the real chart-rendering locks and makes the cache-scan
test build its scan on the main thread (a real worker thread calling
``root.after`` is a race, not a scenario the suite controls).

Changed in 1.4.0: the scan and export fixtures patch the tag-handler factory,
so the real single-pass ``_read_file_tags`` read stays in the loop, and a
load-count test locks the one-load-per-file contract (PLAN D55).
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
def isolated_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> Generator[LibraryCache, None, None]:
    """Bind the app's default-path cache constructor to a scratch database.

    The database is closed on teardown: the app keeps using the injected
    instance, so nothing else would ever close its SQLite handle.
    """
    cache = LibraryCache(str(tmp_path / "library_cache.db"))

    def _factory(cache_path: str | Path | None = None) -> LibraryCache:
        assert cache_path is None, "the app must use the default-path constructor"
        return cache

    monkeypatch.setattr(app_module, "LibraryCache", _factory)
    try:
        yield cache
    finally:
        cache.close()


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


def _handler_for(tags: _FileTags) -> MagicMock:
    """A tag handler reporting *tags*, shaped like a real loaded handler."""
    handler = MagicMock()
    handler.read_artist_album.return_value = tags.artist_album
    handler.read_album_artist.return_value = tags.album_artist
    handler.read_bpm.return_value = tags.bpm
    handler.read_key.return_value = tags.key
    handler.read_genre.return_value = tags.genre
    handler.read_mood.return_value = tags.mood
    handler.read_tempo_marking.return_value = tags.tempo_marking
    raw: dict[str, str] = {}
    if tags.year is not None:
        raw["TDRC"] = str(tags.year)
    handler.get_raw_tags.return_value = raw
    return handler


@pytest.fixture()
def scan_reads(monkeypatch: pytest.MonkeyPatch, library: Path) -> MagicMock:
    """Patch the tag-handler factory: one tagged file, one untagged.

    Stubbing the factory rather than ``_read_file_tags`` keeps the real
    single-pass reader in the loop, so the scan still exercises the shape the
    production path uses (PLAN D55). The returned factory records the loads.
    """
    handlers = {
        str(library / "a.mp3"): _handler_for(_A_TAGS),
        str(library / "b.mp3"): _handler_for(_EMPTY_TAGS),
    }

    factory = MagicMock(side_effect=lambda path: handlers[str(Path(path))])
    monkeypatch.setattr(
        "library_stats.core.file_processor.TagHandlerFactory.get_handler", factory
    )
    return factory


@pytest.fixture()
def export_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Canned tag values so real ``export_csv`` writes every row.

    ``export_csv`` loads one handler per file; on garbage test bytes its
    readers would raise and the row would be skipped, so this fixture returns
    a handler whose readers all report "no tag".
    """
    handler = MagicMock()
    raw = MagicMock()
    raw.get.return_value = None
    handler.get_raw_tags.return_value = raw
    for reader in (
        "read_artist_album",
        "read_album_artist",
        "read_bpm",
        "read_key",
        "read_genre",
        "read_mood",
        "read_tempo_marking",
    ):
        getattr(handler, reader).return_value = None
    monkeypatch.setattr(
        "library_stats.core.file_processor.TagHandlerFactory.get_handler",
        lambda path: handler,
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

    def test_scan_loads_one_handler_per_file(
        self, library: Path, scan_reads: MagicMock
    ) -> None:
        """D55: a two-file scan parses each file once, not eight times."""
        report = scan_directory(str(library), use_cache=False)

        assert report.total_files == 2
        assert scan_reads.call_count == 2
        loaded = sorted(Path(call.args[0]).name for call in scan_reads.call_args_list)
        assert loaded == ["a.mp3", "b.mp3"]

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

    def test_scan_records_one_trend_snapshot(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
        isolated_cache: LibraryCache,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The dashboard writes one trend point per distinct scan (D41)."""
        _patch_after(app, monkeypatch)
        monkeypatch.setattr(app_module, "threading", MagicMock())
        app.folder_path.set(str(library))

        app._do_scan(str(library), refresh=False)
        report, completeness = app.root.after.call_args.args[2:]
        app._on_scan_complete(report, completeness)

        history = isolated_cache.completeness_history(str(library))
        assert len(history) == 1
        assert history[0]["total_files"] == 2

        # Re-scanning unchanged content must not pad the trend series.
        app._do_scan(str(library), refresh=False)
        report2, completeness2 = app.root.after.call_args.args[2:]
        app._on_scan_complete(report2, completeness2)
        assert len(isolated_cache.completeness_history(str(library))) == 1

    def test_uses_cache_when_enabled(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
        isolated_cache: LibraryCache,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        after = _patch_after(app, monkeypatch)
        # The worker thread is not what this test is about, and a real thread
        # calling ``root.after`` races the Tk interpreter ("main thread is not
        # in main loop"); the scan itself runs below, on the main thread.
        monkeypatch.setattr(app_module, "threading", MagicMock())
        app.folder_path.set(str(library))

        app._start_scan(refresh=False)
        app._do_scan(str(library), refresh=False)
        assert after.call_args is not None

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

    def test_heatmap_is_embedded_in_the_completeness_tab(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
    ) -> None:
        """The per-album heatmap goes here, not in a fifth tab (PLAN D38)."""
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        completeness = analyse_completeness(str(library))
        app._update_completeness(completeness)

        assert isinstance(app._comp_heatmap_canvas, FigureCanvasTkAgg)
        heatmap_axes = app._comp_heatmap_canvas.figure.axes[0]
        assert len(heatmap_axes.images) == 1
        assert len(heatmap_axes.get_yticks()) == len(completeness.album_results)
        # Still four tabs: the heatmap must not have widened the layout.
        assert len(app._notebook.tabs()) == 4

    def test_heatmap_replaces_the_previous_canvas(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
    ) -> None:
        completeness = analyse_completeness(str(library))
        app._update_completeness(completeness)
        first = app._comp_heatmap_canvas
        app._update_completeness(completeness)

        assert app._comp_heatmap_canvas is not first
        assert len(app._comp_heatmap_frame.winfo_children()) == 1


class TestChartRendering:
    """The Charts tab against real matplotlib (Sprint 3, PLAN D37)."""

    def test_matplotlib_is_a_declared_dependency(self) -> None:
        """A missing matplotlib fails here instead of degrading silently.

        The gate must run from the project virtualenv, which carries every
        declared dependency; a bare ``python`` on PATH is a partial
        environment. Without this assertion a run there would quietly take
        the ``HAVE_MPL`` fallback branch and still look green.
        """
        assert app_module.HAVE_MPL is True, (
            "matplotlib must be importable for the suite: run the gate from a "
            "virtualenv created with 'uv sync --all-extras'"
        )

    def test_scan_renders_data_panels_and_trend(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
    ) -> None:
        """The fixture library's tags reach the artists, not just the axes."""
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg

        report = scan_directory(str(library), use_cache=False)

        app._update_charts(report)

        assert isinstance(app._chart_canvas, FigureCanvasTkAgg)
        figure = app._chart_canvas.figure
        assert [ax.get_title() for ax in figure.axes] == [
            "Top Genres",
            "BPM Distribution",
            "Top Keys",
            "Year Distribution",
            "Completeness Trend",
        ]
        # One pie wedge for the single genre ("House").
        assert len(figure.axes[0].patches) == 1
        # Only the tagged file carries BPM 128, so the 120-139 bucket (index
        # 4 of the ordered bins) holds the single measured file.
        heights = [patch.get_height() for patch in figure.axes[1].patches]
        assert sum(heights) == 1
        assert heights[4] == 1
        # One horizontal bar for the single key ("Cm").
        assert len(figure.axes[2].patches) == 1
        # The canvas widget is embedded in the Charts frame.
        assert app._charts_frame.winfo_children()

    def test_empty_report_still_renders(self, app: app_module.LibraryStatsApp) -> None:
        """An empty library renders axes with no artists rather than raising."""
        from library_stats.core.file_processor import StatsReport

        app._update_charts(StatsReport(scan_path="", total_files=0))

        assert app._chart_canvas is not None
        figure = app._chart_canvas.figure
        assert len(figure.axes) == 5
        assert len(figure.axes[0].patches) == 0
        # No history yet: the trend panel explains itself instead of being
        # an empty axis a user would read as a rendering failure.
        trend = figure.axes[4]
        assert len(trend.lines) == 0
        assert any("No history" in text.get_text() for text in trend.texts)

    def test_trend_panel_draws_the_history(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
    ) -> None:
        report = scan_directory(str(library), use_cache=False)
        history = [
            {
                "recorded_at": "2026-10-01 10:00:00",
                "total_files": 2,
                "overall_pct": 40.0,
                "tag_pcts": {},
            },
            {
                "recorded_at": "2026-10-02 10:00:00",
                "total_files": 2,
                "overall_pct": 80.0,
                "tag_pcts": {},
            },
        ]

        app._update_charts(report, history)

        figure = app._chart_canvas.figure
        trend = figure.axes[4]
        assert len(trend.lines) == 1
        assert list(trend.lines[0].get_ydata()) == [40.0, 80.0]
        assert [tick.get_text() for tick in trend.get_xticklabels()] == [
            "2026-10-01",
            "2026-10-02",
        ]

    def test_second_render_replaces_the_first(
        self,
        app: app_module.LibraryStatsApp,
        library: Path,
        scan_reads: None,
    ) -> None:
        """Re-scanning destroys the previous canvas; frames do not accumulate."""
        report = scan_directory(str(library), use_cache=False)

        app._update_charts(report)
        first = app._chart_canvas
        app._update_charts(report)

        assert app._chart_canvas is not first
        children = app._charts_frame.winfo_children()
        assert len(children) == 1
