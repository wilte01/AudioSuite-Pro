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

Changed in 2.4.3: split into ``undo_schema`` (DDL, auto_vacuum, migration),
``undo_records`` (the record types, batch lifecycle and pruning) and
``undo_revert`` (the revert paths). ``BatchUndoLog`` composes the two mixins
and keeps connection management; every moved name is re-exported here
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import logging
import os
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .undo_records import _DEFAULT_MAX_BYTES as _DEFAULT_MAX_BYTES
from .undo_records import _DEFAULT_MAX_ENTRIES as _DEFAULT_MAX_ENTRIES
from .undo_records import BatchInfo as BatchInfo
from .undo_records import RevertResult as RevertResult
from .undo_records import UndoRecord as UndoRecord
from .undo_records import UndoRecordsMixin as UndoRecordsMixin
from .undo_records import _load_max_bytes as _load_max_bytes
from .undo_records import _load_max_entries as _load_max_entries
from .undo_revert import UndoRevertMixin as UndoRevertMixin
from .undo_schema import _AUTO_VACUUM_FULL as _AUTO_VACUUM_FULL
from .undo_schema import _SCHEMA_SQL as _SCHEMA_SQL
from .undo_schema import enable_auto_vacuum, migrate_delete_payloads

logger = logging.getLogger(f"audio_suite.{__name__}")
_DB_LOCK = threading.Lock()
_BATCH_DB_PATHS: dict[str, Path] = {}
_ENV_DB_OVERRIDE = "AUDIOSUITE_UNDO_DB"


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


def record_tag_edit_snapshot(file_path: str, operation: str) -> bool:
    """Snapshot the current tags of *file_path* into the active batch.

    This is a no-op when no batch is active (zero overhead for normal
    non-batched usage).  Only the first snapshot per file in the batch is
    recorded — later writes to the same file are skipped (see
    :meth:`BatchUndoLog.record_tag_edit`).

    Args:
        file_path: Path to the audio file.
        operation: Name of the write operation about to happen.

    Returns:
        True when this call inserted the snapshot, False when no batch is
        active, the file already had one, or the snapshot itself failed.
    """
    batch_id = get_active_batch_id()
    if batch_id is None:
        return False

    try:
        from .tag_helper_base import TagHandlerFactory

        handler = TagHandlerFactory.get_handler(file_path)
        old_tags = handler.get_raw_tags()
        log: BatchUndoLog | None = getattr(_thread_local, "log", None)
        if log is None:
            return False
        return log.record_tag_edit(batch_id, file_path, operation, old_tags)
    except Exception:
        # Snapshot failure must never block the actual write operation.
        logger.debug("Failed to snapshot tags for %s", file_path, exc_info=True)
        return False


def discard_tag_edit_snapshot(file_path: str) -> None:
    """Drop the tag snapshot recorded for *file_path* because its write failed.

    The snapshot is taken *before* the write, because it has to describe the
    file's pre-run state.  When the write then raises, the file is unchanged,
    so keeping the record would offer the user an undo entry that can only
    rewrite the tags the file already has (WP-7, D-32).

    A no-op when no batch is active, and never fatal: a stale record is a
    cosmetic problem, whereas failing here would mask the write error.

    Args:
        file_path: Path to the audio file whose write failed.
    """
    batch_id = get_active_batch_id()
    if batch_id is None:
        return
    log: BatchUndoLog | None = getattr(_thread_local, "log", None)
    if log is None:
        return
    try:
        log.discard_tag_edit(batch_id, file_path)
    except Exception:
        logger.debug(
            "Failed to discard the tag snapshot for %s", file_path, exc_info=True
        )


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


class BatchUndoLog(UndoRecordsMixin, UndoRevertMixin):
    """SQLite-backed undo log for batch tag edits and file reorganizations.

    Thread-safe: all writes are serialised through a module-level lock.
    WAL mode allows concurrent reads while writing.  The two mixins supply
    record writing (``undo_records``) and reverting (``undo_revert``).
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

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            with self._lock:
                if self._conn is None:
                    self._conn = sqlite3.connect(
                        str(self._path), check_same_thread=False, timeout=30
                    )
                    self._conn.execute("PRAGMA journal_mode=WAL")
                    self._conn.executescript(_SCHEMA_SQL)
                    migrate_delete_payloads(self._conn)
                    enable_auto_vacuum(self._conn)
        return self._conn

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
