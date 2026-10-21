"""Tests for library_stats.library_cache — SQLite cache CRUD and helpers.

Changed in 1.3.0: adds the ``path_fold`` migration/lookup tests, the
scope-selectivity rule tests (narrow scope uses ``idx_files_path_fold``, wide
scope keeps the sequential predicate, both return identical aggregates) and
the ``batch()`` transaction tests (deferred commit, rollback, nested groups).

Changed in 1.0.1: adds auto_vacuum regression tests asserting new cache
databases are born with the FULL flag and legacy files are converted on
connect so delete-heavy prunes never leave free-page bloat behind. Also in
1.0.1: pins ``query_aggregate``'s exact returned key set against its
docstring.
"""

from __future__ import annotations

import os
import sqlite3
import threading
import time
from pathlib import Path

import pytest

from library_stats.core.completeness import CompletenessReport, TagCompleteness
from library_stats.library_cache import (
    _POPULATE_SCOPE_INDEXED,
    _SCHEMA_SQL,
    _SCHEMA_VERSION,
    _SCOPE_COUNT_SQL,
    _SCOPE_PLAN_CACHE_LIMIT,
    _SCOPE_RANGE_HIGH,
    LibraryCache,
    _bpm_bin,
    _classify_key_mode,
    _decade_bin,
    _path_fold,
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


# ── LibraryCache: auto_vacuum (L2 regression) ────────────────────────────────


class TestAutoVacuum:
    """L2: delete-heavy cache operations must reclaim freed pages.

    ``remove_orphans``/``clear_dir``/``clear_all``/``INSERT OR REPLACE`` all
    free pages; without ``auto_vacuum=FULL`` they stay inside the database
    file and it grows without bound.  New databases must be born with the
    flag, and legacy files must be converted on first connect.
    """

    def test_new_database_has_full_auto_vacuum(self, tmp_path: Path) -> None:
        db = tmp_path / "fresh.db"
        with LibraryCache(db) as cache:
            row = cache._connect().execute("PRAGMA auto_vacuum").fetchone()
            assert row is not None
            assert int(row[0]) == 1  # FULL

    def test_existing_connection_is_not_revacuumed(self, tmp_path: Path) -> None:
        db = tmp_path / "persist.db"
        with LibraryCache(db) as cache:
            first = cache._connect().execute("PRAGMA auto_vacuum").fetchone()
        with LibraryCache(db) as cache:
            second = cache._connect().execute("PRAGMA auto_vacuum").fetchone()
        assert first == second
        assert int(first[0]) == 1

    def test_delete_heavy_legacy_database_is_converted(self, tmp_path: Path) -> None:
        """A cache without the flag keeps free pages; connecting converts it."""
        db = tmp_path / "legacy.db"
        raw = sqlite3.connect(str(db), timeout=30)
        try:
            raw.executescript(_SCHEMA_SQL)
            raw.execute("PRAGMA auto_vacuum = NONE")
            for i in range(1500):
                path = str(tmp_path / f"t{i}.mp3")
                raw.execute(
                    "INSERT OR REPLACE INTO files "
                    "(path_hash, path, dir_path, mtime, size, format) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    [_path_hash(path), path, str(tmp_path), float(i), 10, ".mp3"],
                )
            raw.commit()
            # Deleting every row leaves free pages inside the file (legacy bloat).
            raw.execute("DELETE FROM files")
            raw.commit()
            free_before = int(raw.execute("PRAGMA freelist_count").fetchone()[0])
            assert free_before > 0
        finally:
            raw.close()

        with LibraryCache(db):
            pass

        conn = sqlite3.connect(str(db), timeout=30)
        try:
            auto_vacuum = int(conn.execute("PRAGMA auto_vacuum").fetchone()[0])
            free_after = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        finally:
            conn.close()
        assert auto_vacuum == 1  # FULL
        assert free_after == 0  # VACUUM reclaimed the free pages


# ── LibraryCache: concurrency (P3 regression) ────────────────────────────────


class TestConcurrency:
    """P3: module-level lock + timeout=30 serialise cross-instance writers."""

    def test_instances_share_module_lock(self, tmp_path: Path) -> None:
        """Instances hold no private lock — serialisation is module-wide."""
        import library_stats.library_cache as mod

        a = LibraryCache(tmp_path / "a.db")
        b = LibraryCache(tmp_path / "b.db")
        try:
            assert not hasattr(a, "_lock")
            assert not hasattr(b, "_lock")
            assert isinstance(mod._DB_LOCK, type(threading.Lock()))
        finally:
            a.close()
            b.close()

    @pytest.mark.parametrize("n", (1, 5))
    def test_concurrent_writers_two_instances(self, tmp_path: Path, n: int) -> None:
        """Two instances, same DB file, barrier-synchronised writers.

        Per-instance locks cannot serialise separate connections, so this
        must rely on the shared module lock + busy timeout.  Parametrised
        repeat (n) makes the shared-lock determinism check explicit.
        """
        db = tmp_path / "shared.db"
        a = LibraryCache(db)
        b = LibraryCache(db)
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []
        writes_per_thread = 25

        def writer(cache: LibraryCache, prefix: str) -> None:
            try:
                barrier.wait(timeout=10)
                for i in range(writes_per_thread):
                    path = str(tmp_path / f"{prefix}{i}.mp3")
                    cache.upsert_file(path, mtime=float(i), size=1, format_ext=".mp3")
            except BaseException as exc:  # noqa: BLE001 — collected for assert
                errors.append(exc)

        ta = threading.Thread(target=writer, args=(a, "a"))
        tb = threading.Thread(target=writer, args=(b, "b"))
        ta.start()
        tb.start()
        ta.join(timeout=60)
        tb.join(timeout=60)
        try:
            assert not errors, f"concurrent writers raised: {errors!r}"
            assert a.row_count() == 2 * writes_per_thread
            assert b.row_count() == 2 * writes_per_thread
        finally:
            a.close()
            b.close()

    def test_upsert_waits_out_exclusive_transaction(self, tmp_path: Path) -> None:
        """A concurrent BEGIN EXCLUSIVE blocks upsert; it succeeds after."""
        db = tmp_path / "busy.db"
        cache = LibraryCache(db)
        cache._connect()  # create schema before the exclusive txn
        ready = threading.Event()

        def hold_exclusive() -> None:
            holder = sqlite3.connect(db, timeout=30, check_same_thread=False)
            try:
                holder.execute("BEGIN EXCLUSIVE")
                ready.set()
                time.sleep(0.5)  # keep the exclusive txn short
                holder.commit()
            finally:
                holder.close()

        t = threading.Thread(target=hold_exclusive)
        t.start()
        try:
            assert ready.wait(timeout=10)
            started = time.monotonic()
            cache.upsert_file(
                str(tmp_path / "waited.mp3"),
                mtime=1.0,
                size=1,
                format_ext=".mp3",
            )
            elapsed = time.monotonic() - started
            t.join(timeout=35)
            assert elapsed >= 0.3, "upsert did not block on the exclusive txn"
            assert elapsed < 30, "upsert exceeded the 30 s busy timeout"
            assert cache.row_count() == 1
        finally:
            t.join(timeout=35)
            cache.close()


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

    def test_key_set_matches_documented_contract(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        """Pin the exact aggregate key set consumed by ``StatsReport(**d)``.

        G7.2: the docstring previously listed fields that are never produced
        and omitted ones that are, so the returned keys are pinned here to
        stop the docstring and the mapping drifting apart again.
        """
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
        assert set(agg) == {
            "scan_path",
            "total_files",
            "total_albums",
            "total_artists",
            "format_breakdown",
            "genre_distribution",
            "key_distribution",
            "key_mode_distribution",
            "mood_distribution",
            "tempo_marking_distribution",
            "year_distribution",
            "top_artists",
            "top_genres",
            "missing_data",
        }
        # bpm_distribution is built by the cached-scan report path, not here.
        assert "bpm_distribution" not in agg


# ── LibraryCache: path_fold column, migration & batching (3.2) ───────────────

# Frozen copy of the pre-1.3.0 schema: a cache written by an older build must
# be migrated in place, so the literal is deliberately not ``_SCHEMA_SQL``.
_LEGACY_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
    path_hash TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    dir_path TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER,
    format TEXT,
    bpm INTEGER,
    key TEXT,
    genre TEXT,
    mood TEXT,
    tempo_marking TEXT,
    album_artist TEXT,
    artist_album TEXT,
    year INTEGER,
    scanned_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_files_dir ON files(dir_path);
"""


def _fill(cache: LibraryCache, root: Path, count: int) -> None:
    """Upsert *count* synthetic rows beneath *root*."""
    for i in range(count):
        cache.upsert_file(
            str(root / f"t{i}.mp3"), mtime=float(i), size=1, format_ext=".mp3"
        )


class TestPathFold:
    """The indexed ``path_fold`` column and its one-time migration."""

    def test_upsert_writes_path_fold(
        self, cache: LibraryCache, sample_file: str
    ) -> None:
        cache.upsert_file(sample_file, mtime=1.0, size=1, format_ext=".mp3")
        row = cache._connect().execute("SELECT path_fold FROM files").fetchone()
        assert row is not None
        assert row[0] == _path_fold(sample_file)

    def test_legacy_database_is_migrated_in_place(self, tmp_path: Path) -> None:
        db = tmp_path / "legacy.db"
        path = str(tmp_path / "Song.mp3")
        raw = sqlite3.connect(str(db), timeout=30)
        try:
            raw.executescript(_LEGACY_SCHEMA_SQL)
            assert int(raw.execute("PRAGMA user_version").fetchone()[0]) == 0
            raw.execute(
                "INSERT INTO files "
                "(path_hash, path, dir_path, mtime, size, format) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [_path_hash(path), path, str(tmp_path), 1.0, 1, ".mp3"],
            )
            raw.commit()
        finally:
            raw.close()

        with LibraryCache(db) as cache:
            conn = cache._connect()
            version = int(conn.execute("PRAGMA user_version").fetchone()[0])
            assert version == _SCHEMA_VERSION
            row = conn.execute("SELECT path_fold FROM files").fetchone()
            assert row is not None
            # Backfilled rows keep every scoped read working.
            assert row[0] == _path_fold(path)
            assert cache.row_count(str(tmp_path)) == 1
            assert list(cache.get_cached_mtimes(str(tmp_path))) == [path]
            agg = cache.query_aggregate(str(tmp_path))
            assert agg is not None
            assert agg["total_files"] == 1

    def test_migration_runs_once(self, tmp_path: Path) -> None:
        db = tmp_path / "once.db"
        with LibraryCache(db) as cache:
            cache.upsert_file(
                str(tmp_path / "a.mp3"), mtime=1.0, size=1, format_ext=".mp3"
            )
        with LibraryCache(db) as cache:
            conn = cache._connect()
            assert int(conn.execute("PRAGMA user_version").fetchone()[0]) == (
                _SCHEMA_VERSION
            )
            # Re-running the migration must not duplicate rows or lose data.
            assert cache.row_count() == 1
            assert (
                cache._connect()
                .execute("SELECT COUNT(*) FROM files WHERE path_fold IS NULL")
                .fetchone()[0]
                == 0
            )


class TestScopePredicate:
    """Index range for narrow scopes, sequential INSTR for wide ones."""

    def test_narrow_scope_uses_index_range(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        _fill(cache, tmp_path / "big", 20)
        _fill(cache, tmp_path / "small", 2)

        small = str(tmp_path / "small")
        assert cache.scope_plan_kind(small) == "indexed"

        prefix = _path_fold(LibraryCache._path_prefix(small))
        plan = (
            cache._connect()
            .execute(
                "EXPLAIN QUERY PLAN " + _POPULATE_SCOPE_INDEXED,
                [prefix, prefix + _SCOPE_RANGE_HIGH],
            )
            .fetchall()
        )
        assert any("idx_files_path_fold" in str(row) for row in plan)

        cache.select_scope(small)
        assert cache._connect().execute(_SCOPE_COUNT_SQL).fetchone()[0] == 2

    def test_wide_scope_uses_sequential_plan(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        _fill(cache, tmp_path, 20)
        assert cache.scope_plan_kind(str(tmp_path)) == "sequential"

        cache.select_scope(str(tmp_path))
        assert cache._connect().execute(_SCOPE_COUNT_SQL).fetchone()[0] == 20

    def test_narrow_scope_sees_only_its_own_rows(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        _fill(cache, tmp_path / "big", 20)
        _fill(cache, tmp_path / "small", 2)
        small = str(tmp_path / "small")

        assert cache.row_count(small) == 2
        mtimes = cache.get_cached_mtimes(small)
        assert len(mtimes) == 2
        assert all(os.path.normcase(small) in os.path.normcase(p) for p in mtimes)
        agg = cache.query_aggregate(small)
        assert agg is not None
        assert agg["total_files"] == 2

    def test_index_and_sequential_paths_agree(self, tmp_path: Path) -> None:
        """The rule chooses a plan, never a different answer."""
        indexed = LibraryCache(tmp_path / "indexed.db")
        sequential = LibraryCache(tmp_path / "sequential.db")
        try:
            _fill(indexed, tmp_path / "big", 20)
            _fill(indexed, tmp_path / "small", 2)
            _fill(sequential, tmp_path / "small", 2)

            small = str(tmp_path / "small")
            assert indexed.scope_plan_kind(small) == "indexed"
            assert sequential.scope_plan_kind(small) == "sequential"

            a = indexed.query_aggregate(small)
            b = sequential.query_aggregate(small)
            assert a is not None and b is not None
            a.pop("scan_path")
            b.pop("scan_path")
            assert a == b
        finally:
            indexed.close()
            sequential.close()


class TestSingleStatementPlan:
    """The one-statement reads take the plan the multi-statement reports do.

    Changed in 1.4.1: ``get_cached_mtimes``, ``remove_orphans`` and
    ``clear_dir`` used to run the sequential predicate regardless of scope, so
    the index existed for the report path only (PLAN D97).  These tests read
    the statements the connection actually executed - a plan decision is only
    real if the SQL changed - and EXPLAIN each one.
    """

    @staticmethod
    def _executed(cache: LibraryCache) -> list[str]:
        """Return every statement the connection executes from now on."""
        statements: list[str] = []
        cache._connect().set_trace_callback(statements.append)
        return statements

    @staticmethod
    def _by_operation(statements: list[str]) -> dict[str, list[str]]:
        """Group the scoped statements by the operation that issued them."""
        return {
            "mtimes": [s for s in statements if s.startswith("SELECT path, mtime")],
            "orphans": [s for s in statements if s.startswith("SELECT path_hash")],
            # ``remove_orphans`` also deletes by path_hash; that is its own
            # follow-up write, not the scoped statement under test.
            "clear": [
                s
                for s in statements
                if s.startswith("DELETE FROM files") and "path_hash" not in s
            ],
        }

    def test_a_narrow_scope_reads_and_deletes_through_the_index(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        _fill(cache, tmp_path / "big", 40)
        _fill(cache, tmp_path / "small", 2)
        small = str(tmp_path / "small")
        assert cache.scope_plan_kind(small) == "indexed"

        statements = self._executed(cache)
        try:
            cache.get_cached_mtimes(small)
            cache.remove_orphans(small, set())
            cache.clear_dir(small)
        finally:
            cache._connect().set_trace_callback(None)

        grouped = self._by_operation(statements)
        # The discovered set must be complete: a scan that matched nothing
        # would otherwise pass every assertion below.
        assert set(grouped) == {"mtimes", "orphans", "clear"}
        for operation, found in grouped.items():
            assert len(found) == 1, (operation, found)
            assert "path_fold >=" in found[0], (operation, found[0])
            assert "INSTR" not in found[0], (operation, found[0])
            plan = cache._connect().execute("EXPLAIN QUERY PLAN " + found[0]).fetchall()
            assert any("idx_files_path_fold" in str(row) for row in plan), (
                operation,
                plan,
            )

    def test_a_wide_scope_keeps_the_sequential_predicate(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        _fill(cache, tmp_path, 40)
        root = str(tmp_path)
        assert cache.scope_plan_kind(root) == "sequential"

        statements = self._executed(cache)
        try:
            cache.get_cached_mtimes(root)
            cache.remove_orphans(root, set())
            cache.clear_dir(root)
        finally:
            cache._connect().set_trace_callback(None)

        grouped = self._by_operation(statements)
        assert set(grouped) == {"mtimes", "orphans", "clear"}
        for operation, found in grouped.items():
            assert len(found) == 1, (operation, found)
            assert "INSTR(LOWER(path)" in found[0], (operation, found[0])
            assert "path_fold" not in found[0], (operation, found[0])

    def _plan_pair(self, tmp_path: Path) -> tuple[LibraryCache, LibraryCache]:
        """Return two caches whose *same* scope resolves to opposite plans."""
        indexed = LibraryCache(tmp_path / "indexed.db")
        sequential = LibraryCache(tmp_path / "sequential.db")
        _fill(indexed, tmp_path / "small", 2)
        _fill(indexed, tmp_path / "big", 40)
        _fill(sequential, tmp_path / "small", 2)
        # scoped * 2 (4) is not below the total (3), so the rule keeps the scan.
        _fill(sequential, tmp_path / "big", 1)
        return indexed, sequential

    def test_both_plans_return_the_same_mtimes(self, tmp_path: Path) -> None:
        indexed, sequential = self._plan_pair(tmp_path)
        small = str(tmp_path / "small")
        try:
            assert indexed.scope_plan_kind(small) == "indexed"
            assert sequential.scope_plan_kind(small) == "sequential"

            assert indexed.get_cached_mtimes(small) == sequential.get_cached_mtimes(
                small
            )
            assert indexed.get_cached_mtimes(str(tmp_path / "nope")) == {}
        finally:
            indexed.close()
            sequential.close()

    def test_both_plans_remove_the_same_orphans(self, tmp_path: Path) -> None:
        indexed, sequential = self._plan_pair(tmp_path)
        small = str(tmp_path / "small")
        try:
            removed_indexed = indexed.remove_orphans(small, set())
            removed_sequential = sequential.remove_orphans(small, set())

            assert removed_indexed == removed_sequential == 2
            assert indexed.get_cached_mtimes(small) == {}
            assert sequential.get_cached_mtimes(small) == {}
            # The sibling directory is untouched by either plan.
            assert indexed.row_count(str(tmp_path / "big")) == 40
            assert sequential.row_count(str(tmp_path / "big")) == 1
        finally:
            indexed.close()
            sequential.close()

    def test_both_plans_clear_the_same_scope(self, tmp_path: Path) -> None:
        indexed, sequential = self._plan_pair(tmp_path)
        small = str(tmp_path / "small")
        try:
            indexed.clear_dir(small)
            sequential.clear_dir(small)

            assert indexed.row_count(small) == 0
            assert sequential.row_count(small) == 0
            assert indexed.row_count(str(tmp_path / "big")) == 40
            assert sequential.row_count(str(tmp_path / "big")) == 1
        finally:
            indexed.close()
            sequential.close()


class TestScopePlanMemo:
    """The plan decision is paid once per directory, not once per operation.

    Changed in 1.4.1: PLAN P1 measured `scope_plan_kind` at **15.91 ms** on a
    200 000-row cache (two `COUNT(*)` queries) and every scoped single-statement
    operation paid it, so one scan asking three questions about one directory
    ran the counts three times.  A cached plan can only ever be *suboptimal*
    (both statements return the same rows), which is why a memo is safe here.
    """

    @staticmethod
    def _counts(cache: LibraryCache) -> list[str]:
        """Trace the statements from now on and return the scope `COUNT`s."""
        statements: list[str] = []
        cache._connect().set_trace_callback(statements.append)
        return statements

    @staticmethod
    def _scope_counts(statements: list[str]) -> list[str]:
        """Return the two scope-decision queries among *statements*."""
        return [s for s in statements if s.startswith("SELECT COUNT(*)")]

    def test_the_decision_is_paid_once_for_three_operations(
        self, tmp_path: Path
    ) -> None:
        """`get_cached_mtimes` + `remove_orphans` + `clear_dir` = one decision."""
        cache = LibraryCache(tmp_path / "cache.db")
        try:
            _fill(cache, tmp_path / "small", 2)
            _fill(cache, tmp_path / "big", 40)
            small = str(tmp_path / "small")
            statements = self._counts(cache)

            cache.get_cached_mtimes(small)
            cache.remove_orphans(small, set())
            cache.clear_dir(small)
            cache._connect().set_trace_callback(None)

            counts = self._scope_counts(statements)
            assert len(counts) == 2, f"the scope was decided more than once: {counts}"
        finally:
            cache.close()

    def test_a_second_scan_of_the_same_directory_reuses_the_decision(
        self, tmp_path: Path
    ) -> None:
        """A long scan must not re-decide on every file batch."""
        cache = LibraryCache(tmp_path / "cache.db")
        try:
            _fill(cache, tmp_path / "small", 2)
            _fill(cache, tmp_path / "big", 40)
            small = str(tmp_path / "small")
            cache.get_cached_mtimes(small)

            statements = self._counts(cache)
            cache.get_cached_mtimes(small)
            cache.remove_orphans(small, set())
            cache._connect().set_trace_callback(None)

            assert self._scope_counts(statements) == []
        finally:
            cache.close()

    def test_invalidate_forces_a_recount(self, tmp_path: Path) -> None:
        """The escape hatch exists for a caller whose shape really changed."""
        cache = LibraryCache(tmp_path / "cache.db")
        try:
            _fill(cache, tmp_path / "small", 2)
            _fill(cache, tmp_path / "big", 40)
            small = str(tmp_path / "small")
            cache.get_cached_mtimes(small)
            cache.invalidate_scope_plans()

            statements = self._counts(cache)
            cache.get_cached_mtimes(small)
            cache._connect().set_trace_callback(None)

            assert len(self._scope_counts(statements)) == 2
        finally:
            cache.close()

    def test_a_stale_plan_still_returns_the_same_rows(self, tmp_path: Path) -> None:
        """Staleness is a performance question, never a correctness one."""
        cache = LibraryCache(tmp_path / "cache.db")
        try:
            _fill(cache, tmp_path / "small", 2)
            _fill(cache, tmp_path / "big", 40)
            small = str(tmp_path / "small")
            assert cache._plan_for(small) == "indexed"

            # Grow the scope until the *current* answer flips to sequential;
            # the memo keeps the indexed plan and must still return every row.
            _fill(cache, tmp_path / "small", 100)
            assert cache.scope_plan_kind(small) == "sequential"
            assert cache._plan_for(small) == "indexed"
            stale = cache.get_cached_mtimes(small)

            cache.invalidate_scope_plans()
            assert cache._plan_for(small) == "sequential"
            assert cache.get_cached_mtimes(small) == stale
            assert stale, "the comparison is vacuous if the scope is empty"
        finally:
            cache.close()

    def test_clear_all_forgets_every_decision(self, tmp_path: Path) -> None:
        """After a wipe every remembered ratio is meaningless."""
        cache = LibraryCache(tmp_path / "cache.db")
        try:
            _fill(cache, tmp_path / "small", 2)
            _fill(cache, tmp_path / "big", 40)
            cache._plan_for(str(tmp_path / "small"))
            cache.clear_all()
            assert cache._scope_plans == {}
        finally:
            cache.close()

    def test_the_memo_is_bounded(self, tmp_path: Path) -> None:
        """A huge tree cannot grow the memo without limit."""
        cache = LibraryCache(tmp_path / "cache.db")
        try:
            _fill(cache, tmp_path / "big", 40)
            for index in range(_SCOPE_PLAN_CACHE_LIMIT + 20):
                cache._plan_for(str(tmp_path / f"dir_{index}"))
            assert len(cache._scope_plans) <= _SCOPE_PLAN_CACHE_LIMIT
        finally:
            cache.close()


class TestBatch:
    """``batch()`` groups writes into one transaction (commit-per-row is slow)."""

    def test_commit_deferred_until_block_exits(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        cache._connect()
        reader = sqlite3.connect(str(cache.db_path), timeout=30)
        try:
            with cache.batch():
                _fill(cache, tmp_path, 5)
                # A separate connection cannot see uncommitted rows: proof the
                # block owns the transaction instead of committing per row.
                assert reader.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
            assert reader.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 5
        finally:
            reader.close()

    def test_exception_rolls_the_group_back(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        with pytest.raises(RuntimeError):
            with cache.batch():
                _fill(cache, tmp_path, 3)
                raise RuntimeError("boom")
        assert cache.row_count() == 0

    def test_nested_batches_commit_once(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        cache._connect()
        reader = sqlite3.connect(str(cache.db_path), timeout=30)
        try:
            with cache.batch():
                _fill(cache, tmp_path / "outer", 2)
                with cache.batch():
                    _fill(cache, tmp_path / "inner", 2)
                # The inner block must not commit on the outer block's behalf.
                assert reader.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 0
            assert reader.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 4
        finally:
            reader.close()


# ── LibraryCache: completeness trend history (3.3) ──────────────────────────


def _report(directory: Path, total: int, pct: float) -> CompletenessReport:
    """Build a minimal completeness report for history tests."""
    return CompletenessReport(
        directory=str(directory),
        total_files=total,
        tag_results={
            "bpm": TagCompleteness(
                field="bpm",
                total=total,
                present=int(total * pct / 100),
                missing=total - int(total * pct / 100),
                pct_complete=pct,
            )
        },
        overall_pct=pct,
    )


class TestCompletenessHistory:
    """Trend history lives in the cache DB, deduped and pruned (PLAN D41)."""

    def test_record_and_read_back(self, cache: LibraryCache, tmp_path: Path) -> None:
        assert cache.record_completeness_snapshot(_report(tmp_path, 10, 75.0)) is True

        history = cache.completeness_history(str(tmp_path))
        assert len(history) == 1
        assert history[0]["total_files"] == 10
        assert history[0]["overall_pct"] == 75.0
        assert history[0]["tag_pcts"]["bpm"] == 75.0
        assert history[0]["recorded_at"]

    def test_consecutive_duplicate_is_suppressed(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        assert cache.record_completeness_snapshot(_report(tmp_path, 10, 75.0)) is True
        assert cache.record_completeness_snapshot(_report(tmp_path, 10, 75.0)) is False
        assert len(cache.completeness_history(str(tmp_path))) == 1

    def test_a_changed_scan_is_a_new_snapshot(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        cache.record_completeness_snapshot(_report(tmp_path, 10, 75.0))
        assert cache.record_completeness_snapshot(_report(tmp_path, 10, 80.0)) is True
        assert len(cache.completeness_history(str(tmp_path))) == 2

    def test_history_is_oldest_first(self, cache: LibraryCache, tmp_path: Path) -> None:
        for pct in (10.0, 20.0, 30.0):
            cache.record_completeness_snapshot(_report(tmp_path, 5, pct))

        values = [h["overall_pct"] for h in cache.completeness_history(str(tmp_path))]
        assert values == [10.0, 20.0, 30.0]

    def test_limit_keeps_the_newest(self, cache: LibraryCache, tmp_path: Path) -> None:
        for pct in (10.0, 20.0, 30.0, 40.0):
            cache.record_completeness_snapshot(_report(tmp_path, 5, pct))

        values = [
            h["overall_pct"] for h in cache.completeness_history(str(tmp_path), limit=2)
        ]
        assert values == [30.0, 40.0]

    def test_history_is_per_directory(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        one = tmp_path / "one"
        two = tmp_path / "two"
        cache.record_completeness_snapshot(_report(one, 3, 50.0))
        cache.record_completeness_snapshot(_report(two, 7, 90.0))

        one_history = cache.completeness_history(str(one))
        two_history = cache.completeness_history(str(two))
        assert [h["total_files"] for h in one_history] == [3]
        assert [h["total_files"] for h in two_history] == [7]

    def test_old_snapshots_are_pruned(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        from library_stats.library_cache import _HISTORY_SNAPSHOTS

        for i in range(_HISTORY_SNAPSHOTS + 5):
            cache.record_completeness_snapshot(
                _report(tmp_path, 5, float(i % 100) + 0.5)
            )

        history = cache.completeness_history(str(tmp_path), limit=500)
        assert len(history) == _HISTORY_SNAPSHOTS
        # The newest snapshot survives the prune.
        assert history[-1]["overall_pct"] == float((_HISTORY_SNAPSHOTS + 4) % 100) + 0.5

    def test_clear_one_directory_and_all(
        self, cache: LibraryCache, tmp_path: Path
    ) -> None:
        one = tmp_path / "one"
        two = tmp_path / "two"
        cache.record_completeness_snapshot(_report(one, 3, 50.0))
        cache.record_completeness_snapshot(_report(two, 7, 90.0))

        assert cache.clear_completeness_history(str(one)) == 1
        assert cache.completeness_history(str(one)) == []
        assert cache.completeness_history(str(two))

        assert cache.clear_completeness_history() == 1
        assert cache.completeness_history(str(two)) == []

    def test_history_table_survives_reconnect(self, tmp_path: Path) -> None:
        db = tmp_path / "persist.db"
        with LibraryCache(db) as cache:
            cache.record_completeness_snapshot(_report(tmp_path, 4, 25.0))
        with LibraryCache(db) as cache:
            history = cache.completeness_history(str(tmp_path))
        assert len(history) == 1
        assert history[0]["total_files"] == 4


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
