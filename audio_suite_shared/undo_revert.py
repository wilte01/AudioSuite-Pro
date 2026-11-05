"""
undo_revert.py - part of the batch undo log, split out in 2.4.3.

WP-9 #3 moved this group of methods off ``BatchUndoLog`` into
``UndoRevertMixin``; method bodies are unchanged and ``batch_undo`` still
re-exports every public name.

Changed in 2.4.3: split out of ``audio_suite_shared.batch_undo``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import logging
import os
import pickle
import sqlite3
import threading
from pathlib import Path

from .undo_records import RevertResult

logger = logging.getLogger(f"audio_suite.{__name__}")


class UndoRevertMixin:
    """Revert half of ``BatchUndoLog``."""

    _lock: threading.Lock

    def _connect(self) -> sqlite3.Connection:
        """Provided by ``BatchUndoLog`` itself; composed ahead of this mixin."""
        raise NotImplementedError

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
        # Read outside self._lock: WAL mode allows concurrent reads while a
        # writer holds the lock, so the SELECT sees the last committed state.
        # The revert itself acquires self._lock for any writes it performs.
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
            # Changed in 2.4.1: BLE001 triage (WP-7 of
            # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
            # BLE001 boundary: a bad record is counted, the run goes on
            except Exception as exc:  # noqa: BLE001
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
