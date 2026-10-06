"""
test_resource_manager.py — Unit tests for audio_suite_shared.resource_manager

Covers:
    • ResourceInfo dataclass defaults
    • ResourceManager.register_resource / unregister_resource
    • ResourceManager.cleanup_resource: success, missing, custom callback
    • ResourceManager._default_cleanup: file, temp_dir, thread resource types
    • ResourceManager.cleanup_all_resources and cleanup_expired_resources
    • Context managers: temporary_file, temporary_directory, tracked_resource
    • ResourceManager.track_thread and get_resource_stats / list_resources
    • Module-level convenience functions (temporary_file, temporary_directory,
      track_thread, cleanup_expired_resources, get_resource_stats)
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from audio_suite_shared.resource_manager import (
    ResourceInfo,
    ResourceManager,
    cleanup_expired_resources,
    get_resource_manager,
    get_resource_stats,
    temporary_directory,
    temporary_file,
    track_thread,
)

# ---------------------------------------------------------------------------
# ResourceInfo dataclass
# ---------------------------------------------------------------------------


class TestResourceInfo:
    """Tests for the ResourceInfo dataclass."""

    def test_created_at_set_automatically(self) -> None:
        """created_at must be populated automatically by __post_init__."""
        info = ResourceInfo(resource_id="r1", resource_type="file")
        assert info.created_at is not None

    def test_defaults(self) -> None:
        info = ResourceInfo(resource_id="r2", resource_type="thread")
        assert info.resource_path is None
        assert info.cleanup_callback is None
        assert info.auto_cleanup is True


# ---------------------------------------------------------------------------
# ResourceManager register / unregister
# ---------------------------------------------------------------------------


class TestResourceManagerRegistration:
    """Tests for register_resource and unregister_resource."""

    @staticmethod
    @pytest.fixture()
    def mgr() -> ResourceManager:
        return ResourceManager()

    def test_register_adds_resource(self, mgr: ResourceManager) -> None:
        mgr.register_resource("r1", "file", resource_path="/tmp/test.wav")
        stats = mgr.get_resource_stats()
        assert stats.get("file", 0) >= 1

    def test_unregister_removes_resource(self, mgr: ResourceManager) -> None:
        mgr.register_resource("r_remove", "file")
        result = mgr.unregister_resource("r_remove")
        assert result is True
        # Should no longer appear in listing
        ids = [r["id"] for r in mgr.list_resources()]
        assert "r_remove" not in ids

    def test_unregister_nonexistent_returns_false(self, mgr: ResourceManager) -> None:
        assert mgr.unregister_resource("does_not_exist") is False

    def test_register_multiple_types(self, mgr: ResourceManager) -> None:
        mgr.register_resource("f1", "file")
        mgr.register_resource("t1", "thread")
        mgr.register_resource("d1", "temp_dir")
        stats = mgr.get_resource_stats()
        assert "file" in stats
        assert "thread" in stats
        assert "temp_dir" in stats


# ---------------------------------------------------------------------------
# ResourceManager cleanup_resource
# ---------------------------------------------------------------------------


class TestCleanupResource:
    """Tests for cleanup_resource and _default_cleanup."""

    @staticmethod
    @pytest.fixture()
    def mgr() -> ResourceManager:
        return ResourceManager()

    def test_cleanup_missing_resource_returns_false(self, mgr: ResourceManager) -> None:
        assert mgr.cleanup_resource("ghost") is False

    def test_custom_callback_invoked(self, mgr: ResourceManager) -> None:
        callback = MagicMock()
        mgr.register_resource("cb_res", "file", cleanup_callback=callback)
        result = mgr.cleanup_resource("cb_res")
        assert result is True
        callback.assert_called_once()

    def test_file_cleanup_removes_file(
        self, mgr: ResourceManager, tmp_path: Path
    ) -> None:
        """Default cleanup for type='file' must delete the file from disk."""
        test_file = tmp_path / "to_delete.wav"
        test_file.write_bytes(b"data")
        mgr.register_resource("del_file", "file", resource_path=str(test_file))
        mgr.cleanup_resource("del_file")
        assert not test_file.exists()

    def test_temp_dir_cleanup_removes_directory(
        self, mgr: ResourceManager, tmp_path: Path
    ) -> None:
        """Default cleanup for type='temp_dir' must remove the directory."""
        temp_dir = tmp_path / "subdir"
        temp_dir.mkdir()
        (temp_dir / "file.txt").write_text("x")
        mgr.register_resource("del_dir", "temp_dir", resource_path=str(temp_dir))
        mgr.cleanup_resource("del_dir")
        assert not temp_dir.exists()

    def test_cleanup_removes_resource_from_tracking(self, mgr: ResourceManager) -> None:
        mgr.register_resource("track_me", "file")
        mgr.cleanup_resource("track_me")
        ids = [r["id"] for r in mgr.list_resources()]
        assert "track_me" not in ids


# ---------------------------------------------------------------------------
# cleanup_all_resources and cleanup_expired_resources
# ---------------------------------------------------------------------------


class TestBulkCleanup:
    """Tests for bulk cleanup operations."""

    @staticmethod
    @pytest.fixture()
    def mgr() -> ResourceManager:
        return ResourceManager()

    def test_cleanup_all_calls_auto_cleanup_resources(
        self, mgr: ResourceManager, tmp_path: Path
    ) -> None:
        f = tmp_path / "bulk.wav"
        f.write_bytes(b"x")
        mgr.register_resource("bulk", "file", resource_path=str(f), auto_cleanup=True)
        mgr.cleanup_all_resources()
        assert not f.exists()

    def test_no_auto_cleanup_skipped(self, mgr: ResourceManager) -> None:
        """Resources with auto_cleanup=False must survive cleanup_all_resources."""
        mgr.register_resource("kept", "file", auto_cleanup=False)
        mgr.cleanup_all_resources()
        ids = [r["id"] for r in mgr.list_resources()]
        assert "kept" in ids

    def test_cleanup_expired_removes_old_resources(self, mgr: ResourceManager) -> None:
        """Resources with created_at older than max_age_hours must be cleaned up."""
        from datetime import datetime, timedelta

        mgr.register_resource("old_res", "file", auto_cleanup=True)
        # Backdate created_at to 48 hours ago
        with mgr._lock:
            mgr._resources["old_res"].created_at = datetime.now() - timedelta(hours=48)

        count = mgr.cleanup_expired_resources(max_age_hours=24)
        assert count >= 1

    def test_cleanup_expired_leaves_new_resources(self, mgr: ResourceManager) -> None:
        """Recently registered resources must survive cleanup_expired_resources."""
        mgr.register_resource("new_res", "file", auto_cleanup=True)
        mgr.cleanup_expired_resources(max_age_hours=24)
        ids = [r["id"] for r in mgr.list_resources()]
        assert "new_res" in ids


# ---------------------------------------------------------------------------
# Context managers
# ---------------------------------------------------------------------------


class TestContextManagers:
    """Tests for temporary_file, temporary_directory, and tracked_resource."""

    @staticmethod
    @pytest.fixture()
    def mgr() -> ResourceManager:
        return ResourceManager()

    def test_temporary_file_exists_during_context(self, mgr: ResourceManager) -> None:
        with mgr.temporary_file(suffix=".wav") as path:
            assert os.path.exists(path)
            assert path.endswith(".wav")

    def test_temporary_file_deleted_after_context(self, mgr: ResourceManager) -> None:
        with mgr.temporary_file() as path:
            tmp = path
        assert not os.path.exists(tmp)

    def test_temporary_directory_exists_during_context(
        self, mgr: ResourceManager
    ) -> None:
        with mgr.temporary_directory() as path:
            assert os.path.isdir(path)

    def test_temporary_directory_deleted_after_context(
        self, mgr: ResourceManager
    ) -> None:
        with mgr.temporary_directory() as path:
            tmp = path
        assert not os.path.isdir(tmp)

    def test_tracked_resource_removed_after_context(self, mgr: ResourceManager) -> None:
        with mgr.tracked_resource("ctx_res", "file"):
            ids = [r["id"] for r in mgr.list_resources()]
            assert "ctx_res" in ids
        ids = [r["id"] for r in mgr.list_resources()]
        assert "ctx_res" not in ids


# ---------------------------------------------------------------------------
# Module-level convenience functions
# ---------------------------------------------------------------------------


class TestModuleLevelConvenience:
    """Tests for module-level temporary_file, temporary_directory, etc."""

    def test_module_temporary_file(self) -> None:
        with temporary_file(suffix=".tmp") as path:
            assert os.path.exists(path)
        assert not os.path.exists(path)

    def test_module_temporary_directory(self) -> None:
        with temporary_directory() as path:
            assert os.path.isdir(path)
        assert not os.path.isdir(path)

    def test_module_track_thread(self) -> None:
        t = threading.Thread(target=time.sleep, args=(0,))
        resource_id = track_thread(t)
        assert isinstance(resource_id, str)
        assert "thread" in resource_id

    def test_module_get_resource_stats_returns_dict(self) -> None:
        result = get_resource_stats()
        assert isinstance(result, dict)

    def test_module_cleanup_expired_resources_returns_int(self) -> None:
        result = cleanup_expired_resources(max_age_hours=1)
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# Subprocess resource cleanup
# ---------------------------------------------------------------------------


class TestSubprocessCleanup:
    """Tests for _default_cleanup with subprocess resource type."""

    @staticmethod
    @pytest.fixture()
    def mgr() -> ResourceManager:
        return ResourceManager()

    def test_subprocess_cleanup_returns_true_even_without_process_attr(
        self, mgr: ResourceManager
    ) -> None:
        """A subprocess resource without a 'process' attribute should not raise."""
        mgr.register_resource("sp_no_proc", "subprocess")
        result = mgr.cleanup_resource("sp_no_proc")
        assert result is True

    def test_subprocess_terminate_called(self, mgr: ResourceManager) -> None:
        mock_proc = MagicMock()
        mgr.register_resource("sp_term", "subprocess", resource_path="/dev/null")
        # Manually attach a process object for cleanup
        with mgr._lock:
            mgr._resources["sp_term"].process = mock_proc
        mgr.cleanup_resource("sp_term")
        mock_proc.terminate.assert_called_once()

    def test_subprocess_terminate_fallback_to_kill(self, mgr: ResourceManager) -> None:
        """When terminate raises, kill() must be attempted."""
        mock_proc = MagicMock()
        mock_proc.terminate.side_effect = OSError("terminate failed")
        mgr.register_resource("sp_kill", "subprocess", resource_path="/dev/null")
        with mgr._lock:
            mgr._resources["sp_kill"].process = mock_proc
        mgr.cleanup_resource("sp_kill")
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()

    def test_subprocess_cleanup_handles_timeout(self, mgr: ResourceManager) -> None:
        """TimeoutError during wait should fall back to kill."""
        mock_proc = MagicMock()
        mock_proc.wait.side_effect = TimeoutError("timed out")
        mgr.register_resource("sp_timeout", "subprocess", resource_path="/dev/null")
        with mgr._lock:
            mgr._resources["sp_timeout"].process = mock_proc
        mgr.cleanup_resource("sp_timeout")
        mock_proc.terminate.assert_called_once()
        mock_proc.kill.assert_called_once()

    def test_subprocess_without_process_attr_no_error(
        self, mgr: ResourceManager
    ) -> None:
        mgr.register_resource("sp_no_attr", "subprocess")
        # No 'process' attribute — must not raise or error
        result = mgr.cleanup_resource("sp_no_attr")
        assert result is True


# ---------------------------------------------------------------------------
# get_resource_manager singleton
# ---------------------------------------------------------------------------


class TestGetResourceManagerSingleton:
    """Tests for the module-level singleton accessor."""

    def test_returns_resource_manager_instance(self) -> None:
        mgr = get_resource_manager()
        assert isinstance(mgr, ResourceManager)

    def test_same_instance_on_repeated_calls(self) -> None:
        m1 = get_resource_manager()
        m2 = get_resource_manager()
        assert m1 is m2

    def test_list_resources_returns_list_of_dicts(self) -> None:
        mgr = get_resource_manager()
        result = mgr.list_resources()
        assert isinstance(result, list)
        for item in result:
            assert isinstance(item, dict)
            assert "id" in item
            assert "type" in item
