"""
undo_records.py - part of the batch undo log, split out in 2.4.3.

WP-9 #3 moved this group of methods off ``BatchUndoLog`` into
``UndoRecordsMixin``; method bodies are unchanged and ``batch_undo`` still
re-exports every public name.

Changed in 2.4.3: split out of ``audio_suite_shared.batch_undo``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import logging
import pickle
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(f"audio_suite.{__name__}")


_DEFAULT_MAX_ENTRIES = 50

_DEFAULT_MAX_BYTES = 1024 * 1024 * 1024


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


class UndoRecordsMixin:
    """Batch lifecycle and record writing half of ``BatchUndoLog``."""

    _conn: sqlite3.Connection | None
    _lock: threading.Lock
    _path: Path

    def _connect(self) -> sqlite3.Connection:
        """Provided by ``BatchUndoLog`` itself; composed ahead of this mixin."""
        raise NotImplementedError

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

    def record_tag_edit(
        self,
        batch_id: str,
        file_path: str,
        operation: str,
        old_tags: Any,
    ) -> bool:
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

        Returns:
            True when this call inserted the snapshot, False when the batch
            already held one for the file (or no batch is active).
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
                return False
            conn.execute(
                "INSERT INTO undo_records "
                "(batch_id, file_path, operation, old_tags_snapshot) "
                "VALUES (?, ?, ?, ?)",
                [batch_id, file_path, operation, snapshot],
            )
            conn.commit()
        return True

    def discard_tag_edit(self, batch_id: str, file_path: str) -> None:
        """Remove the tag snapshot recorded for *file_path* in *batch_id*.

        Used when the write the snapshot was taken for failed: the file is
        unchanged, so the record would offer an undo entry that can only
        rewrite the tags the file already has (WP-7, D-32).

        Only tag-edit rows are removed. A byte-level overwrite row for the same
        file has ``file_action = 'overwrite'`` and is left alone, because it
        restores audio that really was rewritten.

        Args:
            batch_id:  The batch holding the record.
            file_path: Absolute path to the audio file.
        """
        conn = self._connect()
        with self._lock:
            conn.execute(
                "DELETE FROM undo_records "
                "WHERE batch_id = ? AND file_path = ? AND file_action IS NULL",
                [batch_id, file_path],
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

    def list_batches(self, limit: int = 50) -> list[BatchInfo]:
        """Return recent batches, newest first.

        Args:
            limit: Maximum number of batches to return.

        Returns:
            List of ``BatchInfo`` dataclasses.
        """
        conn = self._connect()
        # Read outside self._lock: WAL mode allows concurrent reads while a
        # writer holds the lock.  The ORDER BY rowid ensures newest-first
        # without relying on datetime resolution (see _cleanup_old_batches).
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
        # Read outside self._lock: WAL mode allows concurrent reads while a
        # writer holds the lock, so the SELECT sees the last committed state.
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
    except Exception as exc:  # noqa: BLE001 - unreadable config uses the default
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
    except Exception as exc:  # noqa: BLE001 - unreadable config uses the default
        logger.debug("Could not read undo_max_bytes config: %s", exc)
    return _DEFAULT_MAX_BYTES
