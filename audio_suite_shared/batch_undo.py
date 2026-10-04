"""
batch_undo.py — Centralised batch undo / revert log for Audio Suite.

Provides SQLite-backed logging of tag edits and file reorganizations so
that batch operations can be reverted after the fact.

Storage location: ``~/.audiosuite/undo_log.db`` (override with the
``AUDIOSUITE_UNDO_DB`` environment variable).  The database is created with
``auto_vacuum=FULL`` so pruned batches never leave free-page bloat behind.

Usage as context manager::

    with BatchUndoLog() as log:
        batch_id = log.start_batch("bpm_analyzer", "tag_edit")
        log.record_tag_edit(batch_id, "/music/song.mp3", "write_bpm", old_tags)
        log.commit_batch(batch_id)

Reverting a batch::

    with BatchUndoLog() as log:
        result = log.revert_batch(batch_id)

Auto-snapshot integration (used by ``tag_helper_writer``)::

    from audio_suite_shared.batch_undo import set_active_batch, clear_active_batch
    set_active_batch("bpm_analyzer", "tag_edit")
    # ... call write_bpm() etc. -- snapshots are taken automatically ...
    clear_active_batch()

Only the first tag snapshot per file is kept within a batch: a tool like
Mood Analyzer writes several tags (mood, confidence, energy) to each file
in one run, and each write would otherwise record its own entry, showing a
"3 files x 3 writes" count in the undo list.  The first snapshot already
captures the full pre-run tag state, so later ones are redundant.

What each record type stores
-----------------------------
* ``tag_edit``  — the pre-run tags (pickled).  Used by every tag-writing
  tool.  Reverting restores tags only; the audio is untouched, because
  those tools never rewrite it.
* ``overwrite`` — the file's complete pre-run **bytes**, stored raw.  Used
  by the in-place audio tools (noise reduction, pop/click removal, audio
  enhancer, silence trimmer), which replace the source file.  A revert
  restores the file byte for byte, which necessarily restores its tags too,
  so those runs record a single ``overwrite`` record instead of a redundant
  tag record.  This is the contract the iteration-6 B2 decision settled.
* ``delete``    — the deleted file's bytes, so a deleted file can be
  brought back.

The stored payloads are capped (see ``_DEFAULT_MAX_BYTES``).  Byte-level
records make that cap reachable with ordinary music collections, and the
prune drops **whole batches** oldest-first when the total exceeds it, so a
single very large run can push earlier runs out of the history.  This is
documented in the Undo Tag Edits user guide and pinned by a test, because
it is the one part of the undo contract that is a best-effort guarantee
rather than a promise.
"""

from __future__ import annotations

import logging
import os
import pickle
import sqlite3
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(f"audio_suite.{__name__}")

# Global lock shared by every BatchUndoLog instance: SQLite only permits one
# writer at a time, and separate instances must not step on each other.
_DB_LOCK = threading.Lock()

# Maps an active batch id to the DB path that created it so worker threads
# that join via use_batch() open the same database as the originator.
_BATCH_DB_PATHS: dict[str, Path] = {}

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

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

_DEFAULT_MAX_ENTRIES = 50

# Cap on total stored payload bytes (delete snapshots + pickled tags) before
# the oldest batches are pruned.  A few large lossless files can easily
# exceed any entry count, so the byte budget is enforced independently.
_DEFAULT_MAX_BYTES = 1024 * 1024 * 1024

# Environment variable that overrides the default undo-log location.  Pytest
# sets this for every session so CLI/GUI tests that wrap runs in
# ``active_batch(...)`` can never write into the real per-user database.
_ENV_DB_OVERRIDE = "AUDIOSUITE_UNDO_DB"

# SQLite auto_vacuum mode meaning FULL (deleted pages are returned to the OS
# at commit).  Set on every undo log so batch pruning never leaves bloat.
_AUTO_VACUUM_FULL = 1


def _default_db_path() -> Path:
    """Return the default undo-log database path.

    Honors the ``AUDIOSUITE_UNDO_DB`` environment variable (used by the test
    suite to isolate every batch from the real per-user log), falling back to
    ``~/.audiosuite/undo_log.db``.

    Returns:
        The resolved default database path.
    """
    override = os.environ.get(_ENV_DB_OVERRIDE)
    if override:
        return Path(override)
    return Path.home() / ".audiosuite" / "undo_log.db"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BatchInfo:
    """Lightweight view of an undo batch."""

    batch_id: str
    tool_name: str
    operation_type: str
    created_at: str
    record_count: int = 0


@dataclass(frozen=True)
class UndoRecord:
    """A single undoable record within a batch."""

    record_id: int
    batch_id: str
    file_path: str
    operation: str
    has_snapshot: bool
    source_path: str | None
    dest_path: str | None
    file_action: str | None


@dataclass
class RevertResult:
    """Outcome of reverting a batch."""

    batch_id: str
    reverted: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# BatchUndoLog
# ---------------------------------------------------------------------------


class BatchUndoLog:
    """SQLite-backed undo log for batch tag edits and file reorganizations.

    Thread-safe: all writes are serialised through a module-level lock.
    WAL mode allows concurrent reads while writing.

    Usage as context manager::

        with BatchUndoLog() as log:
            batch_id = log.start_batch("bpm_analyzer", "tag_edit")
            ...
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        """Initialise the undo log.

        Args:
            db_path: Path to the SQLite database.  Defaults to the path from
                the ``AUDIOSUITE_UNDO_DB`` environment variable when set,
                otherwise ``~/.audiosuite/undo_log.db``.
        """
        self._path = Path(db_path) if db_path else _default_db_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: sqlite3.Connection | None = None
        self._lock = _DB_LOCK

    # ── Connection management ─────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            with self._lock:
                if self._conn is None:
                    self._conn = sqlite3.connect(
                        str(self._path), check_same_thread=False, timeout=30
                    )
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    self._conn.executescript(_SCHEMA_SQL)
                    self._migrate_delete_payloads(self._conn)
                    self._enable_auto_vacuum(self._conn)
        return self._conn

    def _enable_auto_vacuum(self, conn: sqlite3.Connection) -> None:
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

    def _migrate_delete_payloads(self, conn: sqlite3.Connection) -> None:
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
                except Exception:
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
                        "UPDATE undo_records SET old_tags_snapshot = ? "
                        "WHERE record_id = ?",
                        [decoded, record_id],
                    )
                    changed += 1
        if changed:
            conn.commit()
        conn.execute("PRAGMA user_version = 1")
        conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> BatchUndoLog:
        self._connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def db_path(self) -> Path:
        """Return the path to the SQLite database file."""
        return self._path

    # ── Batch lifecycle ───────────────────────────────────────────────

    def start_batch(self, tool_name: str, operation_type: str) -> str:
        """Create a new undo batch and return its ID.

        Automatically prunes old batches beyond the configured count or
        stored-size maximum after inserting the new one.

        Args:
            tool_name: Identifier for the tool (e.g. ``"bpm_analyzer"``).
            operation_type: ``"tag_edit"`` or ``"file_reorg"``.

        Returns:
            The UUID hex string identifying this batch.
        """
        conn = self._connect()
        batch_id = uuid.uuid4().hex
        with self._lock:
            conn.execute(
                "INSERT INTO undo_batches (batch_id, tool_name, operation_type) "
                "VALUES (?, ?, ?)",
                [batch_id, tool_name, operation_type],
            )
            conn.commit()
            # Prune after insert so the total never exceeds the configured cap.
            self._cleanup_old_batches(conn)
        logger.debug(
            "Started undo batch %s [%s/%s]", batch_id, tool_name, operation_type
        )
        return batch_id

    def commit_batch(self, batch_id: str) -> None:
        """Finalise a batch (no-op kept for API symmetry).

        Records are persisted immediately; this method exists so callers
        can express intent without changes to existing flow.

        Args:
            batch_id: The batch to commit.
        """
        logger.debug("Committed undo batch %s", batch_id)

    def _batch_record_count(self, batch_id: str) -> int:
        """Return the number of records stored for *batch_id*."""
        conn = self._connect()
        with self._lock:
            row = conn.execute(
                "SELECT COUNT(*) FROM undo_records WHERE batch_id = ?", [batch_id]
            ).fetchone()
        return int(row[0]) if row else 0

    def delete_batch(self, batch_id: str) -> bool:
        """Delete a batch and all of its records.

        Args:
            batch_id: The batch to delete.

        Returns:
            True if the batch existed and was removed.
        """
        conn = self._connect()
        with self._lock:
            row = conn.execute(
                "SELECT 1 FROM undo_batches WHERE batch_id = ?", [batch_id]
            ).fetchone()
            if row is None:
                return False
            conn.execute("DELETE FROM undo_records WHERE batch_id = ?", [batch_id])
            conn.execute("DELETE FROM undo_batches WHERE batch_id = ?", [batch_id])
            conn.commit()
        logger.debug("Deleted undo batch %s", batch_id)
        return True

    # ── Recording operations ──────────────────────────────────────────

    def record_tag_edit(
        self,
        batch_id: str,
        file_path: str,
        operation: str,
        old_tags: Any,
    ) -> None:
        """Record a tag edit with a full snapshot of the previous tags.

        At most one snapshot per file is kept in a batch: the undo list and
        preview are file-oriented, so a run that writes several tags to the
        same file (e.g. Mood Analyzer's mood + confidence + energy) must not
        produce duplicate entries.  The first call records the true pre-run
        state; later calls for the same file are skipped because restoring
        that first snapshot already undoes every write in the run.

        Args:
            batch_id:   The batch this record belongs to.
            file_path:  Absolute path to the audio file.
            operation:  Name of the write operation (e.g. ``"write_bpm"``).
            old_tags:   Raw mutagen tags object *before* modification, or
                ``None`` when the file had no tag container.
        """
        snapshot = pickle.dumps(old_tags, protocol=pickle.HIGHEST_PROTOCOL)
        conn = self._connect()
        with self._lock:
            existing = conn.execute(
                "SELECT 1 FROM undo_records WHERE batch_id = ? AND file_path = ?",
                [batch_id, file_path],
            ).fetchone()
            if existing is not None:
                logger.debug(
                    "Skipped duplicate tag snapshot for %s in batch %s",
                    file_path,
                    batch_id,
                )
                return
            conn.execute(
                "INSERT INTO undo_records "
                "(batch_id, file_path, operation, old_tags_snapshot) "
                "VALUES (?, ?, ?, ?)",
                [batch_id, file_path, operation, snapshot],
            )
            conn.commit()

    def record_file_reorg(
        self,
        batch_id: str,
        source_path: str,
        dest_path: str,
        file_action: str,
    ) -> None:
        """Record a file copy or move operation.

        Args:
            batch_id:    The batch this record belongs to.
            source_path: Original file location.
            dest_path:   Target file location.
            file_action: ``"copy"`` or ``"move"``.
        """
        conn = self._connect()
        with self._lock:
            conn.execute(
                "INSERT INTO undo_records "
                "(batch_id, file_path, operation, source_path, dest_path, file_action) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [
                    batch_id,
                    source_path,
                    file_action,
                    source_path,
                    dest_path,
                    file_action,
                ],
            )
            conn.commit()

    def record_file_overwrite(
        self,
        batch_id: str,
        file_path: str,
        operation: str,
        file_bytes: bytes,
    ) -> None:
        """Record an in-place rewrite with the file's complete original bytes.

        Used by the audio tools that replace the source file (noise
        reduction, pop/click removal, ...).  The stored bytes are the whole
        pre-run file, so :meth:`_revert_file_overwrite` can put the file back
        exactly as it was - audio *and* tags, which is why a byte record
        replaces the tag record for these runs instead of accompanying it.

        As with :meth:`record_tag_edit`, only the first record per file is
        kept within a batch: it already holds the true pre-run state.

        The payload counts against the shared stored-bytes cap, so a large
        batch can push older batches out of the history.  See the module
        docstring.

        Args:
            batch_id:    The batch this record belongs to.
            file_path:   Path of the file that is about to be rewritten.
            operation:   Name of the write operation (e.g.
                ``"noise_reduce_edit"``), kept for the undo list.
            file_bytes:  The raw content of the file before the rewrite.
        """
        conn = self._connect()
        with self._lock:
            existing = conn.execute(
                "SELECT 1 FROM undo_records WHERE batch_id = ? AND file_path = ?",
                [batch_id, file_path],
            ).fetchone()
            if existing is not None:
                logger.debug(
                    "Skipped duplicate overwrite snapshot for %s in batch %s",
                    file_path,
                    batch_id,
                )
                return
            conn.execute(
                "INSERT INTO undo_records "
                "(batch_id, file_path, operation, old_tags_snapshot, file_action) "
                "VALUES (?, ?, ?, ?, ?)",
                [batch_id, file_path, operation, file_bytes, "overwrite"],
            )
            conn.commit()

    def record_file_delete(
        self,
        batch_id: str,
        file_path: str,
        file_bytes: bytes,
    ) -> None:
        """Record a file deletion with the deleted file's content.

        The full file content is stored as a raw BLOB in the undo record so
        that a later revert can restore the file at its original path
        without a redundant pickle round-trip (audio payloads can be large).

        Args:
            batch_id:    The batch this record belongs to.
            file_path:   Path of the file that is being (or was) deleted.
            file_bytes:  The raw content of the file before deletion.
        """
        conn = self._connect()
        with self._lock:
            conn.execute(
                "INSERT INTO undo_records "
                "(batch_id, file_path, operation, old_tags_snapshot, file_action) "
                "VALUES (?, ?, ?, ?, ?)",
                [batch_id, file_path, "file_delete", file_bytes, "delete"],
            )
            conn.commit()

    # ── Revert ────────────────────────────────────────────────────────

    def revert_batch(self, batch_id: str) -> RevertResult:
        """Revert all operations in a batch.

        Tag edits are reverted by restoring the pickled snapshot.
        In-place audio rewrites are reverted by writing the stored original
        bytes back, which restores the audio and its tags together.
        File moves are reverted by moving the file back.
        File copies are reverted by removing the copy (with a warning
        if the original is missing).

        Args:
            batch_id: The batch to revert.

        Returns:
            A ``RevertResult`` summarising successes and failures.
        """
        conn = self._connect()
        rows = conn.execute(
            "SELECT record_id, file_path, operation, old_tags_snapshot, "
            "source_path, dest_path, file_action "
            "FROM undo_records WHERE batch_id = ? ORDER BY record_id",
            [batch_id],
        ).fetchall()

        result = RevertResult(batch_id=batch_id)

        for row in rows:
            record_id, file_path, _operation, snapshot, src, dst, action = row
            try:
                if snapshot is not None and action == "delete":
                    self._revert_file_delete(file_path, snapshot)
                    result.reverted += 1
                elif snapshot is not None and action == "overwrite":
                    # Must precede the generic tag branch below: this payload
                    # is raw file content, not a pickled tags object.
                    self._revert_file_overwrite(file_path, snapshot)
                    result.reverted += 1
                elif snapshot is not None:
                    self._revert_tag_edit(file_path, snapshot)
                    result.reverted += 1
                elif action in ("move", "copy") and src and dst:
                    if self._revert_file_reorg(src, dst, action):
                        result.reverted += 1
                    else:
                        result.skipped += 1
                else:
                    result.skipped += 1
            except Exception as exc:
                msg = f"[record {record_id}] {file_path}: {exc}"
                result.errors.append(msg)
                result.failed += 1
                logger.warning("Failed to revert record %d: %s", record_id, exc)

        if result.reverted > 0:
            logger.info(
                "Reverted batch %s: %d reverted, %d failed, %d skipped",
                batch_id,
                result.reverted,
                result.failed,
                result.skipped,
            )
        return result

    def _revert_tag_edit(self, file_path: str, snapshot: bytes) -> None:
        """Restore tags from a pickled snapshot.

        Args:
            file_path: Path to the audio file to restore.
            snapshot:  Pickled mutagen tags object.
        """
        from .tag_helper_base import TagHandlerFactory

        # Snapshot data is written exclusively by our own record_tag_edit()
        # into a local per-user database; never user-supplied input.
        tags = pickle.loads(snapshot)  # nosec B301
        handler = TagHandlerFactory.get_handler(file_path)
        if tags is None:
            handler.delete_tags()
        else:
            handler.set_raw_tags(tags)
        logger.debug("Restored tags for %s", file_path)

    def _revert_file_reorg(self, source_path: str, dest_path: str, action: str) -> bool:
        """Reverse a file copy or move.

        Args:
            source_path: Original file location.
            dest_path:   Current file location.
            action:      ``"move"`` or ``"copy"``.

        Returns:
            True if the reversal actually happened, False when there was
            nothing to undo (e.g. a copy whose target is already gone).
        """
        import shutil

        if action == "move":
            shutil.move(dest_path, source_path)
            logger.debug("Reverted move: %s -> %s", dest_path, source_path)
            return True
        if action == "copy":
            if os.path.exists(dest_path):
                os.remove(dest_path)
                logger.debug("Removed copy: %s", dest_path)
                return True
            logger.warning("Copy target already gone: %s", dest_path)
            return False
        return False

    def _revert_file_overwrite(self, file_path: str, snapshot: bytes) -> None:
        """Restore a file that a tool rewrote in place, byte for byte.

        Written to a sibling temp file and moved into place, because this
        revert *overwrites a file that exists*: a failure part-way through a
        direct write would leave the user with neither the processed audio nor
        the original, whereas an interrupted temp write leaves the current
        file untouched.

        Args:
            file_path: Path of the file that was rewritten.
            snapshot:  Raw bytes of the file's content before the rewrite.
        """
        # The blob is written exclusively by our own record_file_overwrite()
        # into a local per-user database; never user-supplied input.
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_name(f"{path.name}.undo-restore")
        try:
            with open(temp, "wb") as fh:
                fh.write(snapshot)
            os.replace(temp, path)
        except OSError:
            temp.unlink(missing_ok=True)
            raise
        logger.debug("Restored in-place rewrite of %s", file_path)

    def _revert_file_delete(self, file_path: str, snapshot: bytes) -> None:
        """Restore a deleted file from its raw content blob.

        Args:
            file_path: Original path of the deleted file.
            snapshot:  Raw bytes of the file's content.
        """
        # The blob is written exclusively by our own record_file_delete()
        # into a local per-user database; never user-supplied input.
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(snapshot)
        logger.debug("Restored deleted file %s", file_path)

    # ── Query ─────────────────────────────────────────────────────────

    def list_batches(self, limit: int = 50) -> list[BatchInfo]:
        """Return recent batches, newest first.

        Args:
            limit: Maximum number of batches to return.

        Returns:
            List of ``BatchInfo`` dataclasses.
        """
        conn = self._connect()
        rows = conn.execute(
            "SELECT b.batch_id, b.tool_name, b.operation_type, b.created_at, "
            "COUNT(r.record_id) AS record_count "
            "FROM undo_batches b "
            "LEFT JOIN undo_records r ON r.batch_id = b.batch_id "
            "GROUP BY b.batch_id "
            "ORDER BY b.rowid DESC "
            "LIMIT ?",
            [limit],
        ).fetchall()
        return [
            BatchInfo(
                batch_id=row[0],
                tool_name=row[1],
                operation_type=row[2],
                created_at=row[3],
                record_count=row[4],
            )
            for row in rows
        ]

    def get_batch_records(self, batch_id: str) -> list[UndoRecord]:
        """Return all records for a batch, in order.

        Args:
            batch_id: The batch to query.

        Returns:
            List of ``UndoRecord`` dataclasses.
        """
        conn = self._connect()
        rows = conn.execute(
            "SELECT record_id, batch_id, file_path, operation, "
            "old_tags_snapshot, source_path, dest_path, file_action "
            "FROM undo_records WHERE batch_id = ? ORDER BY record_id",
            [batch_id],
        ).fetchall()
        return [
            UndoRecord(
                record_id=row[0],
                batch_id=row[1],
                file_path=row[2],
                operation=row[3],
                has_snapshot=row[4] is not None,
                source_path=row[5],
                dest_path=row[6],
                file_action=row[7],
            )
            for row in rows
        ]

    # ── Cleanup ───────────────────────────────────────────────────────

    def cleanup(
        self,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        max_bytes: int | None = None,
    ) -> int:
        """Prune the oldest batches beyond the configured limits.

        Two independent caps are enforced, oldest batches first (the
        config-driven equivalents from ``suite_config`` are used when the
        arguments are omitted):

        - *max_entries*: keep at most this many batches.
        - *max_bytes*:   keep at most this many total stored payload bytes
          (delete snapshots + pickled tags), so a few large files cannot
          pin the whole undo history in the database.

        Also deletes orphaned records whose batch no longer exists.

        Args:
            max_entries: Keep at most this many batches.
            max_bytes:   Keep at most this many stored payload bytes.  Uses
                the configured ``undo_max_bytes`` when ``None``.

        Returns:
            Number of batches removed.
        """
        conn = self._connect()
        with self._lock:
            return self._cleanup_old_batches(conn, max_entries, max_bytes)

    def _cleanup_old_batches(
        self,
        conn: sqlite3.Connection,
        max_entries: int | None = None,
        max_bytes: int | None = None,
    ) -> int:
        """Internal prune helper.  Must be called under ``self._lock``."""
        if max_entries is None:
            max_entries = _load_max_entries()
        if max_bytes is None:
            max_bytes = _load_max_bytes()

        removed = 0

        # Count current batches
        count_row = conn.execute("SELECT COUNT(*) FROM undo_batches").fetchone()
        current_count: int = count_row[0] if count_row else 0
        if current_count > max_entries:
            excess = current_count - max_entries
            # CTE is materialised before the DELETE runs, so it is safe to
            # reference undo_batches in both the CTE and the target table.
            # rowid order matches insertion order (created_at only has 1-second
            # resolution and can tie for rapid successive starts).
            conn.execute(
                "WITH old_batches AS (SELECT batch_id FROM undo_batches "
                "ORDER BY rowid ASC LIMIT ?) "
                "DELETE FROM undo_records WHERE batch_id IN "
                "(SELECT batch_id FROM old_batches)",
                [excess],
            )
            conn.execute(
                "WITH old_batches AS (SELECT batch_id FROM undo_batches "
                "ORDER BY rowid ASC LIMIT ?) "
                "DELETE FROM undo_batches WHERE batch_id IN "
                "(SELECT batch_id FROM old_batches)",
                [excess],
            )
            conn.commit()
            logger.debug("Pruned %d old undo batches", excess)
            removed += excess

        # Size-based prune: drop the oldest batches (and their payloads)
        # until the stored payload total fits under the byte cap.  Repeated
        # single-batch deletes avoid dynamic SQL entirely.
        size_row = conn.execute(
            "SELECT COALESCE(SUM(LENGTH(old_tags_snapshot)), 0) FROM undo_records"
        ).fetchone()
        total_bytes: int = size_row[0] if size_row else 0
        pruned_by_size = 0
        if max_bytes > 0 and total_bytes > max_bytes:
            while total_bytes > max_bytes:
                oldest = conn.execute(
                    "SELECT batch_id FROM undo_batches ORDER BY rowid ASC LIMIT 1"
                ).fetchone()
                if oldest is None:
                    break
                batch_bytes = conn.execute(
                    "SELECT COALESCE(SUM(LENGTH(old_tags_snapshot)), 0) "
                    "FROM undo_records WHERE batch_id = ?",
                    [oldest[0]],
                ).fetchone()
                conn.execute("DELETE FROM undo_records WHERE batch_id = ?", [oldest[0]])
                conn.execute("DELETE FROM undo_batches WHERE batch_id = ?", [oldest[0]])
                total_bytes -= int(batch_bytes[0]) if batch_bytes else 0
                removed += 1
                pruned_by_size += 1
            conn.commit()
            if pruned_by_size:
                logger.debug(
                    "Pruned %d undo batches to fit the %d-byte size cap",
                    pruned_by_size,
                    max_bytes,
                )
        return removed


# ---------------------------------------------------------------------------
# Auto-snapshot integration (thread-local active batch context)
# ---------------------------------------------------------------------------

_thread_local = threading.local()


def set_active_batch(
    tool_name: str, operation_type: str, db_path: str | Path | None = None
) -> str:
    """Set the active undo batch for the current thread.

    While active, ``record_tag_edit_snapshot()`` will automatically
    snapshot tags before the first write to each file.

    Args:
        tool_name:      Tool identifier.
        operation_type: ``"tag_edit"`` or ``"file_reorg"``.
        db_path:        Path to the undo log database.  Defaults to the
            standard ``~/.audiosuite/undo_log.db``.

    Returns:
        The batch ID.
    """
    log = BatchUndoLog(db_path=db_path)
    log.__enter__()
    batch_id = log.start_batch(tool_name, operation_type)
    _BATCH_DB_PATHS[batch_id] = log.db_path
    _thread_local.batch_id = batch_id
    _thread_local.log = log
    _thread_local.enabled = True
    return batch_id


def get_active_batch_id() -> str | None:
    """Return the current thread's active batch ID, or ``None``."""
    return getattr(_thread_local, "batch_id", None)


def is_undo_enabled() -> bool:
    """Return ``True`` if an active batch is set for this thread."""
    return getattr(_thread_local, "enabled", False)


def record_tag_edit_snapshot(file_path: str, operation: str) -> None:
    """Snapshot the current tags of *file_path* into the active batch.

    This is a no-op when no batch is active (zero overhead for normal
    non-batched usage).  Only the first snapshot per file in the batch is
    recorded — later writes to the same file are skipped (see
    :meth:`BatchUndoLog.record_tag_edit`).

    Args:
        file_path: Path to the audio file.
        operation: Name of the write operation about to happen.
    """
    batch_id = get_active_batch_id()
    if batch_id is None:
        return

    try:
        from .tag_helper_base import TagHandlerFactory

        handler = TagHandlerFactory.get_handler(file_path)
        old_tags = handler.get_raw_tags()
        log: BatchUndoLog | None = getattr(_thread_local, "log", None)
        if log is not None:
            log.record_tag_edit(batch_id, file_path, operation, old_tags)
    except Exception:
        # Snapshot failure must never block the actual write operation.
        logger.debug("Failed to snapshot tags for %s", file_path, exc_info=True)


def record_audio_overwrite_snapshot(file_path: str, operation: str) -> None:
    """Snapshot a file's bytes before a tool rewrites it in place.

    This is the undo hook for the in-place audio tools: it stores the whole
    file (audio **and** tags) so :meth:`BatchUndoLog.revert_batch` can restore
    it exactly, which is the contract the iteration-6 B2 decision settled.
    Call it immediately before the bytes are replaced, while the file is still
    in its pre-run state.

    A no-op when no batch is active, so unbatched runs pay nothing.  If the
    file cannot be read it degrades to a tag-only snapshot rather than
    recording nothing at all, and a recording failure never blocks the write.

    Args:
        file_path: Path to the audio file that is about to be rewritten.
        operation: Name of the write operation, kept on the undo record.
    """
    batch_id = get_active_batch_id()
    if batch_id is None:
        return

    log: BatchUndoLog | None = getattr(_thread_local, "log", None)
    if log is None:
        return

    try:
        # Read outside the module lock: a 40 MB FLAC must not serialise every
        # other worker's snapshot behind this read.
        with open(file_path, "rb") as fh:
            original = fh.read()
    except OSError:
        logger.debug(
            "Could not read %s for a byte-level snapshot; falling back to tags",
            file_path,
            exc_info=True,
        )
        record_tag_edit_snapshot(file_path, operation)
        return

    try:
        log.record_file_overwrite(batch_id, file_path, operation, original)
    except Exception:
        # Snapshot failure must never block the actual write operation.
        logger.debug("Failed to snapshot bytes for %s", file_path, exc_info=True)


def record_file_reorg_snapshot(
    source_path: str, dest_path: str, file_action: str
) -> None:
    """Record a file reorganization into the active batch.

    No-op when no batch is active.

    Args:
        source_path: Original file location.
        dest_path:   Target file location.
        file_action: ``"copy"`` or ``"move"``.
    """
    batch_id = get_active_batch_id()
    if batch_id is None:
        return

    log: BatchUndoLog | None = getattr(_thread_local, "log", None)
    if log is not None:
        log.record_file_reorg(batch_id, source_path, dest_path, file_action)


def record_file_delete_snapshot(file_path: str, file_bytes: bytes) -> None:
    """Record a file deletion into the active batch.

    No-op when no batch is active.

    Args:
        file_path:   Path of the file that is being (or was) deleted.
        file_bytes:  The raw content of the file before deletion.
    """
    batch_id = get_active_batch_id()
    if batch_id is None:
        return

    log: BatchUndoLog | None = getattr(_thread_local, "log", None)
    if log is not None:
        log.record_file_delete(batch_id, file_path, file_bytes)


def clear_active_batch() -> None:
    """Commit and close the active batch for the current thread.

    Batches that ended up with no records (dry runs, nothing modified) are
    deleted so they never show up in the undo list.
    """
    log: BatchUndoLog | None = getattr(_thread_local, "log", None)
    batch_id = getattr(_thread_local, "batch_id", None)
    if log is not None and batch_id is not None:
        log.commit_batch(batch_id)
        if log._batch_record_count(batch_id) == 0:
            log.delete_batch(batch_id)
        log.__exit__(None, None, None)
    if batch_id is not None:
        _BATCH_DB_PATHS.pop(batch_id, None)
    _thread_local.batch_id = None
    _thread_local.log = None
    _thread_local.enabled = False


@contextmanager
def active_batch(
    tool_name: str, operation_type: str, db_path: str | Path | None = None
) -> Iterator[str]:
    """Context manager that opens and closes an active undo batch.

    Yields the batch id; snapshots taken inside the ``with`` block are
    recorded against it and the batch is committed (or pruned if empty)
    on exit.

    Args:
        tool_name:      Tool identifier (e.g. ``"bpm_analyzer"``).
        operation_type: ``"tag_edit"`` or ``"file_reorg"``.
        db_path:        Path to the undo log database.  Defaults to the
            standard ``~/.audiosuite/undo_log.db``.

    Yields:
        The batch id string.
    """
    batch_id = set_active_batch(tool_name, operation_type, db_path=db_path)
    try:
        yield batch_id
    finally:
        clear_active_batch()


@contextmanager
def use_batch(
    batch_id: str | None, db_path: str | Path | None = None
) -> Iterator[str | None]:
    """Temporarily join an existing undo batch in the current thread.

    Used by worker threads (which otherwise have no active batch) so that
    snapshots they take are recorded against the batch opened by the
    orchestrating thread.  A no-op when *batch_id* is ``None``.

    Args:
        batch_id: Batch id to join, or ``None`` to do nothing.
        db_path:  Path to the undo log database.  Defaults to the database
            that created the batch (or the standard undo log).

    Yields:
        The joined batch id (or ``None``).
    """
    if batch_id is None:
        yield None
        return

    prev_log: BatchUndoLog | None = getattr(_thread_local, "log", None)
    prev_batch = getattr(_thread_local, "batch_id", None)
    prev_enabled = getattr(_thread_local, "enabled", False)

    opened_log = prev_log is None
    if opened_log:
        path = db_path or _BATCH_DB_PATHS.get(batch_id)
        log = BatchUndoLog(db_path=path)
        log.__enter__()
        _thread_local.log = log
    _thread_local.batch_id = batch_id
    _thread_local.enabled = True
    try:
        yield batch_id
    finally:
        _thread_local.batch_id = prev_batch
        _thread_local.enabled = prev_enabled
        if opened_log:
            _thread_local.log = prev_log
            log.__exit__(None, None, None)


def revert_batch_by_id(
    batch_id: str, db_path: str | Path | None = None
) -> RevertResult:
    """Convenience wrapper: open a ``BatchUndoLog``, revert, and close.

    Args:
        batch_id: The batch to revert.
        db_path:  Path to the undo log database.  Defaults to the standard
            ``~/.audiosuite/undo_log.db``.

    Returns:
        ``RevertResult`` summarising the revert.
    """
    with BatchUndoLog(db_path=db_path) as log:
        return log.revert_batch(batch_id)


def list_recent_batches(
    limit: int = 50, db_path: str | Path | None = None
) -> list[BatchInfo]:
    """Convenience wrapper: list recent undo batches.

    Args:
        limit:   Maximum batches to return.
        db_path: Path to the undo log database.  Defaults to the standard
            ``~/.audiosuite/undo_log.db``.

    Returns:
        List of ``BatchInfo`` dataclasses.
    """
    with BatchUndoLog(db_path=db_path) as log:
        return log.list_batches(limit)


# ---------------------------------------------------------------------------
# Configuration helpers
# ---------------------------------------------------------------------------


def _load_max_entries() -> int:
    """Load the configured maximum undo entries from suite_config."""
    try:
        from . import suite_config

        raw = suite_config.load_value("undo_max_entries", _DEFAULT_MAX_ENTRIES)
        if isinstance(raw, int) and raw > 0:
            return raw
        if isinstance(raw, str):
            parsed = int(raw.strip())
            if parsed > 0:
                return parsed
    except (TypeError, ValueError) as exc:
        logger.debug("Invalid undo_max_entries config: %s", exc)
    except Exception as exc:
        logger.debug("Could not read undo_max_entries config: %s", exc)
    return _DEFAULT_MAX_ENTRIES


def _load_max_bytes() -> int:
    """Load the configured maximum stored undo payload bytes."""
    try:
        from . import suite_config

        raw = suite_config.load_value("undo_max_bytes", _DEFAULT_MAX_BYTES)
        if isinstance(raw, int) and raw > 0:
            return raw
        if isinstance(raw, str):
            parsed = int(raw.strip())
            if parsed > 0:
                return parsed
    except (TypeError, ValueError) as exc:
        logger.debug("Invalid undo_max_bytes config: %s", exc)
    except Exception as exc:
        logger.debug("Could not read undo_max_bytes config: %s", exc)
    return _DEFAULT_MAX_BYTES
