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

Changed in 2.4.3: split into ``cache_schema`` (DDL, version, path
normalisers and the scope SQL), ``cache_store`` (file rows, scope
selection, aggregate queries) and ``cache_prune`` (whole-cache clearing and
the completeness trend). ``LibraryCache`` composes the two mixins and keeps
connection management; every moved name is re-exported here
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .cache_prune import _HISTORY_SNAPSHOTS as _HISTORY_SNAPSHOTS
from .cache_prune import CachePruneMixin as CachePruneMixin
from .cache_schema import _AUTO_VACUUM_FULL as _AUTO_VACUUM_FULL
from .cache_schema import _CLEAR_SCOPE_SQL as _CLEAR_SCOPE_SQL
from .cache_schema import _POPULATE_SCOPE_INDEXED as _POPULATE_SCOPE_INDEXED
from .cache_schema import _POPULATE_SCOPE_SEQUENTIAL as _POPULATE_SCOPE_SEQUENTIAL
from .cache_schema import _SCHEMA_SQL as _SCHEMA_SQL
from .cache_schema import _SCHEMA_VERSION as _SCHEMA_VERSION
from .cache_schema import _SCOPE_COUNT_SQL as _SCOPE_COUNT_SQL
from .cache_schema import _SCOPE_PLAN_CACHE_LIMIT as _SCOPE_PLAN_CACHE_LIMIT
from .cache_schema import _SCOPE_RANGE_HIGH as _SCOPE_RANGE_HIGH
from .cache_schema import _SCOPE_TABLE_SQL as _SCOPE_TABLE_SQL
from .cache_schema import _SCOPED_CLEAR_INDEXED as _SCOPED_CLEAR_INDEXED
from .cache_schema import _SCOPED_CLEAR_SEQUENTIAL as _SCOPED_CLEAR_SEQUENTIAL
from .cache_schema import _SCOPED_HASHES_INDEXED as _SCOPED_HASHES_INDEXED
from .cache_schema import _SCOPED_HASHES_SEQUENTIAL as _SCOPED_HASHES_SEQUENTIAL
from .cache_schema import _SCOPED_MTIMES_INDEXED as _SCOPED_MTIMES_INDEXED
from .cache_schema import _SCOPED_MTIMES_SEQUENTIAL as _SCOPED_MTIMES_SEQUENTIAL
from .cache_schema import _SCOPED_STAMPS_INDEXED as _SCOPED_STAMPS_INDEXED
from .cache_schema import _SCOPED_STAMPS_SEQUENTIAL as _SCOPED_STAMPS_SEQUENTIAL
from .cache_schema import _path_fold as _path_fold
from .cache_schema import _path_hash as _path_hash
from .cache_schema import enable_auto_vacuum, migrate
from .cache_store import _MAJOR_KEYS as _MAJOR_KEYS
from .cache_store import _MINOR_KEYS as _MINOR_KEYS
from .cache_store import CacheStoreMixin as CacheStoreMixin
from .cache_store import _bpm_bin as _bpm_bin
from .cache_store import _classify_key_mode as _classify_key_mode
from .cache_store import _classify_keys as _classify_keys
from .cache_store import _decade_bin as _decade_bin
from .cache_store import _decade_bins as _decade_bins

logger = logging.getLogger(__name__)
_DB_LOCK = threading.Lock()


class LibraryCache(CacheStoreMixin, CachePruneMixin):
    """SQLite-backed persistent cache for audio file tag metadata.

    Designed for incremental scanning: compare current file mtimes against
    cached values and only re-read tags for files that changed.  The two
    mixins supply row/scope queries (``cache_store``) and cache clearing plus
    the completeness trend (``cache_prune``).

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
                    migrate(self._conn)
                    enable_auto_vacuum(self._conn)
                    self._conn.execute(_SCOPE_TABLE_SQL)
        return self._conn

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
