"""
library_cache.py — SQLite-backed metadata cache for library statistics.

Provides incremental and full scans that cache audio file tag metadata,
avoiding re-reading tags on every dashboard load.  The cache stores raw
values only; aggregation and binning are handled by the caller.

Schema (matches FUTURE_ENHANCEMENTS.md proposal):
    files (
        path_hash TEXT PRIMARY KEY,   -- SHA-256 of the absolute path
        path TEXT NOT NULL,
        path_fold TEXT,                -- LOWER(path), indexed for scoped queries
        dir_path TEXT NOT NULL,        -- parent directory (for scoped queries)
        mtime REAL NOT NULL,           -- file mtime at last scan
        size INTEGER,
        format TEXT,                   -- file extension e.g. ".mp3"
        bpm INTEGER,
        key TEXT,
        genre TEXT,
        mood TEXT,
        tempo_marking TEXT,
        album_artist TEXT,
        artist_album TEXT,             -- JSON array: [artist, album]
        year INTEGER,
        scanned_at TEXT DEFAULT (datetime('now'))
    )
    completeness_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        path_fold TEXT NOT NULL,       -- scope key (folded directory prefix)
        path TEXT NOT NULL,            -- the directory, for humans
        recorded_at TEXT NOT NULL,
        total_files INTEGER NOT NULL,
        overall_pct REAL NOT NULL,
        tag_pcts TEXT NOT NULL         -- JSON: {field: pct_complete}
    )

Concurrency:
    Connection creation is serialised by a module-level lock shared by every
    instance (per-instance locks cannot serialise separate connections to the
    same DB file), and each connection waits up to 30 s (``timeout=30`` +
    ``PRAGMA busy_timeout``) for a competing writer rather than raising
    ``OperationalError: database is locked`` — the pattern documented in
    AGENTS.md and used by ``audio_suite_shared.batch_undo``.

Changed in 1.3.0: the same database also carries the completeness trend history
(``completeness_history``, schema version 3): ``record_completeness_snapshot``
skips a snapshot identical to the previous one for that directory and prunes
to the newest 100, ``completeness_history`` returns them oldest-first for a
time series, and ``clear_completeness_history`` forgets them.  Structured state
belongs in the SQLite file the tool already owns rather than a side-car JSON.

Changed in 1.3.0: multi-statement reports resolve their directory once into a
per-connection ``temp._scope_files`` copy (``select_scope``), choosing between
an indexed range scan on ``path_fold`` and the original sequential
``INSTR(LOWER(path), …)`` predicate from measured selectivity
(``scoped * 2 < total``).  An index only pays off when the scope is a small
slice of the cache; at whole-library selectivity a sequential scan is faster
(measured 9.9 ms vs 13.5 ms over 20 000 rows), so the plan is never
unconditional.  Single-statement reads (``get_cached_mtimes``,
``row_count``, ``remove_orphans``, ``clear_dir``) go straight at ``files``:
copying a 20 000-row scope costs more than the one scan it would save
(70 ms against 17 ms).  Every statement is a complete SQL literal — the plan is
decided by :meth:`LibraryCache.scope_plan_kind` instead of interpolated into a
statement, so no query is assembled by string formatting (bandit B608) — and
``upsert_file`` writes ``path_fold``; legacy databases are migrated on connect
(``PRAGMA user_version``).  Writes can be grouped with ``batch()``:
commit-per-row cost 39.1 s on 20 000 rows against 0.24 s for one
transaction.

Changed in 1.4.1: the single-statement scoped reads take the same plan the
multi-statement reports do (``get_cached_mtimes``, ``remove_orphans`` and
``clear_dir``), so a narrow scope scans the ``path_fold`` index instead of
running ``INSTR`` over every row (PLAN D97).  The rule is the measured one in
:meth:`LibraryCache.scope_plan_kind`; a wide scope keeps the sequential scan,
because the index loses at whole-library selectivity.

Changed in 2.1.7: freshness is the stamp ``(mtime, size)``, not the mtime
alone (R-13).  A file replaced by a copy that preserves its timestamps keeps
its mtime, so an mtime-only comparison answered "cached" for a file whose tags
had never been read and the report served pre-edit values.  ``get_cached_stamps``
is what a scan compares; ``file_is_cached`` takes the size as an optional third
argument (omitting it keeps the coarse answer, which now says so in its
docstring).

Changed in 1.0.1: the cache database is created (or one-time converted on
connect) with ``auto_vacuum=FULL``, so delete-heavy operations
(``remove_orphans``/``clear_dir``/``clear_all``/``INSERT OR REPLACE``) return
freed pages to the OS instead of leaving the file permanently grown. Also in
1.0.1: ``query_aggregate``'s docstring now lists exactly the keys it returns
(``scan_path`` and ``key_mode_distribution`` included; ``bpm_distribution``
is built by the cached-scan report path, not here).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Global lock shared by every LibraryCache instance: SQLite only permits one
# writer at a time, and separate instances must not step on each other.
_DB_LOCK = threading.Lock()

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS files (
    path_hash TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    path_fold TEXT,
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
-- idx_files_path_fold is created by ``_migrate``: a legacy table has no
-- ``path_fold`` column yet, so the statement cannot live in this script.
"""

# Bumped whenever ``_SCHEMA_SQL``/an in-place migration changes the on-disk
# shape; ``PRAGMA user_version`` carries it so a migration runs exactly once.
#   2 — files.path_fold + idx_files_path_fold
#   3 — completeness_history + idx_history_path_fold
_SCHEMA_VERSION = 3

#: Snapshots kept per scanned directory; older ones are pruned on insert.
_HISTORY_SNAPSHOTS = 100

# Upper bound for a prefix range scan on ``path_fold``.  SQLite compares TEXT
# with BINARY collation, so every string that starts with the prefix sorts
# below ``prefix + U+10FFFF``.
_SCOPE_RANGE_HIGH = "\U0010ffff"

#: How many directory -> plan decisions an instance remembers (PLAN P1).  A
#: cached scan visits a handful of directories; the bound exists so a
#: long-lived instance walking a huge tree cannot grow without limit.
_SCOPE_PLAN_CACHE_LIMIT = 128

# Per-connection scratch copy of the selected directory's rows.  Resolving the
# scope once keeps every scoped statement a complete SQL literal: the
# selectivity decision lives in ``select_scope`` instead of being written twice
# into fifteen statements, and no SQL is assembled by string formatting (bandit
# B608 flags exactly that, and the security gate is 0 Medium).
_SCOPE_TABLE_SQL = """CREATE TEMP TABLE IF NOT EXISTS _scope_files (
    path_hash TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    mtime REAL NOT NULL,
    format TEXT,
    bpm INTEGER,
    key TEXT,
    genre TEXT,
    mood TEXT,
    tempo_marking TEXT,
    album_artist TEXT,
    artist_album TEXT,
    year INTEGER
)"""
_CLEAR_SCOPE_SQL = "DELETE FROM temp._scope_files"
_POPULATE_SCOPE_INDEXED = """INSERT INTO temp._scope_files
    (path_hash, path, mtime, format, bpm, key, genre, mood,
     tempo_marking, album_artist, artist_album, year)
SELECT path_hash, path, mtime, format, bpm, key, genre, mood,
       tempo_marking, album_artist, artist_album, year
FROM files
WHERE path_fold >= ? AND path_fold < ?"""
_POPULATE_SCOPE_SEQUENTIAL = """INSERT INTO temp._scope_files
    (path_hash, path, mtime, format, bpm, key, genre, mood,
     tempo_marking, album_artist, artist_album, year)
SELECT path_hash, path, mtime, format, bpm, key, genre, mood,
       tempo_marking, album_artist, artist_album, year
FROM files
WHERE INSTR(LOWER(path), LOWER(?)) = 1"""
_SCOPE_COUNT_SQL = "SELECT COUNT(*) FROM temp._scope_files"

# Single-statement scoped reads and deletes, in both plans.  They are module
# constants rather than literals inside three methods so the benchmark can time
# exactly the SQL the methods run: a measurement of a hand-copied statement
# could drift from production and read as a speed-up that never shipped.
_SCOPED_MTIMES_INDEXED = (
    "SELECT path, mtime FROM files WHERE path_fold >= ? AND path_fold < ?"
)
_SCOPED_MTIMES_SEQUENTIAL = (
    "SELECT path, mtime FROM files WHERE INSTR(LOWER(path), LOWER(?)) = 1"
)
# The freshness stamp a scan compares against.  ``size`` is not decoration: a
# file replaced with an identical mtime (a copy that preserves timestamps, a
# same-second rewrite, a restored backup) is a different file, and mtime alone
# cannot see it (R-13).
_SCOPED_STAMPS_INDEXED = (
    "SELECT path, mtime, size FROM files WHERE path_fold >= ? AND path_fold < ?"
)
_SCOPED_STAMPS_SEQUENTIAL = (
    "SELECT path, mtime, size FROM files WHERE INSTR(LOWER(path), LOWER(?)) = 1"
)
_SCOPED_HASHES_INDEXED = (
    "SELECT path_hash FROM files WHERE path_fold >= ? AND path_fold < ?"
)
_SCOPED_HASHES_SEQUENTIAL = (
    "SELECT path_hash FROM files WHERE INSTR(LOWER(path), LOWER(?)) = 1"
)
_SCOPED_CLEAR_INDEXED = "DELETE FROM files WHERE path_fold >= ? AND path_fold < ?"
_SCOPED_CLEAR_SEQUENTIAL = "DELETE FROM files WHERE INSTR(LOWER(path), LOWER(?)) = 1"

# SQLite auto_vacuum mode meaning FULL (deleted pages are returned to the OS
# at commit, so delete-heavy caches never leave free-page bloat behind).
_AUTO_VACUUM_FULL = 1


def _path_hash(filepath: str) -> str:
    return hashlib.sha256(os.path.normpath(filepath).encode("utf-8")).hexdigest()


def _path_fold(filepath: str) -> str:
    """Return the lower-cased normalised path stored in ``path_fold``.

    Python's ``str.lower`` (not SQLite's ASCII-only ``LOWER``) so a path with
    non-ASCII characters hashes to the same value whether it was written by an
    upsert or backfilled by the migration.
    """
    return os.path.normpath(filepath).lower()


class LibraryCache:
    """SQLite-backed persistent cache for audio file tag metadata.

    Designed for incremental scanning: compare current file mtimes against
    cached values and only re-read tags for files that changed.

    Usage as context manager::

        with LibraryCache() as cache:
            cache.upsert_file(...)
            report_dict = cache.query_aggregate("/music")
    """

    def __init__(self, cache_path: str | Path | None = None) -> None:
        self._path = (
            Path(cache_path)
            if cache_path
            else (Path.home() / ".audiosuite" / "library_cache.db")
        )
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        # Nesting depth of ``batch()``; commits are deferred while it is > 0.
        self._batch_depth = 0
        # Normalised directory -> scope plan, so one scan pays the two COUNT
        # queries once per directory instead of once per operation (PLAN P1).
        self._scope_plans: dict[str, str] = {}

    # ── Connection management ─────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            with _DB_LOCK:
                if self._conn is None:
                    self._conn = sqlite3.connect(
                        str(self._path), check_same_thread=False, timeout=30
                    )
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    self._conn.execute("PRAGMA busy_timeout=30000")
                    # The scope copy lives in RAM; without this SQLite spills
                    # it to a temp file and a 20 000-row scan pays ~30 ms of
                    # disk churn per selection.
                    self._conn.execute("PRAGMA temp_store=MEMORY")
                    self._conn.executescript(_SCHEMA_SQL)
                    self._migrate(self._conn)
                    self._enable_auto_vacuum(self._conn)
                    self._conn.execute(_SCOPE_TABLE_SQL)
        return self._conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Bring an existing cache file up to ``_SCHEMA_VERSION`` in place.

        Version 2 adds ``path_fold`` plus its index and backfills existing
        rows; version 3 adds the completeness trend table.  The column is
        added with ``ALTER TABLE`` so no user data is rewritten, and the
        backfill runs through ``_path_fold`` (Python) rather than SQL ``LOWER``
        so it agrees byte-for-byte with ``upsert_file``.  Must be called under
        ``_DB_LOCK`` with no open transaction.
        """
        row = conn.execute("PRAGMA user_version").fetchone()
        version = int(row[0]) if row is not None else 0
        if version >= _SCHEMA_VERSION:
            return
        columns = {r[1] for r in conn.execute("PRAGMA table_info(files)")}
        if "path_fold" not in columns:
            conn.execute("ALTER TABLE files ADD COLUMN path_fold TEXT")
        missing = conn.execute(
            "SELECT rowid, path FROM files WHERE path_fold IS NULL"
        ).fetchall()
        if missing:
            conn.executemany(
                "UPDATE files SET path_fold = ? WHERE rowid = ?",
                [(_path_fold(path), rowid) for rowid, path in missing],
            )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_files_path_fold ON files(path_fold)"
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS completeness_history (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   path_fold TEXT NOT NULL,
                   path TEXT NOT NULL,
                   recorded_at TEXT NOT NULL DEFAULT (datetime('now')),
                   total_files INTEGER NOT NULL,
                   overall_pct REAL NOT NULL,
                   tag_pcts TEXT NOT NULL
               )"""
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_history_path_fold "
            "ON completeness_history(path_fold, id)"
        )
        conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        conn.commit()

    def _commit(self) -> None:
        """Commit now, unless a ``batch()`` block owns the transaction."""
        if self._batch_depth == 0 and self._conn is not None:
            self._conn.commit()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Group every write inside the block into one transaction.

        Commit-per-row is the cache's dominant scan cost (37.3 s for 20 000
        rows against 0.18 s batched), so a cached scan wraps its upserts in
        this block.  Nested blocks are reference-counted; only the outermost
        commits, and any exception rolls the whole group back.
        """
        conn = self._connect()
        self._batch_depth += 1
        try:
            yield
        except BaseException:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                conn.rollback()
            raise
        else:
            self._batch_depth -= 1
            if self._batch_depth == 0:
                conn.commit()

    def _enable_auto_vacuum(self, conn: sqlite3.Connection) -> None:
        """Ensure the cache reclaims freed pages automatically.

        Sets the persistent ``auto_vacuum=FULL`` file flag so every prune
        (``remove_orphans``/``clear_dir``/``clear_all``/``INSERT OR REPLACE``)
        returns freed pages to the operating system at commit instead of
        leaving them inside a permanently growing database file.  Files that
        predate the flag are converted in place with a one-time ``VACUUM``;
        once the flag is set, later connects only read it and skip.  Must be
        called under ``_DB_LOCK`` with no open transaction.
        """
        row = conn.execute("PRAGMA auto_vacuum").fetchone()
        if row is not None and int(row[0]) == _AUTO_VACUUM_FULL:
            return
        conn.execute("PRAGMA auto_vacuum = FULL")
        conn.commit()
        conn.execute("VACUUM")

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> LibraryCache:
        self._connect()
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    @property
    def db_path(self) -> Path:
        return self._path

    # ── Row-level operations ──────────────────────────────────────────

    @staticmethod
    def _path_prefix(dir_path: str) -> str:
        """Normalize a directory path into a prefix for INSTR matching.

        Ensures a trailing separator so that ``D:\\Music`` becomes
        ``D:\\Music\\`` and correctly matches only files under that tree.
        """
        normalized = os.path.normpath(dir_path)
        if not normalized.endswith(os.sep):
            normalized += os.sep
        return normalized

    def scope_plan_kind(self, dir_path: str) -> str:
        """Return which scope plan *dir_path* would use: ``indexed``/``sequential``.

        An index only pays off when the scope is a small slice of the cache; at
        whole-library selectivity a sequential scan is faster (measured 9.9 ms
        vs 13.5 ms over 20 000 rows), so the plan is chosen from the actual row
        counts — never unconditionally.  This always re-counts, because a
        caller asking the question wants the current answer; the hot callers
        below go through :meth:`_plan_for`, which memoises it.
        """
        conn = self._connect()
        prefix = _path_fold(self._path_prefix(dir_path))
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        if total:
            scoped = conn.execute(
                "SELECT COUNT(*) FROM files WHERE path_fold >= ? AND path_fold < ?",
                [prefix, prefix + _SCOPE_RANGE_HIGH],
            ).fetchone()[0]
            if scoped * 2 < total:
                return "indexed"
        return "sequential"

    def _plan_for(self, dir_path: str) -> str:
        """Return the cached plan for *dir_path*, deciding it at most once.

        The decision costs two ``COUNT(*)`` queries (measured **15.91 ms** on a
        200 000-row cache) and every scoped single-statement operation used to
        pay it: three calls for the same directory during one cached scan ran
        the counts three times.  The memo keeps one decision per directory for
        this instance's lifetime.

        A stale plan is safe, and that is why this can be a plain memo: the
        plan chooses a *path* to the same rows, never which rows are returned
        (both statements are equality-equivalent and the suite asserts it).  A
        write from another connection can therefore make the memo suboptimal,
        never wrong; :meth:`invalidate_scope_plans` is for a caller that knows
        the shape changed and wants the faster side of the threshold back.

        Args:
            dir_path: The directory whose scope is about to be queried.

        Returns:
            ``"indexed"`` or ``"sequential"``.
        """
        key = self._path_prefix(dir_path)
        cached = self._scope_plans.get(key)
        if cached is not None:
            return cached
        plan = self.scope_plan_kind(dir_path)
        if len(self._scope_plans) >= _SCOPE_PLAN_CACHE_LIMIT:
            # Evict the oldest decision (dicts keep insertion order); a scan
            # touching more directories than this re-decides, which is correct
            # and still cheaper than never caching.
            self._scope_plans.pop(next(iter(self._scope_plans)))
        self._scope_plans[key] = plan
        return plan

    def invalidate_scope_plans(self) -> None:
        """Forget every memoised plan decision.

        Call after a bulk change whose row distribution no longer resembles the
        one the decisions were made on.  Not required for correctness - a stale
        plan still returns the same rows - only to get the faster side of the
        threshold back.
        """
        self._scope_plans.clear()

    def select_scope(self, dir_path: str) -> None:
        """Copy *dir_path*'s rows into ``temp._scope_files`` for the next queries.

        Both plans produce the same table, so they return the same rows and
        differ only in how it is filled.  The copy is rebuilt on every call:
        another connection (or a second process) can change ``files`` between
        two calls, and a cache must never serve a stale scope just to save a
        cheap copy.
        """
        conn = self._connect()
        conn.execute(_CLEAR_SCOPE_SQL)
        if self._plan_for(dir_path) == "indexed":
            prefix = _path_fold(self._path_prefix(dir_path))
            conn.execute(_POPULATE_SCOPE_INDEXED, [prefix, prefix + _SCOPE_RANGE_HIGH])
        else:
            conn.execute(_POPULATE_SCOPE_SEQUENTIAL, [self._path_prefix(dir_path)])

    def file_is_cached(
        self, filepath: str, mtime: float, size: int | None = None
    ) -> bool:
        """Return True if *filepath* is cached and its stamp matches.

        A freshness stamp is ``(mtime, size)``, not the mtime alone: a file
        replaced by a copy that preserves its timestamps keeps its mtime, so an
        mtime-only comparison answers "cached" for a file whose tags were never
        read (R-13).

        Args:
            filepath: The file whose row is being checked.
            mtime: The current ``st_mtime``.
            size: The current ``st_size``.  Pass it - omitting it keeps the
                coarse mtime-only answer, which is only appropriate when the
                size is genuinely unknown.

        Returns:
            True when the stored row matches.  A stored ``size`` of NULL never
            matches a supplied size, so a legacy row is re-read once and heals.
        """
        conn = self._connect()
        if size is None:
            cur = conn.execute(
                "SELECT 1 FROM files WHERE path_hash = ? AND mtime = ?",
                [_path_hash(filepath), mtime],
            )
        else:
            cur = conn.execute(
                "SELECT 1 FROM files WHERE path_hash = ? AND mtime = ? AND size = ?",
                [_path_hash(filepath), mtime, size],
            )
        return cur.fetchone() is not None

    def get_cached_mtimes(self, dir_path: str) -> dict[str, float]:
        """Return ``{filepath: mtime}`` for all cached files under *dir_path*.

        Deliberately a single statement against ``files`` rather than a
        materialised scope: copying the scope costs more than this scan saves
        (70 ms against 17 ms for 20 000 rows), and every cached scan runs it
        once.  Only the multi-statement reports pay for a scope copy.

        The statement follows :meth:`scope_plan_kind`: a narrow scope reads the
        ``path_fold`` index, a wide one keeps the sequential predicate.

        This is the mtime *view*, and that is all it is: a freshness decision
        made from it alone is the R-13 defect.  A scan compares
        :meth:`get_cached_stamps` instead; the two share one plan and one row
        set, so this costs nothing extra where only the mtime is wanted.
        """
        conn = self._connect()
        if self._plan_for(dir_path) == "indexed":
            prefix = _path_fold(self._path_prefix(dir_path))
            cur = conn.execute(
                _SCOPED_MTIMES_INDEXED, [prefix, prefix + _SCOPE_RANGE_HIGH]
            )
        else:
            cur = conn.execute(_SCOPED_MTIMES_SEQUENTIAL, [self._path_prefix(dir_path)])
        return {row[0]: row[1] for row in cur}

    def get_cached_stamps(self, dir_path: str) -> dict[str, tuple[float, int | None]]:
        """Return ``{filepath: (mtime, size)}`` for the files under *dir_path*.

        The shape a cached scan needs: one scoped read of the whole stamp, so a
        file that was replaced with its timestamps preserved is a miss rather
        than a stale hit (R-13).  The stored ``size`` may be NULL on a row
        written before the column was filled, which never equals a real size -
        that file is re-read once and the row heals.

        Plan selection, cost and scope are identical to
        :meth:`get_cached_mtimes`; the only difference is one column.
        """
        conn = self._connect()
        if self._plan_for(dir_path) == "indexed":
            prefix = _path_fold(self._path_prefix(dir_path))
            cur = conn.execute(
                _SCOPED_STAMPS_INDEXED, [prefix, prefix + _SCOPE_RANGE_HIGH]
            )
        else:
            cur = conn.execute(_SCOPED_STAMPS_SEQUENTIAL, [self._path_prefix(dir_path)])
        return {row[0]: (row[1], row[2]) for row in cur}

    def upsert_file(
        self,
        filepath: str,
        mtime: float,
        size: int,
        format_ext: str,
        bpm: int | None = None,
        key: str | None = None,
        genre: str | None = None,
        mood: str | None = None,
        tempo_marking: str | None = None,
        album_artist: str | None = None,
        artist_album: tuple[str, str] | None = None,
        year: int | None = None,
    ) -> None:
        """Insert or replace a single file's cached metadata.

        Args:
            filepath: Absolute path to the audio file.
            mtime: Last modification timestamp (from ``os.path.getmtime``).
            size: File size in bytes.
            format_ext: File extension including dot, e.g. ``.mp3``.
            bpm: Detected BPM, or None.
            key: Musical key, or None.
            genre: Genre tag, or None.
            mood: Mood tag, or None.
            tempo_marking: Tempo marking text, or None.
            album_artist: Album artist, or None.
            artist_album: ``(artist, album)`` tuple, or None.
            year: Release year extracted from tags, or None.
        """
        artist_album_json: str | None = None
        if artist_album is not None:
            artist_album_json = json.dumps(list(artist_album), ensure_ascii=False)

        conn = self._connect()
        norm_path = os.path.normpath(filepath)
        conn.execute(
            """INSERT OR REPLACE INTO files
               (path_hash, path, path_fold, dir_path, mtime, size, format,
                bpm, key, genre, mood, tempo_marking,
                album_artist, artist_album, year)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            [
                _path_hash(filepath),
                norm_path,
                _path_fold(filepath),
                os.path.dirname(norm_path),
                mtime,
                size,
                format_ext,
                bpm,
                key,
                genre,
                mood,
                tempo_marking,
                album_artist,
                artist_album_json,
                year,
            ],
        )
        self._commit()

    def remove_orphans(self, dir_path: str, known_paths: set[str]) -> int:
        """Delete cache rows for files under *dir_path* that no longer exist.

        Returns the number of rows removed.  The candidate scan follows
        :meth:`scope_plan_kind`, like every other scoped statement.
        """
        conn = self._connect()
        if self._plan_for(dir_path) == "indexed":
            prefix = _path_fold(self._path_prefix(dir_path))
            cur = conn.execute(
                _SCOPED_HASHES_INDEXED, [prefix, prefix + _SCOPE_RANGE_HIGH]
            )
        else:
            cur = conn.execute(_SCOPED_HASHES_SEQUENTIAL, [self._path_prefix(dir_path)])
        known_hashes = {_path_hash(p) for p in known_paths}
        orphan_hashes = [row[0] for row in cur if row[0] not in known_hashes]
        if orphan_hashes:
            conn.executemany(
                "DELETE FROM files WHERE path_hash = ?",
                [(h,) for h in orphan_hashes],
            )
            self._commit()
        return len(orphan_hashes)

    # ── Bulk operations ───────────────────────────────────────────────

    def clear_dir(self, dir_path: str) -> None:
        """Delete all cached entries under a specific directory (recursive).

        The scope follows :meth:`scope_plan_kind`, so a narrow directory is
        cleared through the ``path_fold`` index.
        """
        conn = self._connect()
        if self._plan_for(dir_path) == "indexed":
            prefix = _path_fold(self._path_prefix(dir_path))
            conn.execute(_SCOPED_CLEAR_INDEXED, [prefix, prefix + _SCOPE_RANGE_HIGH])
        else:
            conn.execute(_SCOPED_CLEAR_SEQUENTIAL, [self._path_prefix(dir_path)])
        self._commit()

    def clear_all(self) -> None:
        """Delete every row in the cache."""
        conn = self._connect()
        conn.execute("DELETE FROM files")
        self._commit()
        # Every scope is now empty, so every remembered ratio is meaningless.
        self.invalidate_scope_plans()

    def row_count(self, dir_path: str | None = None) -> int:
        """Return the number of cached rows, optionally scoped to *dir_path*."""
        conn = self._connect()
        if dir_path is not None:
            cur = conn.execute(
                "SELECT COUNT(*) FROM files WHERE INSTR(LOWER(path), LOWER(?)) = 1",
                [self._path_prefix(dir_path)],
            )
        else:
            cur = conn.execute("SELECT COUNT(*) FROM files")
        row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0])

    # ── Completeness trend history ────────────────────────────────────

    def record_completeness_snapshot(self, report: Any) -> bool:
        """Store one completeness snapshot for its directory.

        Consecutive duplicates are suppressed: opening the dashboard (or
        re-running ``--completeness``) without touching a file must not pad the
        trend series with identical points.  Only the newest
        ``_HISTORY_SNAPSHOTS`` rows per directory are kept.

        Args:
            report: A ``CompletenessReport`` (anything exposing ``directory``,
                ``total_files``, ``overall_pct`` and ``tag_results``).

        Returns:
            True when a row was written, False when it was a duplicate.
        """
        conn = self._connect()
        scope = _path_fold(self._path_prefix(report.directory))
        tag_pcts = {name: tc.pct_complete for name, tc in report.tag_results.items()}
        payload = json.dumps(tag_pcts, sort_keys=True)

        last = conn.execute(
            "SELECT total_files, tag_pcts FROM completeness_history "
            "WHERE path_fold = ? ORDER BY id DESC LIMIT 1",
            [scope],
        ).fetchone()
        if (
            last is not None
            and int(last[0]) == int(report.total_files)
            and last[1] == payload
        ):
            return False

        conn.execute(
            "INSERT INTO completeness_history "
            "(path_fold, path, total_files, overall_pct, tag_pcts) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                scope,
                os.path.normpath(str(report.directory)),
                int(report.total_files),
                float(report.overall_pct),
                payload,
            ],
        )
        conn.execute(
            "DELETE FROM completeness_history "
            "WHERE path_fold = ? AND id NOT IN ("
            "    SELECT id FROM completeness_history WHERE path_fold = ? "
            "    ORDER BY id DESC LIMIT ?"
            ")",
            [scope, scope, _HISTORY_SNAPSHOTS],
        )
        self._commit()
        return True

    def completeness_history(
        self, dir_path: str, limit: int = 12
    ) -> list[dict[str, Any]]:
        """Return up to *limit* snapshots for *dir_path*, oldest first.

        Oldest-first is the order a time-series chart needs; the newest
        *limit* rows are selected, then reversed so a chart's x-axis runs
        left to right in time.
        """
        conn = self._connect()
        scope = _path_fold(self._path_prefix(dir_path))
        rows = conn.execute(
            "SELECT recorded_at, total_files, overall_pct, tag_pcts "
            "FROM completeness_history WHERE path_fold = ? "
            "ORDER BY id DESC LIMIT ?",
            [scope, max(1, int(limit))],
        ).fetchall()
        history: list[dict[str, Any]] = []
        for recorded_at, total_files, overall_pct, tag_pcts in reversed(rows):
            try:
                parsed = json.loads(tag_pcts)
            except (TypeError, ValueError):
                parsed = {}
            history.append(
                {
                    "recorded_at": recorded_at,
                    "total_files": int(total_files),
                    "overall_pct": float(overall_pct),
                    "tag_pcts": parsed if isinstance(parsed, dict) else {},
                }
            )
        return history

    def clear_completeness_history(self, dir_path: str | None = None) -> int:
        """Delete stored snapshots (all of them, or one directory's)."""
        conn = self._connect()
        if dir_path is None:
            cur = conn.execute("DELETE FROM completeness_history")
        else:
            scope = _path_fold(self._path_prefix(dir_path))
            cur = conn.execute(
                "DELETE FROM completeness_history WHERE path_fold = ?", [scope]
            )
        self._commit()
        return int(cur.rowcount or 0)

    # ── Aggregate queries ─────────────────────────────────────────────

    def query_aggregate(self, dir_path: str) -> dict[str, Any] | None:
        """Return aggregated statistics from the cache as a flat dict.

        This avoids loading all rows into Python memory.  Returns None
        when no cached data exists for *dir_path*.

        The returned dict is compatible with ``StatsReport(**d)`` and
        includes::

            scan_path, total_files, total_albums, total_artists,
            format_breakdown, genre_distribution, key_distribution,
            key_mode_distribution, mood_distribution,
            tempo_marking_distribution, year_distribution,
            top_artists, top_genres, missing_data

        Note it does **not** populate ``bpm_distribution`` (the cached-scan
        report path builds that separately in
        ``library_stats.core.file_processor``); ``StatsReport`` defaults it
        to an empty dict, so ``StatsReport(**d)`` still succeeds.
        """
        conn = self._connect()
        self.select_scope(dir_path)

        result: dict[str, Any] = {}
        result["scan_path"] = dir_path

        total_files = conn.execute(_SCOPE_COUNT_SQL).fetchone()[0]
        if total_files == 0:
            return None

        # ── Counts ────────────────────────────────────────────────────
        result["total_files"] = total_files

        cur = conn.execute(
            "SELECT COUNT(DISTINCT artist_album) FROM temp._scope_files "
            "WHERE artist_album IS NOT NULL"
        )
        result["total_albums"] = cur.fetchone()[0] or 0

        cur = conn.execute(
            "SELECT COUNT(DISTINCT album_artist) FROM temp._scope_files "
            "WHERE album_artist IS NOT NULL"
        )
        result["total_artists"] = cur.fetchone()[0] or 0

        # ── Format breakdown ──────────────────────────────────────────
        cur = conn.execute(
            "SELECT format, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE format IS NOT NULL "
            "GROUP BY format ORDER BY cnt DESC"
        )
        result["format_breakdown"] = dict(cur)

        # ── Genre distribution ────────────────────────────────────────
        cur = conn.execute(
            "SELECT genre, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE genre IS NOT NULL "
            "GROUP BY genre ORDER BY cnt DESC"
        )
        result["genre_distribution"] = dict(cur)

        # ── Key distribution ──────────────────────────────────────────
        cur = conn.execute(
            "SELECT key, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE key IS NOT NULL "
            "GROUP BY key ORDER BY cnt DESC"
        )
        result["key_distribution"] = dict(cur)

        # ── Key mode distribution (loaded into Python for classification) ─
        cur = conn.execute("SELECT key FROM temp._scope_files WHERE key IS NOT NULL")
        result["key_mode_distribution"] = dict(_classify_keys([r[0] for r in cur]))

        # ── Mood distribution ─────────────────────────────────────────
        cur = conn.execute(
            "SELECT mood, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE mood IS NOT NULL "
            "GROUP BY mood ORDER BY cnt DESC"
        )
        result["mood_distribution"] = dict(cur)

        # ── Tempo marking distribution ────────────────────────────────
        cur = conn.execute(
            "SELECT tempo_marking, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE tempo_marking IS NOT NULL "
            "GROUP BY tempo_marking ORDER BY cnt DESC"
        )
        result["tempo_marking_distribution"] = dict(cur)

        # ── Year distribution (binned via Python helper) ──────────────
        cur = conn.execute("SELECT year FROM temp._scope_files")
        result["year_distribution"] = dict(_decade_bins([r[0] for r in cur]))

        # ── Top artists ───────────────────────────────────────────────
        cur = conn.execute(
            "SELECT album_artist, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE album_artist IS NOT NULL "
            "GROUP BY album_artist ORDER BY cnt DESC LIMIT 50"
        )
        result["top_artists"] = list(cur)

        # ── Top genres ────────────────────────────────────────────────
        cur = conn.execute(
            "SELECT genre, COUNT(*) AS cnt FROM temp._scope_files "
            "WHERE genre IS NOT NULL "
            "GROUP BY genre ORDER BY cnt DESC LIMIT 50"
        )
        result["top_genres"] = list(cur)

        # ── Missing data counts ──────────────────────────────────────
        missing: dict[str, int] = {}
        missing["no_bpm"] = conn.execute(
            "SELECT COUNT(*) FROM temp._scope_files WHERE bpm IS NULL"
        ).fetchone()[0]
        missing["no_key"] = conn.execute(
            "SELECT COUNT(*) FROM temp._scope_files WHERE key IS NULL"
        ).fetchone()[0]
        missing["no_genre"] = conn.execute(
            "SELECT COUNT(*) FROM temp._scope_files WHERE genre IS NULL"
        ).fetchone()[0]
        missing["no_mood"] = conn.execute(
            "SELECT COUNT(*) FROM temp._scope_files WHERE mood IS NULL"
        ).fetchone()[0]
        missing["no_tempo_marking"] = conn.execute(
            "SELECT COUNT(*) FROM temp._scope_files WHERE tempo_marking IS NULL"
        ).fetchone()[0]
        result["missing_data"] = missing

        return result


# ── Module-level helpers (not exported from the class) ────────────────────

_MAJOR_KEYS = {
    "C",
    "C#",
    "Db",
    "D",
    "D#",
    "Eb",
    "E",
    "F",
    "F#",
    "Gb",
    "G",
    "G#",
    "Ab",
    "A",
    "A#",
    "Bb",
    "B",
    "Cb",
}
_MINOR_KEYS = {
    "Cm",
    "C#m",
    "Dbm",
    "Dm",
    "D#m",
    "Ebm",
    "Em",
    "Fm",
    "F#m",
    "Gbm",
    "Gm",
    "G#m",
    "Abm",
    "Am",
    "A#m",
    "Bbm",
    "Bm",
}


def _classify_key_mode(key: str) -> tuple[str, str] | None:
    """Return (root, mode) e.g. ('C', 'major') or None."""
    k = key.strip()
    if k in _MAJOR_KEYS:
        return (k, "major")
    if k in _MINOR_KEYS:
        return (k, "minor")
    lower = k.lower().replace("\u266d", "b").replace("\u266f", "#")
    for suffix in (" major", " minor"):
        if lower.endswith(suffix):
            root = k[: -len(suffix)]
            mode = suffix.strip()
            return (root, mode)
    return None


def _classify_keys(keys: list[str]) -> dict[str, int]:
    result: dict[str, int] = {}
    for k in keys:
        c = _classify_key_mode(k)
        if c:
            result[c[1]] = result.get(c[1], 0) + 1
    return result


def _bpm_bin(bpm: int | None) -> str:
    if bpm is None:
        return "Unknown"
    if bpm < 60:
        return "<60"
    if bpm < 80:
        return "60\u201379"
    if bpm < 100:
        return "80\u201399"
    if bpm < 120:
        return "100\u2013119"
    if bpm < 140:
        return "120\u2013139"
    if bpm < 160:
        return "140\u2013159"
    if bpm < 180:
        return "160\u2013179"
    return "180+"


def _decade_bin(year: int | None) -> str:
    if year is None:
        return "Unknown"
    decade = (year // 10) * 10
    return f"{decade}s"


def _decade_bins(years: list[int | None]) -> dict[str, int]:
    result: dict[str, int] = {}
    for y in years:
        b = _decade_bin(y)
        result[b] = result.get(b, 0) + 1
    return result
