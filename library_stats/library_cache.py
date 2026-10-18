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

Concurrency:
    Connection creation is serialised by a module-level lock shared by every
    instance (per-instance locks cannot serialise separate connections to the
    same DB file), and each connection waits up to 30 s (``timeout=30`` +
    ``PRAGMA busy_timeout``) for a competing writer rather than raising
    ``OperationalError: database is locked`` — the pattern documented in
    AGENTS.md and used by ``audio_suite_shared.batch_undo``.

Changed in 1.3.0: scoped queries choose between an indexed range scan on
``path_fold`` and the original sequential ``INSTR(LOWER(path), …)`` predicate
based on measured selectivity (``scoped * 2 < total``).  A sequential scan
beats an index at ~90 % selectivity — a whole-library scope was measured at
9.9 ms sequential against 13.5 ms indexed — so the index is only used when the
scope is genuinely narrow (one album inside a large cache: 7.0 ms → 0.13 ms).
``upsert_file`` writes ``path_fold``; legacy databases are migrated on connect
(``PRAGMA user_version`` 0 → 1).  Writes can be grouped with ``batch()``:
commit-per-row cost 37.3 s on 20 000 rows against 0.18 s for one transaction.

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
_SCHEMA_VERSION = 2

# Upper bound for a prefix range scan on ``path_fold``.  SQLite compares TEXT
# with BINARY collation, so every string that starts with the prefix sorts
# below ``prefix + U+10FFFF``.
_SCOPE_RANGE_HIGH = "\U0010ffff"

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
                    self._conn.executescript(_SCHEMA_SQL)
                    self._migrate(self._conn)
                    self._enable_auto_vacuum(self._conn)
        return self._conn

    def _migrate(self, conn: sqlite3.Connection) -> None:
        """Bring an existing cache file up to ``_SCHEMA_VERSION`` in place.

        Version 2 adds ``path_fold`` plus its index and backfills existing
        rows.  The column is added with ``ALTER TABLE`` so no user data is
        rewritten, and the backfill runs through ``_path_fold`` (Python) rather
        than SQL ``LOWER`` so it agrees byte-for-byte with ``upsert_file``.
        Must be called under ``_DB_LOCK`` with no open transaction.
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

    def scope_predicate(self, dir_path: str) -> tuple[str, list[Any]]:
        """Return the cheapest SQL predicate selecting rows under *dir_path*.

        Two predicates are equivalent here: the indexed range scan on
        ``path_fold`` and the sequential ``INSTR(LOWER(path), …)`` scan.  An
        index only pays off when the scope is a small slice of the cache; at
        whole-library selectivity a sequential scan is faster, so the choice is
        made from the actual row counts (``scoped * 2 < total``).  Callers
        reuse the returned fragment across the several statements of one
        report rather than re-deciding per statement.
        """
        conn = self._connect()
        prefix = _path_fold(self._path_prefix(dir_path))
        total = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        if total:
            low = prefix
            high = prefix + _SCOPE_RANGE_HIGH
            scoped = conn.execute(
                "SELECT COUNT(*) FROM files WHERE path_fold >= ? AND path_fold < ?",
                [low, high],
            ).fetchone()[0]
            if scoped * 2 < total:
                return ("path_fold >= ? AND path_fold < ?", [low, high])
        return ("INSTR(LOWER(path), LOWER(?)) = 1", [self._path_prefix(dir_path)])

    def file_is_cached(self, filepath: str, mtime: float) -> bool:
        """Return True if *filepath* is cached and its mtime matches."""
        conn = self._connect()
        cur = conn.execute(
            "SELECT 1 FROM files WHERE path_hash = ? AND mtime = ?",
            [_path_hash(filepath), mtime],
        )
        return cur.fetchone() is not None

    def get_cached_mtimes(self, dir_path: str) -> dict[str, float]:
        """Return ``{filepath: mtime}`` for all cached files under *dir_path*."""
        conn = self._connect()
        scope_sql, scope_params = self.scope_predicate(dir_path)
        cur = conn.execute(
            f"SELECT path, mtime FROM files WHERE {scope_sql}", scope_params
        )
        return {row[0]: row[1] for row in cur}

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

        Returns the number of rows removed.
        """
        conn = self._connect()
        scope_sql, scope_params = self.scope_predicate(dir_path)
        cur = conn.execute(
            f"SELECT path_hash FROM files WHERE {scope_sql}", scope_params
        )
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
        """Delete all cached entries under a specific directory (recursive)."""
        conn = self._connect()
        scope_sql, scope_params = self.scope_predicate(dir_path)
        conn.execute(f"DELETE FROM files WHERE {scope_sql}", scope_params)
        self._commit()

    def clear_all(self) -> None:
        """Delete every row in the cache."""
        conn = self._connect()
        conn.execute("DELETE FROM files")
        self._commit()

    def row_count(self, dir_path: str | None = None) -> int:
        """Return the number of cached rows, optionally scoped to *dir_path*."""
        conn = self._connect()
        if dir_path is not None:
            scope_sql, scope_params = self.scope_predicate(dir_path)
            cur = conn.execute(
                f"SELECT COUNT(*) FROM files WHERE {scope_sql}", scope_params
            )
        else:
            cur = conn.execute("SELECT COUNT(*) FROM files")
        row = cur.fetchone()
        if row is None:
            return 0
        return int(row[0])

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
        where, params = self.scope_predicate(dir_path)

        result: dict[str, Any] = {}
        result["scan_path"] = dir_path

        total_files = conn.execute(
            f"SELECT COUNT(*) FROM files WHERE {where}", params
        ).fetchone()[0]
        if total_files == 0:
            return None

        # ── Counts ────────────────────────────────────────────────────
        result["total_files"] = total_files

        cur = conn.execute(
            f"SELECT COUNT(DISTINCT artist_album) FROM files "
            f"WHERE {where} AND artist_album IS NOT NULL",
            params,
        )
        result["total_albums"] = cur.fetchone()[0] or 0

        cur = conn.execute(
            f"SELECT COUNT(DISTINCT album_artist) FROM files "
            f"WHERE {where} AND album_artist IS NOT NULL",
            params,
        )
        result["total_artists"] = cur.fetchone()[0] or 0

        # ── Format breakdown ──────────────────────────────────────────
        cur = conn.execute(
            f"SELECT format, COUNT(*) AS cnt FROM files "
            f"WHERE {where} AND format IS NOT NULL "
            f"GROUP BY format ORDER BY cnt DESC",
            params,
        )
        result["format_breakdown"] = dict(cur)

        # ── Genre distribution ────────────────────────────────────────
        cur = conn.execute(
            f"SELECT genre, COUNT(*) AS cnt FROM files "
            f"WHERE {where} AND genre IS NOT NULL "
            f"GROUP BY genre ORDER BY cnt DESC",
            params,
        )
        result["genre_distribution"] = dict(cur)

        # ── Key distribution ──────────────────────────────────────────
        cur = conn.execute(
            f"SELECT key, COUNT(*) AS cnt FROM files "
            f"WHERE {where} AND key IS NOT NULL "
            f"GROUP BY key ORDER BY cnt DESC",
            params,
        )
        result["key_distribution"] = dict(cur)

        # ── Key mode distribution (loaded into Python for classification) ─
        cur = conn.execute(
            f"SELECT key FROM files WHERE {where} AND key IS NOT NULL", params
        )
        result["key_mode_distribution"] = dict(_classify_keys([r[0] for r in cur]))

        # ── Mood distribution ─────────────────────────────────────────
        cur = conn.execute(
            f"SELECT mood, COUNT(*) AS cnt FROM files "
            f"WHERE {where} AND mood IS NOT NULL "
            f"GROUP BY mood ORDER BY cnt DESC",
            params,
        )
        result["mood_distribution"] = dict(cur)

        # ── Tempo marking distribution ────────────────────────────────
        cur = conn.execute(
            f"SELECT tempo_marking, COUNT(*) AS cnt FROM files "
            f"WHERE {where} AND tempo_marking IS NOT NULL "
            f"GROUP BY tempo_marking ORDER BY cnt DESC",
            params,
        )
        result["tempo_marking_distribution"] = dict(cur)

        # ── Year distribution (binned via Python helper) ──────────────
        cur = conn.execute(f"SELECT year FROM files WHERE {where}", params)
        result["year_distribution"] = dict(_decade_bins([r[0] for r in cur]))

        # ── Top artists ───────────────────────────────────────────────
        cur = conn.execute(
            f"SELECT album_artist, COUNT(*) AS cnt FROM files "
            f"WHERE {where} AND album_artist IS NOT NULL "
            f"GROUP BY album_artist ORDER BY cnt DESC LIMIT 50",
            params,
        )
        result["top_artists"] = list(cur)

        # ── Top genres ────────────────────────────────────────────────
        cur = conn.execute(
            f"SELECT genre, COUNT(*) AS cnt FROM files "
            f"WHERE {where} AND genre IS NOT NULL "
            f"GROUP BY genre ORDER BY cnt DESC LIMIT 50",
            params,
        )
        result["top_genres"] = list(cur)

        # ── Missing data counts ──────────────────────────────────────
        missing: dict[str, int] = {}
        missing["no_bpm"] = conn.execute(
            f"SELECT COUNT(*) FROM files WHERE {where} AND bpm IS NULL", params
        ).fetchone()[0]
        missing["no_key"] = conn.execute(
            f"SELECT COUNT(*) FROM files WHERE {where} AND key IS NULL", params
        ).fetchone()[0]
        missing["no_genre"] = conn.execute(
            f"SELECT COUNT(*) FROM files WHERE {where} AND genre IS NULL", params
        ).fetchone()[0]
        missing["no_mood"] = conn.execute(
            f"SELECT COUNT(*) FROM files WHERE {where} AND mood IS NULL", params
        ).fetchone()[0]
        missing["no_tempo_marking"] = conn.execute(
            f"SELECT COUNT(*) FROM files WHERE {where} AND tempo_marking IS NULL",
            params,
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
