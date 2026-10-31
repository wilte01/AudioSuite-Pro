"""SQLite cache of per-file fingerprints.

Fingerprinting a library with ``fpcalc`` costs about half a second per file, so
a tool that re-fingerprinted on every run would be unusable on the library it
exists for.  The cache stores one row per file and the scan trusts it only when
the file's **freshness stamp** still matches.

Freshness is ``(mtime, size)``, not the mtime alone
---------------------------------------------------
A file replaced by a copy that preserves its timestamps keeps its mtime, so an
mtime-only comparison answers "cached" for a file whose fingerprint was taken
from different audio.  That is the R-13 defect `library_stats` fixed, and the
rule is reused here rather than a second one invented
(``PLAN_functional_backlog.md`` §7: "decide at the start of that item, with the
R-13 stamp as the default").

Why its own database file
-------------------------
This is decision D39 in the governing plan.  The fingerprint payload is ~700
bytes per file and grows with the library, while `library_stats`' cache is a
tag-metadata store with its own schema and its own migration history; merging
them would make one tool's migration edit the other's table.  The stamp rule is
shared, the file is not.

Concurrency
-----------
Connection creation is serialised by a module-level lock shared by every
instance (per-instance locks cannot serialise separate connections to the same
file), and each connection waits for a competing writer instead of raising
``database is locked``: the pattern ``audio_suite_shared.batch_undo`` and
``library_stats.library_cache`` already use.  ``auto_vacuum=FULL`` keeps a
delete-heavy cache from growing permanently.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from .models import FingerprintRecord

logger = logging.getLogger(__name__)

_DB_LOCK = threading.Lock()

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fingerprints (
    path_hash TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    mtime REAL NOT NULL,
    size INTEGER NOT NULL,
    duration REAL NOT NULL,
    words TEXT NOT NULL,
    sample_rate INTEGER NOT NULL DEFAULT 0,
    channels INTEGER NOT NULL DEFAULT 0,
    bitrate_kbps REAL NOT NULL DEFAULT 0,
    lossless INTEGER NOT NULL DEFAULT 0,
    artist TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    scanned_at TEXT DEFAULT (datetime('now'))
);
"""

#: Bumped when the on-disk shape changes; ``PRAGMA user_version`` carries it, so
#: a migration runs exactly once instead of on every connect.
_SCHEMA_VERSION = 1

_AUTO_VACUUM_FULL = 1


#: Environment override for the cache location.  The same escape hatch
#: ``AUDIOSUITE_LOG_DIR`` and ``AUDIOSUITE_UNDO_DB`` give: the suite's own tests
#: redirect it, so no test writes into the developer's home directory, and a
#: user with a cache on another volume can point at it.
CACHE_PATH_ENV = "AUDIOSUITE_DUPLICATE_CACHE"


def default_cache_path() -> Path:
    """Return the cache file's canonical location.

    One canonical directory for the tool, whatever the calling module's
    location (AGENTS.md, *Shared Config Pattern*): a cache resolved relative to
    ``__file__`` would be written beside the package by one caller and in the
    user's home by another.

    Returns:
        ``~/.audiosuite/duplicate_cache.db``, or the path named by
        :data:`CACHE_PATH_ENV` when it is set.
    """
    override = os.environ.get(CACHE_PATH_ENV, "").strip()
    if override:
        return Path(override)
    return Path.home() / ".audiosuite" / "duplicate_cache.db"


def _path_hash(filepath: str) -> str:
    """Return the SHA-256 of *filepath*'s normalised form.

    Args:
        filepath: Absolute or relative path.

    Returns:
        Hex digest, used as the primary key.
    """
    return hashlib.sha256(os.path.normpath(filepath).encode("utf-8")).hexdigest()


class FingerprintCache:
    """Persistent ``path -> FingerprintRecord`` store with stamp freshness."""

    def __init__(self, cache_path: str | Path | None = None) -> None:
        """Open (or create) the cache at *cache_path*.

        Args:
            cache_path: Where the SQLite file lives.  Defaults to
                :func:`default_cache_path`; tests pass a temporary path so they
                never touch the user's real cache.
        """
        self._path = Path(cache_path) if cache_path else default_cache_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        #: Nesting depth of :meth:`batch`; commits are deferred while it is > 0.
        self._batch_depth = 0

    # ── Connection management ─────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        """Return the open connection, creating the schema on first use."""
        if self._conn is None:
            with _DB_LOCK:
                if self._conn is None:
                    self._conn = sqlite3.connect(
                        str(self._path), check_same_thread=False, timeout=30
                    )
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    self._conn.execute("PRAGMA busy_timeout=30000")
                    self._conn.executescript(_SCHEMA_SQL)
                    self._conn.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
                    self._enable_auto_vacuum(self._conn)
                    self._conn.commit()
        return self._conn

    @staticmethod
    def _enable_auto_vacuum(conn: sqlite3.Connection) -> None:
        """Set the persistent ``auto_vacuum=FULL`` flag, converting once.

        A file created before the flag was set is converted in place with a
        one-time ``VACUUM``; afterwards the flag is only read.

        Args:
            conn: An open connection with no transaction in flight.
        """
        row = conn.execute("PRAGMA auto_vacuum").fetchone()
        if row is not None and int(row[0]) == _AUTO_VACUUM_FULL:
            return
        conn.execute("PRAGMA auto_vacuum = FULL")
        conn.commit()
        conn.execute("VACUUM")

    def close(self) -> None:
        """Close the connection, if one is open."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> FingerprintCache:
        """Open the cache for use as a context manager."""
        self._connect()
        return self

    def __exit__(self, *args: Any) -> None:
        """Close the cache when the context ends."""
        self.close()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Group every write inside the block into one transaction.

        Commit-per-row dominates a scan's write cost, so a fingerprinted library
        is written in one transaction.  Nested blocks are reference-counted;
        any exception rolls the whole group back.
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

    def _commit(self) -> None:
        """Commit now, unless a :meth:`batch` block owns the transaction."""
        if self._batch_depth == 0 and self._conn is not None:
            self._conn.commit()

    @property
    def db_path(self) -> Path:
        """Return the cache file's path."""
        return self._path

    # ── Reads ─────────────────────────────────────────────────────────────

    @staticmethod
    def _scope_prefix(dir_path: str) -> str:
        """Return *dir_path* normalised with a trailing separator.

        The trailing separator is what keeps ``D:\\\\Music`` from also matching
        ``D:\\\\Musicology``.

        Args:
            dir_path: The directory a scan is rooted at.

        Returns:
            The normalised scope prefix.
        """
        normalised = os.path.normpath(dir_path)
        if not normalised.endswith(os.sep):
            normalised += os.sep
        return normalised

    def load_under(self, dir_path: str) -> dict[str, FingerprintRecord]:
        """Return every cached record under *dir_path*, keyed by path.

        Args:
            dir_path: The scan root.

        Returns:
            ``{path: record}``.  Each record carries the stamp it was stored
            with, so a caller can compare it with the file on disk.
        """
        conn = self._connect()
        cursor = conn.execute(
            "SELECT path, mtime, size, duration, words, sample_rate, channels, "
            "bitrate_kbps, lossless, artist, title FROM fingerprints "
            "WHERE INSTR(LOWER(path), LOWER(?)) = 1",
            [self._scope_prefix(dir_path)],
        )
        records: dict[str, FingerprintRecord] = {}
        for row in cursor:
            path, mtime, size, duration, words, sample_rate, channels = row[:7]
            bitrate_kbps, lossless, artist, title = row[7:]
            try:
                parsed = tuple(int(part) for part in str(words).split(",") if part)
            except ValueError:
                # A corrupt row is a cache miss, never a crash: the file is
                # simply fingerprinted again and the row is rewritten.
                logger.warning("Discarding unparseable cached fingerprint for %s", path)
                continue
            records[path] = FingerprintRecord(
                path=path,
                duration=float(duration),
                words=parsed,
                size=int(size),
                mtime=float(mtime),
                sample_rate=int(sample_rate),
                channels=int(channels),
                bitrate_kbps=float(bitrate_kbps),
                lossless=bool(lossless),
                artist=str(artist),
                title=str(title),
            )
        return records

    def is_fresh(self, record: FingerprintRecord, mtime: float, size: int) -> bool:
        """Return whether *record* still describes the file on disk.

        Args:
            record: The cached record.
            mtime: The file's current ``st_mtime``.
            size: The file's current ``st_size``.

        Returns:
            True when both halves of the stamp match.  A record whose size was
            never stored cannot match, so it is re-read once and heals.
        """
        return record.mtime == mtime and record.size == size

    def count(self) -> int:
        """Return the number of cached rows."""
        conn = self._connect()
        row = conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()
        return int(row[0]) if row is not None else 0

    # ── Writes ────────────────────────────────────────────────────────────

    def upsert(self, record: FingerprintRecord) -> None:
        """Insert or replace one file's cached fingerprint.

        Args:
            record: The record to store.
        """
        conn = self._connect()
        conn.execute(
            "INSERT OR REPLACE INTO fingerprints "
            "(path_hash, path, mtime, size, duration, words, sample_rate, "
            " channels, bitrate_kbps, lossless, artist, title) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                _path_hash(record.path),
                os.path.normpath(record.path),
                record.mtime,
                record.size,
                record.duration,
                ",".join(str(word) for word in record.words),
                record.sample_rate,
                record.channels,
                record.bitrate_kbps,
                1 if record.lossless else 0,
                record.artist,
                record.title,
            ],
        )
        self._commit()

    def remove_orphans(self, dir_path: str, known_paths: set[str]) -> int:
        """Delete rows under *dir_path* whose file no longer exists.

        Args:
            dir_path: The scan root.
            known_paths: Every path the scan actually visited.

        Returns:
            The number of rows removed.
        """
        conn = self._connect()
        cursor = conn.execute(
            "SELECT path_hash, path FROM fingerprints "
            "WHERE INSTR(LOWER(path), LOWER(?)) = 1",
            [self._scope_prefix(dir_path)],
        )
        orphans = [
            (row[0],) for row in cursor if os.path.normpath(row[1]) not in known_paths
        ]
        if orphans:
            conn.executemany("DELETE FROM fingerprints WHERE path_hash = ?", orphans)
            conn.commit()
        return len(orphans)

    def clear(self) -> None:
        """Delete every cached row."""
        conn = self._connect()
        conn.execute("DELETE FROM fingerprints")
        conn.commit()
