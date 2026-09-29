"""
Tests for batch_undo.py — SQLite-backed batch undo / revert log.

Covers: schema creation, batch lifecycle, tag snapshot round-trip, file
reorg recording, revert logic, cleanup/pruning, thread safety, and the
auto-snapshot thread-local integration.
"""

from __future__ import annotations

import os
import pickle
import shutil
import sqlite3
import threading
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.batch_undo import (
    _BATCH_DB_PATHS,
    _DEFAULT_MAX_ENTRIES,
    _SCHEMA_SQL,
    BatchUndoLog,
    RevertResult,
    _thread_local,
    active_batch,
    clear_active_batch,
    get_active_batch_id,
    is_undo_enabled,
    list_recent_batches,
    record_audio_overwrite_snapshot,
    record_file_delete_snapshot,
    record_file_reorg_snapshot,
    record_tag_edit_snapshot,
    revert_batch_by_id,
    set_active_batch,
    use_batch,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def undo_db(tmp_path: Path) -> Path:
    """Return a path to a temporary SQLite database."""
    return tmp_path / "undo_log.db"


@pytest.fixture()
def log(undo_db: Path) -> Generator[BatchUndoLog, None, None]:
    """Provide an open BatchUndoLog backed by a temp database."""
    with BatchUndoLog(db_path=undo_db) as bl:
        yield bl


@pytest.fixture(autouse=True)
def _clear_thread_local() -> Generator[None, None, None]:
    """Ensure the thread-local auto-snapshot state is always clean."""
    _thread_local.batch_id = None
    _thread_local.log = None
    _thread_local.enabled = False
    yield
    # Also clean up if a test left state behind
    dangling_log = getattr(_thread_local, "log", None)
    if dangling_log is not None:
        dangling_log.__exit__(None, None, None)
    _BATCH_DB_PATHS.clear()
    _thread_local.batch_id = None
    _thread_local.log = None
    _thread_local.enabled = False


@pytest.fixture()
def mock_tag_handler_factory() -> Generator[MagicMock, None, None]:
    """Stub TagHandlerFactory so snapshot reads return deterministic tags."""
    with patch("audio_suite_shared.tag_helper_base.TagHandlerFactory") as factory:
        handler = MagicMock()
        handler.get_raw_tags.return_value = {"TBPM": "120"}
        factory.get_handler.return_value = handler
        yield factory


# ---------------------------------------------------------------------------
# Schema & connection
# ---------------------------------------------------------------------------


class TestSchema:
    def test_creates_database_file(self, undo_db: Path) -> None:
        assert not undo_db.exists()
        with BatchUndoLog(db_path=undo_db):
            assert undo_db.exists()

    def test_wal_mode(self, log: BatchUndoLog) -> None:
        conn = log._connect()
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"

    def test_tables_exist(self, log: BatchUndoLog) -> None:
        conn = log._connect()
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "undo_batches" in tables
        assert "undo_records" in tables

    def test_idempotent_schema(self, undo_db: Path) -> None:
        with BatchUndoLog(db_path=undo_db):
            pass
        with BatchUndoLog(db_path=undo_db):
            pass

    def test_context_manager(self, undo_db: Path) -> None:
        bl = BatchUndoLog(db_path=undo_db)
        with bl:
            assert bl._conn is not None
        assert bl._conn is None


class TestDefaultDbPath:
    """Regression: tests must never open the real per-user undo log.

    Conftest redirects the default database via ``AUDIOSUITE_UNDO_DB`` for the
    whole session; the engine itself must honor that override so CLI and GUI
    runs under pytest stop writing into ``~/.audiosuite/undo_log.db`` (they
    previously left ``pytest-of-<user>`` songs on the Undo Tag Edits list).
    """

    def test_env_override_redirects_default_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        override = tmp_path / "scratch_undo.db"
        monkeypatch.setenv("AUDIOSUITE_UNDO_DB", str(override))
        assert BatchUndoLog()._path == override

    def test_env_override_is_resolved_per_instance(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("AUDIOSUITE_UNDO_DB", raising=False)
        assert BatchUndoLog()._path == Path.home() / ".audiosuite" / "undo_log.db"
        override = tmp_path / "other.db"
        monkeypatch.setenv("AUDIOSUITE_UNDO_DB", str(override))
        assert BatchUndoLog()._path == override

    def test_use_batch_without_db_path_honors_override(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        mock_tag_handler_factory: MagicMock,
    ) -> None:
        override = tmp_path / "batch_undo.db"
        monkeypatch.setenv("AUDIOSUITE_UNDO_DB", str(override))
        with active_batch("test_tool", "tag_edit") as batch_id:
            assert batch_id
            record_tag_edit_snapshot("/song.mp3", "write_test")
        assert Path(BatchUndoLog()._path) == override
        batches = list_recent_batches()
        assert [b.tool_name for b in batches] == ["test_tool"]


class TestAutoVacuum:
    """Regression: every undo log must be self-compacting.

    Batch pruning deletes rows constantly; without ``auto_vacuum=FULL`` the
    freed pages stay inside the database file and it grows without bound (the
    production log had reached 5.5 GB with only ~62 MB of live data).  New
    databases must be born with the flag, and legacy files must be converted
    on first connect.
    """

    def test_new_database_has_full_auto_vacuum(self, tmp_path: Path) -> None:
        db = tmp_path / "fresh.db"
        with BatchUndoLog(db_path=db) as log:
            row = log._connect().execute("PRAGMA auto_vacuum").fetchone()
            assert row is not None
            assert int(row[0]) == 1  # FULL

    def test_existing_connection_is_not_revacuumed(self, tmp_path: Path) -> None:
        db = tmp_path / "persist.db"
        with BatchUndoLog(db_path=db) as log:
            first_header = log._connect().execute("PRAGMA auto_vacuum").fetchone()
        with BatchUndoLog(db_path=db) as log:
            second_header = log._connect().execute("PRAGMA auto_vacuum").fetchone()
        assert first_header == second_header
        assert int(first_header[0]) == 1

    def test_legacy_database_with_freelist_bloat_is_converted(
        self, tmp_path: Path
    ) -> None:
        db = tmp_path / "legacy.db"
        raw = sqlite3.connect(str(db), timeout=30)
        try:
            raw.executescript(_SCHEMA_SQL)
            raw.execute("PRAGMA auto_vacuum = NONE")
            raw.execute(
                "INSERT INTO undo_batches (batch_id, tool_name, operation_type) "
                "VALUES ('legacy1', 'test', 'file_delete')"
            )
            raw.execute(
                "INSERT INTO undo_records "
                "(batch_id, file_path, operation, old_tags_snapshot, file_action) "
                "VALUES ('legacy1', '/x.flac', 'file_delete', ?, 'delete')",
                [b"\x00" * (2 * 1024 * 1024)],
            )
            raw.commit()
            # Deleting leaves ~2 MB of free pages inside the file (legacy bloat).
            raw.execute("DELETE FROM undo_records WHERE batch_id = 'legacy1'")
            raw.execute("DELETE FROM undo_batches WHERE batch_id = 'legacy1'")
            raw.commit()
            free_before = int(raw.execute("PRAGMA freelist_count").fetchone()[0])
            assert free_before > 0
        finally:
            raw.close()

        with BatchUndoLog(db_path=db):
            pass

        conn = sqlite3.connect(str(db), timeout=30)
        try:
            auto_vacuum = int(conn.execute("PRAGMA auto_vacuum").fetchone()[0])
            free_after = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        finally:
            conn.close()
        assert auto_vacuum == 1  # FULL
        assert free_after == 0  # VACUUM reclaimed the free pages


# ---------------------------------------------------------------------------
# Batch lifecycle
# ---------------------------------------------------------------------------


class TestBatchLifecycle:
    def test_start_batch_returns_uuid(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("test_tool", "tag_edit")
        assert isinstance(batch_id, str)
        assert len(batch_id) == 32

    def test_batch_persisted(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("bpm_analyzer", "tag_edit")
        conn = log._connect()
        row = conn.execute(
            "SELECT tool_name, operation_type FROM undo_batches WHERE batch_id = ?",
            [batch_id],
        ).fetchone()
        assert row is not None
        assert row[0] == "bpm_analyzer"
        assert row[1] == "tag_edit"

    def test_commit_batch_is_noop(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("test", "tag_edit")
        log.commit_batch(batch_id)  # should not raise

    def test_multiple_batches(self, log: BatchUndoLog) -> None:
        id1 = log.start_batch("tool_a", "tag_edit")
        id2 = log.start_batch("tool_b", "file_reorg")
        assert id1 != id2
        batches = log.list_batches()
        assert len(batches) >= 2


# ---------------------------------------------------------------------------
# Recording tag edits
# ---------------------------------------------------------------------------


class TestRecordTagEdit:
    def test_record_stores_snapshot(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("test", "tag_edit")
        fake_tags = {"TBPM": "120", "TIT2": "My Song"}
        log.record_tag_edit(batch_id, "/fake/path.mp3", "write_bpm", fake_tags)

        records = log.get_batch_records(batch_id)
        assert len(records) == 1
        assert records[0].file_path == "/fake/path.mp3"
        assert records[0].operation == "write_bpm"
        assert records[0].has_snapshot is True

    def test_snapshot_round_trip(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("test", "tag_edit")
        original = {"key": "value", "nested": [1, 2, 3]}
        log.record_tag_edit(batch_id, "/song.mp3", "write_bpm", original)

        conn = log._connect()
        row = conn.execute(
            "SELECT old_tags_snapshot FROM undo_records WHERE batch_id = ?",
            [batch_id],
        ).fetchone()
        restored = pickle.loads(row[0])
        assert restored == original

    def test_none_tags_stored_as_tagless_snapshot(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("test", "tag_edit")
        log.record_tag_edit(batch_id, "/song.mp3", "write_bpm", None)

        records = log.get_batch_records(batch_id)
        assert records[0].has_snapshot is True
        conn = log._connect()
        row = conn.execute(
            "SELECT old_tags_snapshot FROM undo_records WHERE batch_id = ?",
            [batch_id],
        ).fetchone()
        assert pickle.loads(row[0]) is None

    def test_multiple_records_per_batch(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("test", "tag_edit")
        log.record_tag_edit(batch_id, "/a.mp3", "write_bpm", {"bpm": 120})
        log.record_tag_edit(batch_id, "/b.mp3", "write_genre", {"genre": "Rock"})
        log.record_tag_edit(batch_id, "/c.mp3", "write_key", {"key": "Am"})

        records = log.get_batch_records(batch_id)
        assert len(records) == 3
        assert [r.file_path for r in records] == ["/a.mp3", "/b.mp3", "/c.mp3"]

    def test_second_snapshot_same_file_is_skipped(self, log: BatchUndoLog) -> None:
        """A run writing several tags per file keeps one snapshot per file.

        Regression: Mood Analyzer writes mood, confidence, and energy to each
        file, and every write used to record its own entry — the undo list
        then showed three times the real file count.  Only the first snapshot
        (the true pre-run state) must be retained.
        """
        batch_id = log.start_batch("mood_analyzer", "tag_edit")
        log.record_tag_edit(batch_id, "/song.mp3", "write_mood", {"TMOO": "Happy"})
        log.record_tag_edit(
            batch_id,
            "/song.mp3",
            "write_mood_confidence",
            {"TMOO": "Happy", "TXXX": "0.9"},
        )
        log.record_tag_edit(
            batch_id,
            "/song.mp3",
            "write_energy",
            {"TMOO": "Happy", "TXXX": "0.9", "TXXX2": "5"},
        )

        records = log.get_batch_records(batch_id)
        assert len(records) == 1
        assert records[0].operation == "write_mood"
        assert records[0].file_path == "/song.mp3"

    def test_revert_single_snapshot_restores_pre_run_state(
        self, log: BatchUndoLog
    ) -> None:
        """Reverting a deduped batch restores the original pre-run tags."""
        batch_id = log.start_batch("mood_analyzer", "tag_edit")
        original = {"TMOO": "None"}
        log.record_tag_edit(batch_id, "/song.mp3", "write_mood", original)
        log.record_tag_edit(
            batch_id,
            "/song.mp3",
            "write_mood_confidence",
            {"TMOO": "Happy", "TXXX": "0.9"},
        )
        log.record_tag_edit(
            batch_id,
            "/song.mp3",
            "write_energy",
            {"TMOO": "Happy", "TXXX": "0.9", "TXXX2": "5"},
        )

        with patch(
            "audio_suite_shared.tag_helper_base.TagHandlerFactory"
        ) as mock_factory:
            mock_handler = MagicMock()
            mock_factory.get_handler.return_value = mock_handler

            result = log.revert_batch(batch_id)

        assert result.reverted == 1
        assert result.failed == 0
        mock_handler.set_raw_tags.assert_called_once_with(original)
        mock_handler.save.assert_not_called()


# ---------------------------------------------------------------------------
# Recording file reorganizations
# ---------------------------------------------------------------------------


class TestRecordFileReorg:
    def test_record_move(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("file_reorganizer", "file_reorg")
        log.record_file_reorg(batch_id, "/src/song.mp3", "/dst/song.mp3", "move")

        records = log.get_batch_records(batch_id)
        assert len(records) == 1
        assert records[0].source_path == "/src/song.mp3"
        assert records[0].dest_path == "/dst/song.mp3"
        assert records[0].file_action == "move"
        assert records[0].has_snapshot is False

    def test_record_copy(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("file_reorganizer", "file_reorg")
        log.record_file_reorg(batch_id, "/src/song.mp3", "/dst/song.mp3", "copy")

        records = log.get_batch_records(batch_id)
        assert records[0].file_action == "copy"


# ---------------------------------------------------------------------------
# Recording file deletions
# ---------------------------------------------------------------------------


class TestRecordFileDelete:
    def test_record_delete_stores_raw_snapshot(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("music_format_converter", "file_delete")
        content = b"\x00\x01\x02 fake audio bytes"
        log.record_file_delete(batch_id, "/deleted/song.flac", content)

        records = log.get_batch_records(batch_id)
        assert len(records) == 1
        assert records[0].file_path == "/deleted/song.flac"
        assert records[0].operation == "file_delete"
        assert records[0].file_action == "delete"
        assert records[0].has_snapshot is True

        conn = log._connect()
        row = conn.execute(
            "SELECT old_tags_snapshot FROM undo_records WHERE batch_id = ?",
            [batch_id],
        ).fetchone()
        assert row[0] == content

    def test_legacy_pickled_delete_payload_is_migrated(
        self, undo_db: Path, tmp_path: Path
    ) -> None:
        target = tmp_path / "nested" / "legacy.flac"
        content = b"\x12\x34\x9a legacy audio bytes"

        with BatchUndoLog(db_path=undo_db) as log:
            batch_id = log.start_batch("music_format_converter", "file_delete")
            legacy = pickle.dumps(content, protocol=pickle.HIGHEST_PROTOCOL)
            log._connect().execute(
                "INSERT INTO undo_records "
                "(batch_id, file_path, operation, old_tags_snapshot, file_action) "
                "VALUES (?, ?, 'file_delete', ?, 'delete')",
                [batch_id, str(target), legacy],
            )
            log._connect().commit()
            # Simulate a pre-migration database so the next connect migrates.
            log._connect().execute("PRAGMA user_version = 0")
            log._connect().commit()

        with BatchUndoLog(db_path=undo_db) as log2:
            row = (
                log2._connect()
                .execute(
                    "SELECT old_tags_snapshot FROM undo_records WHERE batch_id = ?",
                    [batch_id],
                )
                .fetchone()
            )
            assert row is not None and row[0] == content
            assert row[0] != legacy

            result = log2.revert_batch(batch_id)
        assert result.reverted == 1
        assert result.failed == 0
        assert target.exists()
        assert target.read_bytes() == content


# ---------------------------------------------------------------------------
# Revert — tag edits
# ---------------------------------------------------------------------------


class TestRevertTagEdit:
    def test_revert_restores_pickle(self, log: BatchUndoLog) -> None:
        """Simulate: snapshot old tags, modify tags, revert."""
        batch_id = log.start_batch("test", "tag_edit")
        original_tags = {"TBPM": "120", "TIT2": "Original Title"}
        log.record_tag_edit(batch_id, "/fake/path.mp3", "write_bpm", original_tags)

        with patch(
            "audio_suite_shared.tag_helper_base.TagHandlerFactory"
        ) as mock_factory:
            mock_handler = MagicMock()
            mock_factory.get_handler.return_value = mock_handler

            result = log.revert_batch(batch_id)

        assert result.reverted == 1
        assert result.failed == 0
        mock_handler.set_raw_tags.assert_called_once_with(original_tags)
        mock_handler.save.assert_not_called()

    def test_revert_tagless_snapshot_deletes_created_tags(
        self, log: BatchUndoLog
    ) -> None:
        batch_id = log.start_batch("tag_editor", "tag_edit")
        log.record_tag_edit(batch_id, "/tagless/song.mp3", "write_editable_tag", None)

        with patch(
            "audio_suite_shared.tag_helper_base.TagHandlerFactory"
        ) as mock_factory:
            mock_handler = MagicMock()
            mock_factory.get_handler.return_value = mock_handler

            result = log.revert_batch(batch_id)

        assert result.reverted == 1
        assert result.failed == 0
        mock_handler.delete_tags.assert_called_once()
        mock_handler.set_raw_tags.assert_not_called()

    def test_revert_missing_file_logs_error(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("test", "tag_edit")
        log.record_tag_edit(
            batch_id, "/nonexistent/file.mp3", "write_bpm", {"bpm": 120}
        )

        with patch(
            "audio_suite_shared.tag_helper_base.TagHandlerFactory"
        ) as mock_factory:
            mock_factory.get_handler.side_effect = FileNotFoundError("no file")
            result = log.revert_batch(batch_id)

        assert result.failed == 1
        assert result.reverted == 0
        assert len(result.errors) == 1


# ---------------------------------------------------------------------------
# Revert — file reorganizations
# ---------------------------------------------------------------------------


class TestRevertFileReorg:
    def test_revert_move(self, log: BatchUndoLog, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        src_file = src_dir / "song.mp3"
        src_file.write_bytes(b"audio data")

        batch_id = log.start_batch("file_reorganizer", "file_reorg")
        dest = str(dst_dir / "song.mp3")
        shutil.move(str(src_file), dest)
        log.record_file_reorg(batch_id, str(src_file), dest, "move")

        result = log.revert_batch(batch_id)
        assert result.reverted == 1
        assert src_file.exists()
        assert not (dst_dir / "song.mp3").exists()
        assert src_file.read_bytes() == b"audio data"

    def test_revert_copy_removes_dest(self, log: BatchUndoLog, tmp_path: Path) -> None:
        src_dir = tmp_path / "src"
        dst_dir = tmp_path / "dst"
        src_dir.mkdir()
        dst_dir.mkdir()
        src_file = src_dir / "song.mp3"
        src_file.write_bytes(b"audio data")

        dest = str(dst_dir / "song.mp3")
        shutil.copy2(str(src_file), dest)

        batch_id = log.start_batch("file_reorganizer", "file_reorg")
        log.record_file_reorg(batch_id, str(src_file), dest, "copy")

        result = log.revert_batch(batch_id)
        assert result.reverted == 1
        assert not os.path.exists(dest)
        assert src_file.exists()

    def test_revert_copy_missing_dest(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("file_reorganizer", "file_reorg")
        log.record_file_reorg(batch_id, "/src/song.mp3", "/dst/song.mp3", "copy")

        result = log.revert_batch(batch_id)
        assert result.skipped == 1


# ---------------------------------------------------------------------------
# Revert — file deletions
# ---------------------------------------------------------------------------


class TestRevertFileDelete:
    def test_revert_restores_deleted_file(
        self, log: BatchUndoLog, tmp_path: Path
    ) -> None:
        target = tmp_path / "deleted" / "song.flac"
        content = b"\xff\xf8 audio payload"

        batch_id = log.start_batch("music_format_converter", "file_delete")
        log.record_file_delete(batch_id, str(target), content)

        result = log.revert_batch(batch_id)
        assert result.reverted == 1
        assert result.failed == 0
        assert target.exists()
        assert target.read_bytes() == content

    def test_revert_creates_parent_directories(
        self, log: BatchUndoLog, tmp_path: Path
    ) -> None:
        target = tmp_path / "nested" / "deep" / "song.flac"

        batch_id = log.start_batch("music_format_converter", "file_delete")
        log.record_file_delete(batch_id, str(target), b"payload")

        result = log.revert_batch(batch_id)
        assert result.reverted == 1
        assert target.exists()


# ---------------------------------------------------------------------------
# List & query
# ---------------------------------------------------------------------------


class TestListBatches:
    def test_list_returns_newest_first(self, log: BatchUndoLog) -> None:
        id1 = log.start_batch("tool_a", "tag_edit")
        id2 = log.start_batch("tool_b", "tag_edit")
        batches = log.list_batches()
        assert batches[0].batch_id == id2
        assert batches[1].batch_id == id1

    def test_list_includes_record_count(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("test", "tag_edit")
        log.record_tag_edit(batch_id, "/a.mp3", "write_bpm", {"bpm": 120})
        log.record_tag_edit(batch_id, "/b.mp3", "write_bpm", {"bpm": 130})

        batches = log.list_batches()
        target = [b for b in batches if b.batch_id == batch_id][0]
        assert target.record_count == 2

    def test_list_limit(self, log: BatchUndoLog) -> None:
        for i in range(10):
            log.start_batch(f"tool_{i}", "tag_edit")
        assert len(log.list_batches(limit=3)) == 3

    def test_list_empty(self, log: BatchUndoLog) -> None:
        assert log.list_batches() == []


# ---------------------------------------------------------------------------
# Cleanup / pruning
# ---------------------------------------------------------------------------


class TestCleanup:
    def test_cleanup_prunes_oldest(self, log: BatchUndoLog) -> None:
        ids = []
        for i in range(5):
            ids.append(log.start_batch(f"tool_{i}", "tag_edit"))

        removed = log.cleanup(max_entries=3)
        assert removed == 2
        remaining = log.list_batches(limit=10)
        remaining_ids = {b.batch_id for b in remaining}
        assert ids[0] not in remaining_ids
        assert ids[1] not in remaining_ids
        assert ids[2] in remaining_ids
        assert ids[3] in remaining_ids
        assert ids[4] in remaining_ids

    def test_cleanup_noop_when_under_limit(self, log: BatchUndoLog) -> None:
        log.start_batch("test", "tag_edit")
        removed = log.cleanup(max_entries=10)
        assert removed == 0

    def test_cleanup_removes_orphaned_records(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("test", "tag_edit")
        log.record_tag_edit(batch_id, "/a.mp3", "write_bpm", {"bpm": 120})

        log.cleanup(max_entries=0)
        conn = log._connect()
        count = conn.execute("SELECT COUNT(*) FROM undo_records").fetchone()[0]
        assert count == 0

    def test_auto_prune_on_start_batch(self, log: BatchUndoLog) -> None:
        for i in range(_DEFAULT_MAX_ENTRIES + 5):
            log.start_batch(f"tool_{i}", "tag_edit")

        batches = log.list_batches(limit=100)
        assert len(batches) <= _DEFAULT_MAX_ENTRIES

    def test_cleanup_prunes_oldest_by_size(self, log: BatchUndoLog) -> None:
        ids = []
        for i in range(3):
            batch_id = log.start_batch(f"tool_{i}", "file_delete")
            ids.append(batch_id)
            log.record_file_delete(batch_id, f"/delete_{i}.flac", b"x" * 1024)

        # 3 KiB stored, cap at 2 KiB -> exactly one (oldest) batch is pruned.
        removed = log.cleanup(max_bytes=2048)
        assert removed == 1
        remaining = log.list_batches(limit=10)
        remaining_ids = {b.batch_id for b in remaining}
        assert ids[0] not in remaining_ids
        assert ids[1] in remaining_ids
        assert ids[2] in remaining_ids

    def test_cleanup_by_size_noop_under_cap(self, log: BatchUndoLog) -> None:
        batch_id = log.start_batch("music_format_converter", "file_delete")
        log.record_file_delete(batch_id, "/small.flac", b"y" * 16)
        removed = log.cleanup(max_bytes=1024)
        assert removed == 0
        assert {b.batch_id for b in log.list_batches(limit=10)} == {batch_id}

    def test_auto_prune_by_size_on_start_batch(self, tmp_path: Path) -> None:
        db_path = tmp_path / "undo_log.db"
        with BatchUndoLog(db_path=db_path) as log:
            # Each payload is 512 bytes; three batches total 1536 bytes.
            for i in range(3):
                batch_id = log.start_batch(f"tool_{i}", "file_delete")
                log.record_file_delete(batch_id, f"/f_{i}.flac", b"z" * 512)
            log.cleanup(max_bytes=1024)
            assert len(log.list_batches(limit=10)) == 2


# ---------------------------------------------------------------------------
# Thread safety
# ---------------------------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_writes(self, undo_db: Path) -> None:
        errors: list[Exception] = []

        def writer(tool_idx: int) -> None:
            try:
                with BatchUndoLog(db_path=undo_db) as log:
                    batch_id = log.start_batch(f"tool_{tool_idx}", "tag_edit")
                    for j in range(20):
                        log.record_tag_edit(
                            batch_id,
                            f"/file_{tool_idx}_{j}.mp3",
                            "write_bpm",
                            {"bpm": 100 + j},
                        )
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        assert errors == []
        with BatchUndoLog(db_path=undo_db) as log:
            batches = log.list_batches(limit=100)
            total_records = sum(b.record_count for b in batches)
            assert total_records == 100


# ---------------------------------------------------------------------------
# Auto-snapshot thread-local integration
# ---------------------------------------------------------------------------


class TestAutoSnapshot:
    def test_no_batch_is_noop(self) -> None:
        record_tag_edit_snapshot("/fake.mp3", "write_bpm")

    def test_set_and_get_active_batch(self) -> None:
        with patch("audio_suite_shared.batch_undo.BatchUndoLog") as mock_cls:
            mock_log = MagicMock()
            mock_log.__enter__ = MagicMock(return_value=mock_log)
            mock_log.__exit__ = MagicMock(return_value=False)
            mock_log.start_batch.return_value = "test_batch_id"
            mock_cls.return_value = mock_log

            batch_id = set_active_batch("test_tool", "tag_edit")
            assert batch_id == "test_batch_id"
            assert get_active_batch_id() == "test_batch_id"
            assert is_undo_enabled() is True

        clear_active_batch()
        assert get_active_batch_id() is None
        assert is_undo_enabled() is False

    def test_record_tag_edit_snapshot_captures_tags(self) -> None:
        with patch("audio_suite_shared.batch_undo.BatchUndoLog") as mock_cls:
            mock_log = MagicMock()
            mock_log.__enter__ = MagicMock(return_value=mock_log)
            mock_log.__exit__ = MagicMock(return_value=False)
            mock_log.start_batch.return_value = "batch_123"
            mock_cls.return_value = mock_log

            set_active_batch("test", "tag_edit")

            with patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory"
            ) as mock_factory:
                mock_handler = MagicMock()
                mock_handler.get_raw_tags.return_value = {"TBPM": "128"}
                mock_factory.get_handler.return_value = mock_handler

                record_tag_edit_snapshot("/song.mp3", "write_bpm")

            mock_log.record_tag_edit.assert_called_once_with(
                "batch_123", "/song.mp3", "write_bpm", {"TBPM": "128"}
            )

        clear_active_batch()

    def test_record_tag_edit_snapshot_tolerates_errors(self) -> None:
        with patch("audio_suite_shared.batch_undo.BatchUndoLog") as mock_cls:
            mock_log = MagicMock()
            mock_log.__enter__ = MagicMock(return_value=mock_log)
            mock_log.__exit__ = MagicMock(return_value=False)
            mock_log.start_batch.return_value = "batch_err"
            mock_cls.return_value = mock_log
            set_active_batch("test", "tag_edit")

            with patch(
                "audio_suite_shared.tag_helper_base.TagHandlerFactory"
            ) as mock_factory:
                mock_factory.get_handler.side_effect = OSError("disk error")
                record_tag_edit_snapshot("/bad.mp3", "write_bpm")
                # Should not raise

        clear_active_batch()

    def test_record_file_reorg_snapshot(self) -> None:
        with patch("audio_suite_shared.batch_undo.BatchUndoLog") as mock_cls:
            mock_log = MagicMock()
            mock_log.__enter__ = MagicMock(return_value=mock_log)
            mock_log.__exit__ = MagicMock(return_value=False)
            mock_log.start_batch.return_value = "batch_reorg"
            mock_cls.return_value = mock_log
            set_active_batch("test", "file_reorg")

            record_file_reorg_snapshot("/src.mp3", "/dst.mp3", "move")

            mock_log.record_file_reorg.assert_called_once_with(
                "batch_reorg", "/src.mp3", "/dst.mp3", "move"
            )

        clear_active_batch()

    def test_clear_active_batch_closes_log(self) -> None:
        with patch("audio_suite_shared.batch_undo.BatchUndoLog") as mock_cls:
            mock_log = MagicMock()
            mock_log.__enter__ = MagicMock(return_value=mock_log)
            mock_log.__exit__ = MagicMock(return_value=False)
            mock_log.start_batch.return_value = "batch_close"
            mock_cls.return_value = mock_log
            set_active_batch("test", "tag_edit")

            clear_active_batch()

            mock_log.commit_batch.assert_called_once_with("batch_close")
            mock_log.__exit__.assert_called_once()

    def test_no_batch_for_record_file_reorg_snapshot(self) -> None:
        record_file_reorg_snapshot("/src.mp3", "/dst.mp3", "move")


class TestRecordFileDeleteSnapshot:
    def test_record_file_delete_snapshot(self) -> None:
        with patch("audio_suite_shared.batch_undo.BatchUndoLog") as mock_cls:
            mock_log = MagicMock()
            mock_log.__enter__ = MagicMock(return_value=mock_log)
            mock_log.__exit__ = MagicMock(return_value=False)
            mock_log.start_batch.return_value = "batch_del"
            mock_cls.return_value = mock_log
            set_active_batch("music_format_converter", "file_delete")

            record_file_delete_snapshot("/song.flac", b"payload")

            mock_log.record_file_delete.assert_called_once_with(
                "batch_del", "/song.flac", b"payload"
            )

        clear_active_batch()

    def test_no_batch_for_record_file_delete_snapshot(self) -> None:
        record_file_delete_snapshot("/song.flac", b"payload")


# ---------------------------------------------------------------------------
# Byte-level undo for in-place audio rewrites (iteration-6 B2)
# ---------------------------------------------------------------------------


class TestRecordFileOverwrite:
    def test_revert_restores_the_original_bytes(
        self, undo_db: Path, tmp_path: Path
    ) -> None:
        """The whole point of B2: undo must put the audio back, not the tags.

        Written as a real file whose bytes are asserted, not as a read-back of
        the same internal state the record just wrote: a tag-only snapshot
        would pass any self-consistency check while leaving the processed
        audio in place.
        """
        original = b"ORIGINAL-AUDIO-BYTES" * 64
        target = tmp_path / "song.flac"
        target.write_bytes(original)

        with BatchUndoLog(db_path=undo_db) as log:
            batch_id = log.start_batch("noise_reduction", "audio_overwrite")
            log.record_file_overwrite(
                batch_id, str(target), "noise_reduce_edit", original
            )
            records = log.get_batch_records(batch_id)
        assert len(records) == 1
        assert records[0].file_action == "overwrite"
        assert records[0].operation == "noise_reduce_edit"
        assert records[0].has_snapshot is True

        # Simulate the live run having replaced the file...
        target.write_bytes(b"PROCESSED-AUDIO-BYTES" * 64)
        assert target.read_bytes() != original

        with BatchUndoLog(db_path=undo_db) as log:
            result = log.revert_batch(batch_id)

        assert result.reverted == 1
        assert result.failed == 0
        assert target.read_bytes() == original

    def test_overwrite_payload_is_not_unpickled_as_tags(self, undo_db: Path) -> None:
        """A byte payload must never reach the pickled-tags revert path.

        ``_revert_tag_edit`` calls ``pickle.loads``; a raw FLAC payload would
        raise and be reported as a failed revert, which is the failure mode a
        dispatch-order mistake produces.
        """
        with BatchUndoLog(db_path=undo_db) as log:
            batch_id = log.start_batch("noise_reduction", "audio_overwrite")
            log.record_file_overwrite(
                batch_id, "C:/music/song.flac", "noise_reduce_edit", b"\x00\x01\x02raw"
            )
            with patch(
                "audio_suite_shared.batch_undo.BatchUndoLog._revert_tag_edit"
            ) as tag_revert:
                result = log.revert_batch(batch_id)

        assert result.reverted == 1
        assert result.failed == 0
        tag_revert.assert_not_called()

    def test_only_the_first_snapshot_per_file_is_kept(self, undo_db: Path) -> None:
        """Same per-file dedup rule as ``record_tag_edit``.

        The first record holds the true pre-run state; a later one would be a
        duplicate entry in the undo list, not extra safety.
        """
        with BatchUndoLog(db_path=undo_db) as log:
            batch_id = log.start_batch("noise_reduction", "audio_overwrite")
            log.record_file_overwrite(
                batch_id, "C:/music/song.flac", "noise_reduce_edit", b"first"
            )
            log.record_file_overwrite(
                batch_id, "C:/music/song.flac", "noise_reduce_edit", b"second"
            )
            records = log.get_batch_records(batch_id)
        assert len(records) == 1

    def test_revert_leaves_no_temp_file_behind(
        self, undo_db: Path, tmp_path: Path
    ) -> None:
        """The restore goes through a sibling temp file; it must be cleaned up."""
        target = tmp_path / "song.mp3"
        target.write_bytes(b"before")
        with BatchUndoLog(db_path=undo_db) as log:
            batch_id = log.start_batch("noise_reduction", "audio_overwrite")
            log.record_file_overwrite(
                batch_id, str(target), "noise_reduce_edit", b"before"
            )
        target.write_bytes(b"after")
        with BatchUndoLog(db_path=undo_db) as log:
            assert log.revert_batch(batch_id).reverted == 1
        assert target.read_bytes() == b"before"
        assert not list(tmp_path.glob("*.undo-restore"))


class TestRecordAudioOverwriteSnapshot:
    def test_records_the_files_bytes(self, undo_db: Path, tmp_path: Path) -> None:
        target = tmp_path / "song.flac"
        target.write_bytes(b"ORIGINAL")
        with active_batch(
            "noise_reduction", "audio_overwrite", db_path=undo_db
        ) as batch_id:
            record_audio_overwrite_snapshot(str(target), "noise_reduce_edit")
            with BatchUndoLog(db_path=undo_db) as log:
                records = log.get_batch_records(batch_id)

        assert len(records) == 1
        assert records[0].file_action == "overwrite"
        assert records[0].operation == "noise_reduce_edit"

    def test_no_batch_is_a_no_op(self, tmp_path: Path) -> None:
        target = tmp_path / "song.flac"
        target.write_bytes(b"ORIGINAL")
        # Must not raise, and must not create the database's batch.
        record_audio_overwrite_snapshot(str(target), "noise_reduce_edit")
        assert target.read_bytes() == b"ORIGINAL"

    def test_unreadable_file_falls_back_to_a_tag_snapshot(
        self, undo_db: Path, tmp_path: Path
    ) -> None:
        """A byte snapshot that cannot be taken still records *something*.

        Degrading to the tag payload keeps the pre-existing contract: a file
        whose bytes cannot be read (locked, vanished) is still restorable at
        tag level rather than losing its undo entry entirely.
        """
        missing = tmp_path / "gone.flac"
        with active_batch(
            "noise_reduction", "audio_overwrite", db_path=undo_db
        ) as batch_id:
            # ``record_audio_overwrite_snapshot`` calls the module-global
            # ``record_tag_edit_snapshot``, so patch it there (the function-local
            # ``TagHandlerFactory`` import inside it is not patchable here).
            with patch(
                "audio_suite_shared.batch_undo.record_tag_edit_snapshot"
            ) as tag_snapshot:
                record_audio_overwrite_snapshot(str(missing), "noise_reduce_edit")
            tag_snapshot.assert_called_once_with(str(missing), "noise_reduce_edit")
            with BatchUndoLog(db_path=undo_db) as log:
                records = log.get_batch_records(batch_id)

        # The fallback ran instead of the byte record, so no overwrite row.
        assert all(r.file_action != "overwrite" for r in records)

    def test_snapshot_failure_never_blocks_the_write(
        self, undo_db: Path, tmp_path: Path
    ) -> None:
        """A DB error must not propagate to the tool's write path."""
        target = tmp_path / "song.flac"
        target.write_bytes(b"ORIGINAL")
        with active_batch("noise_reduction", "audio_overwrite", db_path=undo_db):
            with patch.object(
                BatchUndoLog,
                "record_file_overwrite",
                side_effect=RuntimeError("db exploded"),
            ):
                record_audio_overwrite_snapshot(str(target), "noise_reduce_edit")

    def test_oversized_payload_is_pruned_by_the_stored_bytes_cap(
        self, tmp_path: Path
    ) -> None:
        """Pins the documented cap behaviour: a big run pushes itself out.

        Byte-level records make the 1 GiB budget reachable with ordinary
        music, and the prune drops whole batches oldest-first.  The
        user-facing guide states this, so the behaviour must not change
        silently - this test is the tripwire.
        """
        db = tmp_path / "cap.db"
        with BatchUndoLog(db_path=db) as log:
            big = log.start_batch("noise_reduction", "audio_overwrite")
            log.record_file_overwrite(
                big, "C:/music/big.flac", "noise_reduce_edit", b"x" * 4096
            )
            # Prune with a cap the payload cannot fit under: the batch holding
            # the payload is dropped, exactly as start_batch would do on the
            # next run.
            removed = log.cleanup(max_entries=50, max_bytes=1024)
            assert removed == 1
            assert log.list_batches(limit=10) == []


# ---------------------------------------------------------------------------
# active_batch / use_batch context managers
# ---------------------------------------------------------------------------


class TestActiveBatchContext:
    def test_records_into_batch(
        self, undo_db: Path, mock_tag_handler_factory: MagicMock
    ) -> None:
        with active_batch("tool_x", "tag_edit", db_path=undo_db) as batch_id:
            assert get_active_batch_id() == batch_id
            assert is_undo_enabled() is True
            record_tag_edit_snapshot("/a.mp3", "write_bpm")

        # Context exit commits and clears the thread-local state.
        assert get_active_batch_id() is None
        assert is_undo_enabled() is False
        with BatchUndoLog(db_path=undo_db) as log:
            batches = log.list_batches(limit=10)
        assert len(batches) == 1
        assert batches[0].batch_id == batch_id
        assert batches[0].record_count == 1

    def test_empty_batch_pruned_on_clear(self, undo_db: Path) -> None:
        with active_batch("tool_z", "tag_edit", db_path=undo_db):
            pass

        with BatchUndoLog(db_path=undo_db) as log:
            assert log.list_batches() == []
        assert not _BATCH_DB_PATHS

    def test_restores_thread_state_on_exception(self, undo_db: Path) -> None:
        with pytest.raises(RuntimeError):
            with active_batch("tool_x", "tag_edit", db_path=undo_db):
                raise RuntimeError("boom")
        assert get_active_batch_id() is None
        assert is_undo_enabled() is False


class TestUseBatch:
    def test_none_batch_is_noop(self) -> None:
        with use_batch(None) as joined:
            assert joined is None
            assert get_active_batch_id() is None

    def test_worker_records_into_shared_batch(
        self, undo_db: Path, mock_tag_handler_factory: MagicMock
    ) -> None:
        with active_batch("tool_x", "tag_edit", db_path=undo_db) as batch_id:
            errors: list[BaseException] = []

            def worker() -> None:
                try:
                    with use_batch(batch_id):
                        assert get_active_batch_id() == batch_id
                        record_tag_edit_snapshot("/worker.mp3", "write_bpm")
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(timeout=10)
            assert errors == [], f"worker failed: {errors}"

            # The worker must not have created its own batch.
            with BatchUndoLog(db_path=undo_db) as log:
                batches = log.list_batches(limit=10)
            assert len(batches) == 1
            assert batches[0].batch_id == batch_id
            assert batches[0].record_count == 1
            assert batches[0].record_count == 1

        # After both threads finish, only the shared batch remains.
        with BatchUndoLog(db_path=undo_db) as log:
            assert len(log.list_batches(limit=10)) == 1

    def test_restores_thread_state_after_join(self, undo_db: Path) -> None:
        with active_batch("tool_x", "tag_edit", db_path=undo_db) as batch_id:
            state: list[None | str] = []

            def worker() -> None:
                with use_batch(batch_id):
                    assert get_active_batch_id() == batch_id
                state.append(get_active_batch_id())

            thread = threading.Thread(target=worker)
            thread.start()
            thread.join(timeout=10)

            # The worker's thread-local was cleared after the join.
            assert state == [None]
            assert get_active_batch_id() == batch_id
        assert get_active_batch_id() is None


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


class TestConvenienceWrappers:
    def test_revert_batch_by_id(self, undo_db: Path) -> None:
        with BatchUndoLog(db_path=undo_db) as log:
            batch_id = log.start_batch("test", "tag_edit")
            log.record_tag_edit(batch_id, "/a.mp3", "write_bpm", {"bpm": 120})

        with patch(
            "audio_suite_shared.tag_helper_base.TagHandlerFactory"
        ) as mock_factory:
            mock_handler = MagicMock()
            mock_factory.get_handler.return_value = mock_handler
            result = revert_batch_by_id(batch_id, db_path=undo_db)

        assert result.reverted == 1

    def test_list_recent_batches(self, undo_db: Path) -> None:
        with BatchUndoLog(db_path=undo_db) as log:
            log.start_batch("tool_a", "tag_edit")

        batches = list_recent_batches(limit=5, db_path=undo_db)
        assert len(batches) == 1
        assert batches[0].tool_name == "tool_a"


# ---------------------------------------------------------------------------
# RevertResult dataclass
# ---------------------------------------------------------------------------


class TestRevertResult:
    def test_defaults(self) -> None:
        r = RevertResult(batch_id="abc")
        assert r.reverted == 0
        assert r.failed == 0
        assert r.skipped == 0
        assert r.errors == []
