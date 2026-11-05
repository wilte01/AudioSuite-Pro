"""
cache_schema.py - the library cache's SQLite schema and scope SQL.

Split out of ``library_stats.library_cache`` (WP-9 #5): the DDL, the
version, the path normalisers and the temp-table scope queries, plus the
two connection hooks. Bodies are unchanged; ``LibraryCache._connect`` and
the store mixin import them.

Changed in 2.4.3: split out of ``library_stats.library_cache``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3

logger = logging.getLogger(f"audio_suite.{__name__}")

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

_SCHEMA_VERSION = 3

_SCOPE_RANGE_HIGH = "\U0010ffff"

_SCOPE_PLAN_CACHE_LIMIT = 128

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

_SCOPED_MTIMES_INDEXED = (
    "SELECT path, mtime FROM files WHERE path_fold >= ? AND path_fold < ?"
)

_SCOPED_MTIMES_SEQUENTIAL = (
    "SELECT path, mtime FROM files WHERE INSTR(LOWER(path), LOWER(?)) = 1"
)

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


def enable_auto_vacuum(conn: sqlite3.Connection) -> None:
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


def migrate(conn: sqlite3.Connection) -> None:
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_files_path_fold ON files(path_fold)")
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
