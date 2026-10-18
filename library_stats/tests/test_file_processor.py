"""
tests/test_file_processor.py
Unit tests for library_stats/core/file_processor.py gap paths not covered
by test_library_stats.py: year extraction (ID3 TDRC + Vorbis DATE) in both
the full and cached scanners, per-file error skipping, unstatable-file
skipping, missing-tag counters via the cache path, corrupt cached
artist_album JSON, default-cache creation, and export_csv year/skip paths.

All tag readers are patched on their module-level bindings
(library_stats.core.file_processor), matching the pattern in
test_library_stats.py; the SQLite cache uses a tmp_path database.

Changed in 1.3.0: pins the cached-scan fast path — an unchanged library reads
no tags and performs no per-file ``file_is_cached`` lookup — and that a
backdated mtime re-reads only that file.

Changed in 1.0.1: adds the valid-JSON-non-list ``artist_album`` cache-row
regression (a value that decodes but is not a 2-element list must be ignored,
not raise a TypeError).

Run with:
    pytest tests/test_file_processor.py -v
"""

from __future__ import annotations

import csv
import os
from contextlib import ExitStack, contextmanager
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from library_stats.core.file_processor import (
    StatsReport,
    _extract_year_from_tags,
    _populate_report,
    _read_file_tags,
    export_csv,
    scan_directory,
)
from library_stats.library_cache import LibraryCache

_READER_NAMES = (
    "read_artist_album",
    "read_album_artist",
    "read_bpm",
    "read_key",
    "read_genre",
    "read_mood",
    "read_tempo_marking",
    "read_tags_raw",
)


@contextmanager
def _reader_mocks() -> Any:
    """Patch all tag readers, defaulting every return to None.

    Yields a dict of the MagicMock objects keyed by reader name so each
    test can override only the readers it cares about.
    """
    with ExitStack() as stack:
        mocks = {
            name: stack.enter_context(
                patch(f"library_stats.core.file_processor.{name}")
            )
            for name in _READER_NAMES
        }
        for mock in mocks.values():
            mock.return_value = None
        yield mocks


def _raw_with(field_values: dict[str, str]) -> MagicMock:
    """Raw-tags mock whose get() returns canned strings per tag ID."""
    raw = MagicMock()
    raw.get.side_effect = lambda k: field_values.get(k)
    return raw


def _raise_if(substr: str, exc: Exception, default: Any) -> Any:
    """Side effect raising *exc* for paths containing *substr*."""

    def _fn(path: str, *args: Any, **kwargs: Any) -> Any:
        if substr in str(path):
            raise exc
        return default

    return _fn


# ── Full (uncached) scanner: year extraction and error paths ────────────────


class TestFullScanYears:
    def test_year_from_tdrc_frame(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        with _reader_mocks() as r:
            r["read_tags_raw"].return_value = _raw_with({"TDRC": "2021-06-15"})
            report = scan_directory(str(tmp_path))
        assert report.year_distribution == {"2020s": 1}

    def test_year_from_vorbis_date_fallback(self, tmp_path: Path) -> None:
        (tmp_path / "a.flac").write_bytes(b"x")
        with _reader_mocks() as r:
            r["read_tags_raw"].return_value = _raw_with({"DATE": "1995-03-01"})
            report = scan_directory(str(tmp_path))
        assert report.year_distribution == {"1990s": 1}

    def test_year_read_error_counts_unknown(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        with _reader_mocks() as r:
            raw = MagicMock()
            raw.get.side_effect = ValueError("bad tag value")
            r["read_tags_raw"].return_value = raw
            report = scan_directory(str(tmp_path))
        assert report.year_distribution == {"Unknown": 1}

    def test_unreadable_file_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        with _reader_mocks() as r:
            r["read_bpm"].side_effect = OSError("corrupt file")
            report = scan_directory(str(tmp_path))
        # Counted before the failure, but no distributions populated.
        assert report.total_files == 1
        assert report.bpm_distribution == {}
        assert report.year_distribution == {}


# ── Cached scanner ───────────────────────────────────────────────────────────


class TestCachedScan:
    def test_year_from_tdrc_frame(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        cache = LibraryCache(tmp_path / "cache.db")
        with _reader_mocks() as r:
            r["read_tags_raw"].return_value = _raw_with({"TDRC": "2019-04-01"})
            report = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        cache.close()
        assert report.year_distribution == {"2010s": 1}

    def test_year_from_vorbis_date_fallback(self, tmp_path: Path) -> None:
        (tmp_path / "a.flac").write_bytes(b"x")
        cache = LibraryCache(tmp_path / "cache.db")
        with _reader_mocks() as r:
            r["read_tags_raw"].return_value = _raw_with({"DATE": "1987-01-02"})
            report = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        cache.close()
        assert report.year_distribution == {"1980s": 1}

    def test_year_read_error_is_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        cache = LibraryCache(tmp_path / "cache.db")
        with _reader_mocks() as r:
            raw = MagicMock()
            raw.get.side_effect = ValueError("bad tag value")
            r["read_tags_raw"].return_value = raw
            report = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        cache.close()
        assert report.year_distribution == {"Unknown": 1}

    def test_unreadable_file_is_skipped(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        cache = LibraryCache(tmp_path / "cache.db")
        with _reader_mocks() as r:
            r["read_bpm"].side_effect = OSError("corrupt file")
            report = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        cache.close()
        # No cache row was written, so nothing is reported.
        assert report.total_files == 0

    def test_unstatable_file_is_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / "broken.mp3").write_bytes(b"x")
        (tmp_path / "good.mp3").write_bytes(b"x")
        real_stat = os.stat

        def flaky_stat(path: Any, *args: Any, **kwargs: Any) -> Any:
            if "broken" in str(path):
                raise OSError("gone")
            return real_stat(path, *args, **kwargs)

        monkeypatch.setattr(os, "stat", flaky_stat)
        cache = LibraryCache(tmp_path / "cache.db")
        with _reader_mocks() as r:
            r["read_bpm"].return_value = 120
            report = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        cache.close()
        assert report.total_files == 1
        assert report.bpm_distribution == {"120\u2013139": 1}

    def test_cache_hit_skips_every_tag_read(self, tmp_path: Path) -> None:
        """An unchanged file must not be re-read, and no per-file lookup runs.

        3.2 replaced the per-file ``file_is_cached`` query with one scoped
        ``get_cached_mtimes`` read, so a regression to per-row lookups (or to
        re-reading tags) fails here rather than only on a 20 000-file
        library.
        """
        (tmp_path / "a.mp3").write_bytes(b"x")
        (tmp_path / "b.mp3").write_bytes(b"y")
        cache = LibraryCache(tmp_path / "cache.db")
        with _reader_mocks() as r:
            r["read_bpm"].return_value = 128
            first = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        assert first.total_files == 2
        assert len(first.bpm_distribution) == 1

        with (
            patch.object(
                cache,
                "file_is_cached",
                side_effect=AssertionError(
                    "cache scan used the per-file file_is_cached() lookup"
                ),
            ),
            _reader_mocks() as r2,
        ):
            second = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        cache.close()

        r2["read_bpm"].assert_not_called()
        assert second.total_files == 2
        assert second.bpm_distribution == first.bpm_distribution

    def test_changed_mtime_re_reads_that_file(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        cache = LibraryCache(tmp_path / "cache.db")
        with _reader_mocks() as r:
            r["read_bpm"].return_value = 100
            scan_directory(str(tmp_path), use_cache=True, cache=cache)
        stale = cache.get_cached_mtimes(str(tmp_path))
        assert stale

        # Backdate the cached mtime so the file looks changed.
        conn = cache._connect()
        conn.execute("UPDATE files SET mtime = mtime - 10")
        conn.commit()

        with _reader_mocks() as r2:
            r2["read_bpm"].return_value = 170
            second = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        cache.close()

        r2["read_bpm"].assert_called()
        assert second.bpm_distribution == {"160\u2013179": 1}

    def test_missing_tags_counters_from_cache(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        cache = LibraryCache(tmp_path / "cache.db")
        with _reader_mocks():
            report = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        cache.close()
        assert report.missing_data == {
            "no_bpm": 1,
            "no_key": 1,
            "no_genre": 1,
            "no_mood": 1,
            "no_tempo_marking": 1,
        }

    def test_corrupt_cached_artist_album_json_ignored(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        cache = LibraryCache(tmp_path / "cache.db")
        with _reader_mocks() as r:
            r["read_artist_album"].return_value = ("Artist", "Album")
            r["read_album_artist"].return_value = "Artist"
            first = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        assert first.total_albums == 1

        # Corrupt the cached JSON, then re-scan (cache hit → no re-read).
        conn = cache._connect()
        conn.execute("UPDATE files SET artist_album = '{oops'")
        conn.commit()
        second = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        cache.close()
        # Corrupt row contributes no album/track-artist, but the intact
        # album_artist column still counts the artist.
        assert second.total_albums == 0
        assert second.total_track_artists == 0
        assert second.total_artists == 1

    def test_valid_json_non_list_cached_artist_album_ignored(
        self, tmp_path: Path
    ) -> None:
        """A cache row holding valid JSON that is not a 2-element list must
        not abort the scan with an uncaught TypeError (G7.3)."""
        (tmp_path / "a.mp3").write_bytes(b"x")
        cache = LibraryCache(tmp_path / "cache.db")
        with _reader_mocks() as r:
            r["read_artist_album"].return_value = ("Artist", "Album")
            r["read_album_artist"].return_value = "Artist"
            scan_directory(str(tmp_path), use_cache=True, cache=cache)

        # Valid JSON, but neither a list nor a 2-element list: len() would
        # raise TypeError pre-fix.
        conn = cache._connect()
        conn.execute("UPDATE files SET artist_album = '5'")
        conn.commit()
        second = scan_directory(str(tmp_path), use_cache=True, cache=cache)
        cache.close()

        assert second.total_albums == 0
        assert second.total_track_artists == 0
        assert second.total_artists == 1


class TestScanDirectoryCacheCreation:
    def test_use_cache_without_cache_creates_one(self, tmp_path: Path) -> None:
        db = tmp_path / "cache.db"

        class _TmpLibraryCache(LibraryCache):
            def __init__(self) -> None:
                super().__init__(str(db))

        (tmp_path / "a.mp3").write_bytes(b"x")
        with (
            _reader_mocks() as r,
            patch("library_stats.library_cache.LibraryCache", _TmpLibraryCache),
        ):
            r["read_bpm"].return_value = 128
            report = scan_directory(str(tmp_path), use_cache=True)
        assert report.total_files == 1
        assert db.exists()


# ── export_csv ───────────────────────────────────────────────────────────────


class TestExportCsv:
    def test_year_column_extracted_from_tdrc(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        out = tmp_path / "out.csv"
        with _reader_mocks() as r:
            r["read_bpm"].return_value = 120
            r["read_tags_raw"].return_value = _raw_with({"TDRC": "2019-12-01"})
            report = StatsReport(scan_path=str(tmp_path))
            export_csv(report, str(out))

        with open(out, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["year"] == "2019"
        assert rows[0]["bpm"] == "120"

    def test_unreadable_file_skipped_during_export(self, tmp_path: Path) -> None:
        (tmp_path / "good.mp3").write_bytes(b"x")
        (tmp_path / "bad.mp3").write_bytes(b"x")
        out = tmp_path / "out.csv"
        with _reader_mocks() as r:
            r["read_bpm"].side_effect = _raise_if("bad", OSError("corrupt file"), 120)
            report = StatsReport(scan_path=str(tmp_path))
            export_csv(report, str(out))

        with open(out, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 1
        assert rows[0]["path"].endswith("good.mp3")


# ── _extract_year_from_tags unit tests ───────────────────────────────────────


class TestExtractYearFromTags:
    def test_none_input(self) -> None:
        assert _extract_year_from_tags(None) is None

    def test_non_dict_input(self) -> None:
        assert _extract_year_from_tags("not a dict") is None

    def test_no_get_method(self) -> None:
        assert _extract_year_from_tags(42) is None

    def test_year_from_tdrc(self) -> None:
        raw = _raw_with({"TDRC": "2021-06-15"})
        assert _extract_year_from_tags(raw) == 2021

    def test_year_from_tdrl(self) -> None:
        raw = _raw_with({"TDRL": "2020"})
        assert _extract_year_from_tags(raw) == 2020

    def test_year_from_tyer(self) -> None:
        raw = _raw_with({"TYER": "1999"})
        assert _extract_year_from_tags(raw) == 1999

    def test_year_from_tory(self) -> None:
        raw = _raw_with({"TORY": "2015"})
        assert _extract_year_from_tags(raw) == 2015

    def test_vorbis_date_fallback(self) -> None:
        raw = _raw_with({"DATE": "1987-01-02"})
        assert _extract_year_from_tags(raw) == 1987

    def test_id3_takes_priority_over_vorbis(self) -> None:
        raw = _raw_with({"TDRC": "2020-01-01", "DATE": "1990-06-01"})
        assert _extract_year_from_tags(raw) == 2020

    def test_no_year_found(self) -> None:
        raw = _raw_with({"TDRC": "not a year"})
        assert _extract_year_from_tags(raw) is None

    def test_empty_tags(self) -> None:
        raw = _raw_with({})
        assert _extract_year_from_tags(raw) is None


# ── _populate_report unit tests ──────────────────────────────────────────────


class TestPopulateReport:
    def test_populates_all_fields(self) -> None:
        from collections import Counter

        report = StatsReport(scan_path="/music")
        _populate_report(
            report,
            format_counter=Counter({".mp3": 5, ".flac": 3}),
            bpm_counter=Counter({"120\u2013139": 4, "Unknown": 4}),
            key_counter=Counter({"C": 3, "Am": 2}),
            key_mode_counter=Counter({"major": 3, "minor": 2}),
            mood_counter=Counter({"Happy": 2}),
            genre_counter=Counter({"Rock": 4}),
            tempo_counter=Counter({"Allegro": 3}),
            year_counter=Counter({"2020s": 5, "1990s": 3}),
            artist_counter=Counter({"Artist A": 5, "Artist B": 3}),
            album_set={("A", "Album1"), ("B", "Album2")},
            artist_set={"Artist A", "Artist B"},
            track_artist_set={"Artist A", "Artist B", "Artist C"},
            missing_no_bpm=2,
            missing_no_key=1,
            missing_no_genre=0,
            missing_no_mood=3,
            missing_no_tempo=1,
        )
        assert report.format_breakdown == {".mp3": 5, ".flac": 3}
        assert report.total_albums == 2
        assert report.total_artists == 2
        assert report.total_track_artists == 3
        assert report.missing_data["no_bpm"] == 2
        assert report.top_artists == [("Artist A", 5), ("Artist B", 3)]

    def test_empty_counters(self) -> None:
        from collections import Counter

        report = StatsReport(scan_path="/empty")
        _populate_report(
            report,
            format_counter=Counter(),
            bpm_counter=Counter(),
            key_counter=Counter(),
            key_mode_counter=Counter(),
            mood_counter=Counter(),
            genre_counter=Counter(),
            tempo_counter=Counter(),
            year_counter=Counter(),
            artist_counter=Counter(),
            album_set=set(),
            artist_set=set(),
            track_artist_set=set(),
            missing_no_bpm=0,
            missing_no_key=0,
            missing_no_genre=0,
            missing_no_mood=0,
            missing_no_tempo=0,
        )
        assert report.total_files == 0
        assert report.total_albums == 0
        assert report.format_breakdown == {}
        assert report.missing_data["no_bpm"] == 0


# ── _read_file_tags unit tests ───────────────────────────────────────────────


class TestReadFileTags:
    def test_reads_all_fields(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        with _reader_mocks() as r:
            r["read_artist_album"].return_value = ("Artist", "Album")
            r["read_album_artist"].return_value = "Album Artist"
            r["read_bpm"].return_value = 120
            r["read_key"].return_value = "C"
            r["read_genre"].return_value = "Rock"
            r["read_mood"].return_value = "Happy; Energetic"
            r["read_tempo_marking"].return_value = "Allegro"
            r["read_tags_raw"].return_value = _raw_with({"TDRC": "2021-06-15"})
            tags = _read_file_tags(str(tmp_path / "a.mp3"))

        assert tags.artist_album == ("Artist", "Album")
        assert tags.album_artist == "Album Artist"
        assert tags.bpm == 120
        assert tags.key == "C"
        assert tags.genre == "Rock"
        assert tags.mood == "Happy; Energetic"
        assert tags.tempo_marking == "Allegro"
        assert tags.year == 2021

    def test_missing_tags_default_to_none(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        with _reader_mocks():
            tags = _read_file_tags(str(tmp_path / "a.mp3"))
        assert tags.artist_album is None
        assert tags.album_artist is None
        assert tags.bpm is None
        assert tags.key is None
        assert tags.genre is None
        assert tags.mood is None
        assert tags.tempo_marking is None
        assert tags.year is None

    def test_year_error_degrades_to_none(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        with _reader_mocks() as r:
            raw = MagicMock()
            raw.get.side_effect = ValueError("bad tag value")
            r["read_tags_raw"].return_value = raw
            tags = _read_file_tags(str(tmp_path / "a.mp3"))
        assert tags.year is None
        assert tags.bpm is None

    def test_read_error_propagates(self, tmp_path: Path) -> None:
        (tmp_path / "a.mp3").write_bytes(b"x")
        with _reader_mocks() as r:
            r["read_bpm"].side_effect = OSError("corrupt")
            with pytest.raises(OSError):
                _read_file_tags(str(tmp_path / "a.mp3"))
