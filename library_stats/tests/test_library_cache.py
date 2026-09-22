"""Tests for library_stats.library_cache — SQLite cache CRUD and helpers."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from library_stats.library_cache import (
    LibraryCache,
    _bpm_bin,
    _classify_key_mode,
    _decade_bin,
    _path_hash,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def cache(tmp_path: Path) -> LibraryCache:
    """Return a LibraryCache backed by a temp file (cleaned up automatically)."""
    db_path = tmp_path / "test_cache.db"
    cache = LibraryCache(db_path)
    yield cache
    cache.close()


@pytest.fixture
def sample_file(tmp_path: Path) -> str:
    p = tmp_path / "song.mp3"
    p.write_bytes(b"fake mp3")
    return str(p)


# ── _path_hash ────────────────────────────────────────────────────────────────


class TestPathHash:
    def test_consistent(self) -> None:
        h1 = _path_hash("/music/track.mp3")
        h2 = _path_hash("/music/track.mp3")
        assert h1 == h2

    def test_different_paths(self) -> None:
        assert _path_hash("/a.mp3") != _path_hash("/b.mp3")

    def test_hex_length(self) -> None:
        h = _path_hash("/music/track.mp3")
        assert len(h) == 64  # SHA-256 hex


# ── LibraryCache: connection & lifecycle ─────────────────────────────────────


class TestLifecycle:
    def test_custom_path(self, tmp_path: Path) -> None:
        db = tmp_path / "custom.db"
        c = LibraryCache(db)
        assert c.db_path == db
        c.close()

    def test_default_path_creates_dir(self) -> None:
        c = LibraryCache()
        assert c.db_path.parent.name == ".audiosuite"
        c.close()

    def test_context_manager(self, tmp_path: Path) -> None:
        db = tmp_path / "ctx.db"
        with LibraryCache(db) as c:
            c._connect()
            assert c.db_path == db
        # Context manager exit closes the connection

    def test_db_file_created(self, tmp_path: Path) -> None:
        db = tmp_path / "created.db"
        assert not db.exists()
        with LibraryCache(db) as c:
            c._connect()
        assert db.exists()

    def test_double_connect_reuses(self, tmp_path: Path) -> None:
        with LibraryCache(tmp_path / "reuse.db") as c:
            conn1 = c._connect()
            conn2 = c._connect()
            assert conn1 is conn2


# ── LibraryCache: row operations ─────────────────────────────────────────────


class TestRowOperations:
    def test_upsert_and_file_is_cached(
        self, cache: LibraryCache, sample_file: str
    ) -> None:
        mtime = os.path.getmtime(sample_file)
        size = os.path.getsize(sample_file)
        cache.upsert_file(
            filepath=sample_file,
            mtime=mtime,
            size=size,
            format_ext=".mp3",
            bpm=128,
            key="C",
        )
        assert cache.file_is_cached(sample_file, mtime)
        assert not cache.file_is_cached(sample_file, mtime + 1)

    def test_file_is_cached_new_file(
        self, cache: LibraryCache, sample_file: str
    ) -> None:
        assert not cache.file_is_cached(sample_file, 0.0)

    def test_get_cached_mtimes(self, cache: LibraryCache, tmp_path: Path) -> None:
        f1 = tmp_path / "a.mp3"
        f2 = tmp_path / "b.mp3"
        f1.write_bytes(b"x")
        f2.write_bytes(b"y")
        m1 = os.path.getmtime(str(f1))
        m2 = os.path.getmtime(str(f2))
        cache.upsert_file(str(f1), mtime=m1, size=1, format_ext=".mp3")
        cache.upsert_file(str(f2), mtime=m2, size=1, format_ext=".mp3")

        mtimes = cache.get_cached_mtimes(str(tmp_path))
        assert str(f1) in mtimes
        assert str(f2) in mtimes
        assert mtimes[str(f1)] == m1

    def test_get_cached_mtimes_empty(self, cache: LibraryCache, tmp_path: Path) -> None:
        assert cache.get_cached_mtimes(str(tmp_path)) == {}

    def test_upsert_replaces_existing(
        self, cache: LibraryCache, sample_file: str
    ) -> None:
        mtime = os.path.getmtime(sample_file)
        cache.upsert_file(sample_file, mtime=mtime, size=1, format_ext=".mp3", bpm=100)
        cache.upsert_file(sample_file, mtime=mtime, size=1, format_ext=".mp3", bpm=200)
        assert cache.file_is_cached(sample_file, mtime)
        agg = cache.query_aggregate(os.path.dirname(sample_file))
        assert agg is not None
        # Only 1 row, bpm doesn't appear directly in aggregate but total_files = 1

    def test_upsert_with_all_fields(
        self, cache: LibraryCache, sample_file: str
    ) -> None:
        mtime = os.path.getmtime(sample_file)
        cache.upsert_file(
            filepath=sample_file,
            mtime=mtime,
            size=42,
            format_ext=".mp3",
            bpm=120,
            key="Am",
            genre="Jazz",
            mood="Energetic",
            tempo_marking="Allegro",
            album_artist="Test Artist",
            artist_album=("Test Artist", "Test Album"),
            year=1999,
        )
        agg = cache.query_aggregate(os.path.dirname(sample_file))
        assert agg is not None
        assert agg["total_files"] == 1
        assert agg["total_albums"] == 1
        assert agg["total_artists"] == 1

    def test_path_matching_case_insensitive(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        f = tmp_path / "track.mp3"
        f.write_bytes(b"x")
        m = os.path.getmtime(str(f))
        cache.upsert_file(str(f), mtime=m, size=1, format_ext=".mp3")

        path_lower = os.path.normpath(str(tmp_path)).lower()
        path_upper = os.path.normpath(str(tmp_path)).upper()

        assert cache.row_count(path_lower) == 1
        assert cache.row_count(path_upper) == 1

        mtimes_lower = cache.get_cached_mtimes(path_lower)
        mtimes_upper = cache.get_cached_mtimes(path_upper)
        assert str(f) in mtimes_lower
        assert str(f) in mtimes_upper

        agg_lower = cache.query_aggregate(path_lower)
        agg_upper = cache.query_aggregate(path_upper)
        assert agg_lower is not None
        assert agg_upper is not None
        assert agg_lower["total_files"] == 1
        assert agg_upper["total_files"] == 1


# ── LibraryCache: remove_orphans ─────────────────────────────────────────────


class TestRemoveOrphans:
    def test_removes_stale_entries(self, cache: LibraryCache, tmp_path: Path) -> None:
        f1 = tmp_path / "keep.mp3"
        f2 = tmp_path / "gone.mp3"
        f1.write_bytes(b"x")
        f2.write_bytes(b"x")
        m1 = os.path.getmtime(str(f1))
        m2 = os.path.getmtime(str(f2))
        cache.upsert_file(str(f1), mtime=m1, size=1, format_ext=".mp3")
        cache.upsert_file(str(f2), mtime=m2, size=1, format_ext=".mp3")

        # f2 still exists, so no orphans
        removed = cache.remove_orphans(str(tmp_path), {str(f1), str(f2)})
        assert removed == 0

        # Now simulate f2 being deleted (not in known_paths)
        removed = cache.remove_orphans(str(tmp_path), {str(f1)})
        assert removed == 1
        assert cache.row_count(str(tmp_path)) == 1

    def test_no_orphans_empty_dir(self, cache: LibraryCache, tmp_path: Path) -> None:
        removed = cache.remove_orphans(str(tmp_path), set())
        assert removed == 0


# ── LibraryCache: clear operations ───────────────────────────────────────────


class TestClear:
    def test_clear_dir(self, cache: LibraryCache, tmp_path: Path) -> None:
        sub = tmp_path / "sub"
        sub.mkdir()
        f1 = sub / "t.mp3"
        f1.write_bytes(b"x")
        m1 = os.path.getmtime(str(f1))
        cache.upsert_file(str(f1), mtime=m1, size=1, format_ext=".mp3")
        assert cache.row_count(str(sub)) == 1
        cache.clear_dir(str(sub))
        assert cache.row_count(str(sub)) == 0

    def test_clear_dir_keeps_other_dirs(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        d1.mkdir()
        d2.mkdir()
        f1 = d1 / "a.mp3"
        f2 = d2 / "b.mp3"
        f1.write_bytes(b"x")
        f2.write_bytes(b"x")
        m1 = os.path.getmtime(str(f1))
        m2 = os.path.getmtime(str(f2))
        cache.upsert_file(str(f1), mtime=m1, size=1, format_ext=".mp3")
        cache.upsert_file(str(f2), mtime=m2, size=1, format_ext=".mp3")
        cache.clear_dir(str(d1))
        assert cache.row_count(str(d1)) == 0
        assert cache.row_count(str(d2)) == 1

    def test_clear_all(self, cache: LibraryCache, tmp_path: Path) -> None:
        f1 = tmp_path / "a.mp3"
        f1.write_bytes(b"x")
        m1 = os.path.getmtime(str(f1))
        cache.upsert_file(str(f1), mtime=m1, size=1, format_ext=".mp3")
        assert cache.row_count() == 1
        cache.clear_all()
        assert cache.row_count() == 0


# ── LibraryCache: row_count ──────────────────────────────────────────────────


class TestRowCount:
    def test_count_global(self, cache: LibraryCache, tmp_path: Path) -> None:
        assert cache.row_count() == 0
        for name in ("a.mp3", "b.mp3", "c.mp3"):
            p = tmp_path / name
            p.write_bytes(b"x")
            m = os.path.getmtime(str(p))
            cache.upsert_file(str(p), mtime=m, size=1, format_ext=".mp3")
        assert cache.row_count() == 3

    def test_count_scoped(self, cache: LibraryCache, tmp_path: Path) -> None:
        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        d1.mkdir()
        d2.mkdir()
        for d in (d1, d2):
            p = d / "t.mp3"
            p.write_bytes(b"x")
            m = os.path.getmtime(str(p))
            cache.upsert_file(str(p), mtime=m, size=1, format_ext=".mp3")
        assert cache.row_count(str(d1)) == 1
        assert cache.row_count(str(d2)) == 1


# ── LibraryCache: query_aggregate ────────────────────────────────────────────


class TestQueryAggregate:
    def test_none_when_empty(self, cache: LibraryCache, tmp_path: Path) -> None:
        assert cache.query_aggregate(str(tmp_path)) is None

    def test_returns_all_fields(self, cache: LibraryCache, tmp_path: Path) -> None:
        p = tmp_path / "t.mp3"
        p.write_bytes(b"x")
        m = os.path.getmtime(str(p))
        cache.upsert_file(
            str(p),
            mtime=m,
            size=10,
            format_ext=".mp3",
            bpm=120,
            key="C",
            genre="Rock",
            mood="Happy",
            tempo_marking="Allegro",
            album_artist="A",
            artist_album=("A", "Album"),
            year=2000,
        )
        agg = cache.query_aggregate(str(tmp_path))
        assert agg is not None
        assert agg["total_files"] == 1
        assert agg["total_albums"] == 1
        assert agg["total_artists"] == 1
        assert agg["format_breakdown"] == {".mp3": 1}
        assert agg["missing_data"]["no_bpm"] == 0
        assert agg["missing_data"]["no_key"] == 0

    def test_missing_data_counts(self, cache: LibraryCache, tmp_path: Path) -> None:
        p = tmp_path / "t.mp3"
        p.write_bytes(b"x")
        m = os.path.getmtime(str(p))
        cache.upsert_file(str(p), mtime=m, size=10, format_ext=".mp3")
        agg = cache.query_aggregate(str(tmp_path))
        assert agg is not None
        assert agg["total_files"] == 1
        assert agg["missing_data"]["no_bpm"] == 1
        assert agg["missing_data"]["no_key"] == 1
        assert agg["missing_data"]["no_genre"] == 1
        assert agg["missing_data"]["no_mood"] == 1
        assert agg["missing_data"]["no_tempo_marking"] == 1

    def test_multiple_files_aggregation(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        files_data = [
            ("a.mp3", ".mp3", 120, "Rock", "C"),
            ("b.mp3", ".mp3", 130, "Jazz", "Am"),
            ("c.flac", ".flac", 140, "Rock", "C"),
        ]
        for name, fmt, bpm, genre, key in files_data:
            p = tmp_path / name
            p.write_bytes(b"x")
            m = os.path.getmtime(str(p))
            cache.upsert_file(
                str(p),
                mtime=m,
                size=10,
                format_ext=fmt,
                bpm=bpm,
                genre=genre,
                key=key,
                album_artist="Various" if genre == "Rock" else "Jazz Man",
            )
        agg = cache.query_aggregate(str(tmp_path))
        assert agg is not None
        assert agg["total_files"] == 3
        assert agg["format_breakdown"] == {".mp3": 2, ".flac": 1}
        assert agg["genre_distribution"] == {"Rock": 2, "Jazz": 1}

    def test_aggregate_scoped_to_directory(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        d1 = tmp_path / "d1"
        d2 = tmp_path / "d2"
        d1.mkdir()
        d2.mkdir()
        for d in (d1, d2):
            p = d / "t.mp3"
            p.write_bytes(b"x")
            m = os.path.getmtime(str(p))
            cache.upsert_file(str(p), mtime=m, size=10, format_ext=".mp3")
        assert cache.query_aggregate(str(d1)) is not None
        assert cache.query_aggregate(str(d1))["total_files"] == 1
        assert cache.query_aggregate(str(d2))["total_files"] == 1

    def test_subdirectory_files_included_in_parent_query(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        """Regression: files in subdirectories must be found when querying root."""
        sub = tmp_path / "subdir"
        sub.mkdir()
        for i in range(3):
            p = sub / f"t{i}.mp3"
            p.write_bytes(b"x")
            m = os.path.getmtime(str(p))
            cache.upsert_file(str(p), mtime=m, size=10, format_ext=".mp3")
        # Query at the parent level should find all 3 subdirectory files
        agg = cache.query_aggregate(str(tmp_path))
        assert agg is not None
        assert agg["total_files"] == 3
        assert cache.row_count(str(tmp_path)) == 3
        assert cache.row_count(str(sub)) == 3


# ── _classify_key_mode ────────────────────────────────────────────────────────


class TestClassifyKeyMode:
    def test_major_short(self) -> None:
        assert _classify_key_mode("C") == ("C", "major")
        assert _classify_key_mode("F#") == ("F#", "major")
        assert _classify_key_mode("Bb") == ("Bb", "major")

    def test_minor_short(self) -> None:
        assert _classify_key_mode("Am") == ("Am", "minor")
        assert _classify_key_mode("C#m") == ("C#m", "minor")
        assert _classify_key_mode("Dbm") == ("Dbm", "minor")

    def test_major_text(self) -> None:
        assert _classify_key_mode("C major") == ("C", "major")
        assert _classify_key_mode("F# major") == ("F#", "major")

    def test_minor_text(self) -> None:
        assert _classify_key_mode("A minor") == ("A", "minor")
        assert _classify_key_mode("C# minor") == ("C#", "minor")

    def test_unicode_accidentals(self) -> None:
        assert _classify_key_mode("E\u266dm") is None
        r = _classify_key_mode("F\u266f minor")
        assert r is not None
        assert r[1] == "minor"

    def test_whitespace_stripped(self) -> None:
        assert _classify_key_mode("  G  ") == ("G", "major")

    def test_unparseable(self) -> None:
        assert _classify_key_mode("") is None
        assert _classify_key_mode("not a key") is None
        assert _classify_key_mode("X#") is None


# ── _bpm_bin ──────────────────────────────────────────────────────────────────


class TestBpmBin:
    def test_none(self) -> None:
        assert _bpm_bin(None) == "Unknown"

    def test_boundaries(self) -> None:
        assert _bpm_bin(0) == "<60"
        assert _bpm_bin(59) == "<60"
        assert _bpm_bin(60) == "60\u201379"
        assert _bpm_bin(79) == "60\u201379"
        assert _bpm_bin(80) == "80\u201399"
        assert _bpm_bin(99) == "80\u201399"
        assert _bpm_bin(100) == "100\u2013119"
        assert _bpm_bin(119) == "100\u2013119"
        assert _bpm_bin(120) == "120\u2013139"
        assert _bpm_bin(139) == "120\u2013139"
        assert _bpm_bin(140) == "140\u2013159"
        assert _bpm_bin(159) == "140\u2013159"
        assert _bpm_bin(160) == "160\u2013179"
        assert _bpm_bin(179) == "160\u2013179"
        assert _bpm_bin(180) == "180+"
        assert _bpm_bin(999) == "180+"


# ── _decade_bin ───────────────────────────────────────────────────────────────


class TestDecadeBin:
    def test_none(self) -> None:
        assert _decade_bin(None) == "Unknown"

    def test_various_years(self) -> None:
        assert _decade_bin(1973) == "1970s"
        assert _decade_bin(1984) == "1980s"
        assert _decade_bin(1999) == "1990s"
        assert _decade_bin(2000) == "2000s"
        assert _decade_bin(2026) == "2020s"
