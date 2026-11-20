"""sqlite_helpers.py — the SQLite setup the suite's caches share.

Three modules keep a SQLite cache: the tag undo log (``batch_undo``), Library
Statistics' tag cache (``library_stats.cache_schema``) and Duplicate Finder's
fingerprint cache.  Each asked the same two questions, and each answered them
with its own copy of the same code:

* *How does a delete-heavy file stop growing forever?* — set the persistent
  ``auto_vacuum=FULL`` file flag, converting a file that predates it with a
  one-time ``VACUUM``.  The order matters (read the flag, set it, commit, then
  vacuum, with no transaction open) and a copy that gets it wrong corrupts
  nothing but silently never reclaims a page.
* *How does a scan write thousands of rows without committing each one?* —
  wrap the block in one reference-counted transaction, so only the outermost
  ``batch()`` commits and any exception rolls the whole group back.

Both are now one implementation.  The DDL, the migrations and the queries stay
where they are: those are each cache's own schema, not a shared capability.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager

__all__ = [
    "AUTO_VACUUM_FULL",
    "BatchTransactionMixin",
    "enable_auto_vacuum",
    "scope_prefix",
]

#: ``PRAGMA auto_vacuum``'s FULL mode.
AUTO_VACUUM_FULL = 1


def enable_auto_vacuum(conn: sqlite3.Connection) -> None:
    """Ensure *conn*'s database reclaims freed pages automatically.

    Sets the persistent ``auto_vacuum=FULL`` file flag so every prune (a batch
    cleanup, an orphan sweep, an ``INSERT OR REPLACE``) returns freed pages to
    the operating system at commit instead of leaving them inside a
    permanently growing database file.  A file that predates the flag is
    converted in place with a one-time ``VACUUM``; once the flag is set, later
    connects only read it and skip, so the check costs one pragma read.

    Must be called with no transaction open — ``VACUUM`` cannot run inside one.

    Args:
        conn: An open connection to the cache database.
    """
    row = conn.execute("PRAGMA auto_vacuum").fetchone()
    if row is not None and int(row[0]) == AUTO_VACUUM_FULL:
        return
    conn.execute("PRAGMA auto_vacuum = FULL")
    conn.commit()
    conn.execute("VACUUM")


def scope_prefix(dir_path: str) -> str:
    """Return *dir_path* normalised with a trailing separator.

    The trailing separator is what keeps ``D:\\Music`` from also matching
    ``D:\\Musicology`` when the path is used as an ``INSTR`` prefix, so every
    scoped query needs exactly this shape.

    Args:
        dir_path: The directory a scan is rooted at.

    Returns:
        The normalised scope prefix.
    """
    normalised = os.path.normpath(dir_path)
    if not normalised.endswith(os.sep):
        normalised += os.sep
    return normalised


class BatchTransactionMixin:
    """Reference-counted ``batch()`` transaction for a SQLite-backed cache.

    Commit-per-row dominates a scan's write cost — 37.3 s for 20 000 rows
    against 0.18 s batched — so a scan wraps its writes in one transaction.
    Nested blocks are reference-counted: only the outermost commits, and any
    exception rolls the whole group back.

    The host class supplies ``_conn`` (``None`` while closed), ``_batch_depth``
    (0 at construction) and :meth:`_connect`.
    """

    _conn: sqlite3.Connection | None
    _batch_depth: int

    def _connect(self) -> sqlite3.Connection:
        """Return the open connection; provided by the host class."""
        raise NotImplementedError

    def _commit(self) -> None:
        """Commit now, unless a :meth:`batch` block owns the transaction."""
        if self._batch_depth == 0 and self._conn is not None:
            self._conn.commit()

    @contextmanager
    def batch(self) -> Iterator[None]:
        """Group every write inside the block into one transaction."""
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
