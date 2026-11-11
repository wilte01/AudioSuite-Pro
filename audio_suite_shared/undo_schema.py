"""
undo_schema.py - the undo log's SQLite schema, in one place.

Split out of ``audio_suite_shared.batch_undo`` (WP-9 #3): the DDL string,
the ``auto_vacuum`` flag and the one delete-payload migration. Function
bodies are unchanged; ``BatchUndoLog._connect`` calls them.

Changed in 2.4.3: split out of ``audio_suite_shared.batch_undo``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).

Changed in 2.7.0: the blind-``except`` boundary is named for the BLE001 triage
(WP-7 of ``PLAN_2026-11-03_2.4.1_stop_the_drift.md``, section 10).

"""

from __future__ import annotations

import logging
import pickle
import sqlite3

logger = logging.getLogger(f"audio_suite.{__name__}")


_AUTO_VACUUM_FULL = 1


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS undo_batches (
    batch_id TEXT PRIMARY KEY,
    tool_name TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS undo_records (
    record_id INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id TEXT NOT NULL REFERENCES undo_batches(batch_id),
    file_path TEXT NOT NULL,
    operation TEXT NOT NULL,
    old_tags_snapshot BLOB,
    source_path TEXT,
    dest_path TEXT,
    file_action TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_undo_batch ON undo_records(batch_id);
"""


def enable_auto_vacuum(conn: sqlite3.Connection) -> None:
    """Ensure the undo log reclaims freed pages automatically.

    Sets the persistent ``auto_vacuum=FULL`` file flag so every prune
    (batch cleanup) returns freed pages to the operating system at commit
    instead of leaving them inside a permanently growing database file.
    Files that predate the flag are converted in place with a one-time
    ``VACUUM``; once the flag is set, later connects only read it and
    skip.  Must be called under ``self._lock`` with no open transaction.
    """
    row = conn.execute("PRAGMA auto_vacuum").fetchone()
    if row is not None and int(row[0]) == _AUTO_VACUUM_FULL:
        return
    conn.execute("PRAGMA auto_vacuum = FULL")
    conn.commit()
    conn.execute("VACUUM")


def migrate_delete_payloads(conn: sqlite3.Connection) -> None:
    """Rewrite legacy pickled delete payloads to raw bytes.

    Pre-iteration-5 versions stored ``pickle.dumps(file_bytes)`` inside
    ``old_tags_snapshot``; new records store the raw bytes directly so
    a revert restores the exact file content without an unpickle.  The
    migration is gated by ``PRAGMA user_version`` so it runs at most
    once per database.  Must be called under ``self._lock``.
    """
    version_row = conn.execute("PRAGMA user_version").fetchone()
    if version_row is not None and int(version_row[0]) >= 1:
        return
    rows = conn.execute(
        "SELECT record_id, old_tags_snapshot FROM undo_records "
        "WHERE file_action = 'delete' AND old_tags_snapshot IS NOT NULL"
    ).fetchall()
    changed = 0
    for record_id, payload in rows:
        # Legacy payloads always begin with a pickle PROTO opcode.
        if payload[:1] == b"\x80":
            try:
                decoded = pickle.loads(payload)  # nosec B301 - legacy self-writes
            except Exception:  # noqa: BLE001 - skip undecodable legacy rows
                # Kept deliberately broad: skipping an undecodable legacy row
                # is the shipped migration contract, and a one-shot migration
                # must never abort on a single corrupt payload. ``exc_info``
                # records the concrete ``pickle.UnpicklingError`` / ``EOFError``
                # (or whatever else) so the skip is no longer silent. Narrowing
                # this to the two expected decode errors would turn a
                # best-effort migration into a potential startup failure.
                logger.warning(
                    "Skipping undecodable legacy undo payload for record %s "
                    "(it stays unmigrated; undo of that row will not restore "
                    "exact bytes)",
                    record_id,
                    exc_info=True,
                )
                continue
            if isinstance(decoded, bytes):
                conn.execute(
                    "UPDATE undo_records SET old_tags_snapshot = ? WHERE record_id = ?",
                    [decoded, record_id],
                )
                changed += 1
    if changed:
        conn.commit()
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
