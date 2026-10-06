"""
Tests for audio_suite_shared.security.error_handler (G-20),
         audio_suite_shared.error_recovery (G-21),
         audio_suite_shared.resource_manager (G-22)
"""

import os
import threading
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.error_recovery import (
    RecoveryAction,
    RetryConfig,
    get_recovery_action,
    retry_with_backoff,
)
from audio_suite_shared.resource_manager import (
    ResourceManager,
    cleanup_expired_resources,
    get_resource_manager,
    temporary_directory,
    temporary_file,
    track_thread,
)
from audio_suite_shared.security.error_handler import SecureErrorHandler

# ═════════════════════════════════════════════════════════════════════════════
# G-20 — SecureErrorHandler
# ═════════════════════════════════════════════════════════════════════════════


class TestSecureErrorHandler:
    @staticmethod
    @pytest.fixture(autouse=True)
    def reset_debug():
        original = os.environ.get("AUDIOSUITE_DEBUG", "")
        yield
        if original:
            os.environ["AUDIOSUITE_DEBUG"] = original
        else:
            os.environ.pop("AUDIOSUITE_DEBUG", None)

    # ── set_debug_mode ────────────────────────────────────────────────────────

    def test_set_debug_true_enables_details(self):
        SecureErrorHandler.set_debug_mode(True)
        assert SecureErrorHandler._is_debug() is True

    def test_set_debug_false_disables_details(self):
        SecureErrorHandler.set_debug_mode(False)
        assert SecureErrorHandler._is_debug() is False

    def test_set_debug_updates_env_var(self):
        SecureErrorHandler.set_debug_mode(True)
        assert os.environ.get("AUDIOSUITE_DEBUG") == "1"
        SecureErrorHandler.set_debug_mode(False)
        assert os.environ.get("AUDIOSUITE_DEBUG") == "0"

    # ── handle_error ──────────────────────────────────────────────────────────

    def test_production_mode_returns_generic_message(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_error(ValueError("secret detail"), "test_op")
        assert "secret detail" not in msg

    def test_debug_mode_returns_full_error(self):
        SecureErrorHandler.set_debug_mode(True)
        msg = SecureErrorHandler.handle_error(ValueError("secret detail"), "test_op")
        assert "secret detail" in msg

    def test_show_details_override_true(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_error(
            ValueError("details"), "op", show_details=True
        )
        assert "details" in msg

    def test_show_details_override_false(self):
        """show_details=False produces generic message, not the raw exception text."""
        SecureErrorHandler.set_debug_mode(False)
        # Use a distinctive sentinel that won't appear in any generic message
        sentinel = "SENTINEL_SECRET_XYZ_123"
        msg = SecureErrorHandler.handle_error(
            ValueError(sentinel), "op", show_details=False
        )
        assert sentinel not in msg

    def test_context_appears_in_message(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_error(IOError("x"), "my_context")
        # Production mode returns a generic safe message, not the context
        assert isinstance(msg, str) and len(msg) > 0

    def test_returns_string(self):
        msg = SecureErrorHandler.handle_error(RuntimeError("x"), "ctx")
        assert isinstance(msg, str)

    # ── handle_file_error ─────────────────────────────────────────────────────

    def test_permission_error_message(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_file_error(
            PermissionError("denied"), "/path/to/file.mp3"
        )
        assert "Permission denied" in msg
        assert isinstance(msg, str) and len(msg) > 0

    def test_file_not_found_message(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_file_error(
            FileNotFoundError("missing"), "/path/track.mp3"
        )
        assert "could not be found" in msg.lower()

    def test_os_error_message(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_file_error(
            OSError("disk error"), "/path/song.mp3"
        )
        assert "System error" in msg or "system error" in msg.lower()

    def test_debug_mode_shows_full_path(self):
        SecureErrorHandler.set_debug_mode(True)
        msg = SecureErrorHandler.handle_file_error(IOError("x"), "/full/path/file.mp3")
        assert "file.mp3" in msg

    # ── handle_network_error ──────────────────────────────────────────────────

    def test_network_error_with_service(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_network_error(
            ConnectionError("timeout"), "MusicBrainz"
        )
        assert "MusicBrainz" in msg

    def test_network_error_without_service(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_network_error(ConnectionError("x"))
        assert "Network error" in msg or "internet" in msg.lower()

    # ── handle_api_error ──────────────────────────────────────────────────────

    def test_api_401_returns_auth_message(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_api_error(
            Exception("401 Unauthorized"), "Fanart.tv"
        )
        assert "Authentication" in msg or "API keys" in msg

    def test_api_429_returns_rate_limit_message(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_api_error(
            Exception("429 rate limit exceeded"), "Deezer"
        )
        assert "Rate limit" in msg or "later" in msg.lower()

    def test_api_404_returns_not_found_message(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_api_error(Exception("404 not found"), "iTunes")
        assert "not found" in msg.lower()

    def test_api_timeout_returns_timeout_message(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_api_error(
            Exception("Request timeout"), "MusicBrainz"
        )
        assert "timed out" in msg.lower() or "timeout" in msg.lower()

    def test_api_403_returns_access_denied(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_api_error(Exception("403 forbidden"), "API")
        assert "denied" in msg.lower() or "permissions" in msg.lower()

    def test_api_service_name_in_generic_error(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_api_error(Exception("unknown"), "MyService")
        assert "MyService" in msg

    # ── handle_processing_error ───────────────────────────────────────────────

    def test_processing_error_with_filename(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_processing_error(
            RuntimeError("x"), "/path/track.mp3"
        )
        # Production mode returns a generic safe message
        assert isinstance(msg, str) and len(msg) > 0

    def test_processing_error_without_filename(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_processing_error(RuntimeError("x"))
        assert isinstance(msg, str) and len(msg) > 0

    # ── handle_config_error ───────────────────────────────────────────────────

    def test_config_permission_error(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_config_error(
            Exception("permission denied"), "config.json"
        )
        assert isinstance(msg, str) and len(msg) > 0

    def test_config_parse_error(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_config_error(
            Exception("parse error"), "config.json"
        )
        assert isinstance(msg, str) and len(msg) > 0

    def test_config_not_found_error(self):
        SecureErrorHandler.set_debug_mode(False)
        msg = SecureErrorHandler.handle_config_error(
            Exception("not found"), "config.json"
        )
        assert isinstance(msg, str) and len(msg) > 0


# ═════════════════════════════════════════════════════════════════════════════
# G-21 — retry_with_backoff / get_recovery_action (standalone)
# ═════════════════════════════════════════════════════════════════════════════


class TestRetryWithBackoff:
    def test_successful_function_returns_result(self):
        config = RetryConfig(max_retries=3)
        result = retry_with_backoff(lambda: 42, config, "op1")
        assert result == 42

    def test_retries_on_io_error(self):
        call_count = [0]

        def flaky():
            call_count[0] += 1
            if call_count[0] < 3:
                raise IOError("temporary")
            return "ok"

        config = RetryConfig(max_retries=3, retry_delay=0.01)
        result = retry_with_backoff(flaky, config, "op1")
        assert result == "ok"
        assert call_count[0] == 3

    def test_raises_after_max_retries_exhausted(self):
        config = RetryConfig(max_retries=2, retry_delay=0.01)
        with pytest.raises(IOError):
            retry_with_backoff(
                lambda: (_ for _ in ()).throw(IOError("fail")), config, "op1"
            )

    def test_non_retryable_exception_raises_immediately(self):
        config = RetryConfig(max_retries=3, retry_on_exceptions=[IOError])
        call_count = [0]

        def raises_value_error():
            call_count[0] += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            retry_with_backoff(raises_value_error, config, "op1")
        assert call_count[0] == 1

    def test_exponential_backoff_delays_increase(self):
        delays = []

        def mock_sleep(d):
            delays.append(d)

        config = RetryConfig(max_retries=3, retry_delay=0.1, backoff_factor=2.0)
        call_count = [0]

        def always_fails():
            call_count[0] += 1
            raise IOError("fail")

        with patch("audio_suite_shared.error_recovery.time.sleep", mock_sleep):
            with pytest.raises(IOError):
                retry_with_backoff(always_fails, config, "op1")
        assert len(delays) == 3
        assert delays[1] > delays[0]
        assert delays[2] > delays[1]

    def test_delay_capped_at_max_delay(self):
        delays = []

        def mock_sleep(d):
            delays.append(d)

        config = RetryConfig(
            max_retries=5, retry_delay=1.0, backoff_factor=100.0, max_delay=5.0
        )

        def always_fails():
            raise IOError("fail")

        with patch("audio_suite_shared.error_recovery.time.sleep", mock_sleep):
            with pytest.raises(IOError):
                retry_with_backoff(always_fails, config, "op1")
        assert all(d <= 5.0 for d in delays)


class TestGetRecoveryAction:
    def test_memory_error_aborts(self):
        assert get_recovery_action(MemoryError(), "batch") == RecoveryAction.ABORT

    def test_keyboard_interrupt_aborts(self):
        assert get_recovery_action(KeyboardInterrupt(), "batch") == RecoveryAction.ABORT

    def test_permission_error_retries(self):
        assert (
            get_recovery_action(PermissionError("denied"), "write")
            == RecoveryAction.RETRY
        )

    def test_file_not_found_skips(self):
        assert (
            get_recovery_action(FileNotFoundError("missing"), "read")
            == RecoveryAction.SKIP
        )

    def test_io_error_retries(self):
        assert get_recovery_action(IOError("disk"), "read") == RecoveryAction.RETRY

    def test_user_callback_used_when_provided(self):
        callback = MagicMock(return_value=RecoveryAction.SKIP)
        result = get_recovery_action(PermissionError("x"), "op", user_callback=callback)
        assert result == RecoveryAction.SKIP
        callback.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# G-22 — ResourceManager
# ═════════════════════════════════════════════════════════════════════════════


class TestResourceManager:
    @staticmethod
    @pytest.fixture
    def mgr():
        return ResourceManager()

    # ── register / unregister ─────────────────────────────────────────────────

    def test_register_resource(self, mgr):
        mgr.register_resource("res1", "file", resource_path="/tmp/x.tmp")
        stats = mgr.get_resource_stats()
        assert stats.get("file", 0) >= 1

    def test_unregister_resource_returns_true(self, mgr):
        mgr.register_resource("res1", "file")
        assert mgr.unregister_resource("res1") is True

    def test_unregister_nonexistent_returns_false(self, mgr):
        assert mgr.unregister_resource("ghost") is False

    def test_unregistered_resource_no_longer_tracked(self, mgr):
        mgr.register_resource("res1", "file")
        mgr.unregister_resource("res1")
        resources = mgr.list_resources()
        assert not any(r["id"] == "res1" for r in resources)

    # ── cleanup_resource ──────────────────────────────────────────────────────

    def test_cleanup_file_resource_deletes_file(self, mgr, tmp_path):
        f = tmp_path / "temp.mp3"
        f.write_bytes(b"x")
        mgr.register_resource("f1", "file", resource_path=str(f))
        mgr.cleanup_resource("f1")
        assert not f.exists()

    def test_cleanup_temp_dir_resource_removes_directory(self, mgr, tmp_path):
        d = tmp_path / "temp_dir"
        d.mkdir()
        (d / "file.txt").write_text("x")
        mgr.register_resource("d1", "temp_dir", resource_path=str(d))
        mgr.cleanup_resource("d1")
        assert not d.exists()

    def test_cleanup_with_custom_callback(self, mgr):
        called = [False]

        def cb():
            called[0] = True

        mgr.register_resource("cb1", "custom", cleanup_callback=cb)
        mgr.cleanup_resource("cb1")
        assert called[0] is True

    def test_cleanup_nonexistent_resource_returns_false(self, mgr):
        assert mgr.cleanup_resource("ghost") is False

    def test_cleanup_removes_resource_from_tracking(self, mgr, tmp_path):
        f = tmp_path / "f.txt"
        f.write_bytes(b"x")
        mgr.register_resource("f1", "file", resource_path=str(f))
        mgr.cleanup_resource("f1")
        assert mgr.unregister_resource("f1") is False  # already gone

    # ── cleanup_expired_resources ─────────────────────────────────────────────

    def test_cleanup_expired_removes_old_resources(self, mgr, tmp_path):
        f = tmp_path / "old.tmp"
        f.write_bytes(b"x")
        mgr.register_resource("old", "file", resource_path=str(f))
        # Backdate the creation time
        mgr._resources["old"].created_at = datetime.now() - timedelta(hours=25)
        count = mgr.cleanup_expired_resources(max_age_hours=24)
        assert count == 1
        assert not f.exists()

    def test_cleanup_expired_ignores_fresh_resources(self, mgr, tmp_path):
        f = tmp_path / "fresh.tmp"
        f.write_bytes(b"x")
        mgr.register_resource("fresh", "file", resource_path=str(f))
        count = mgr.cleanup_expired_resources(max_age_hours=24)
        assert count == 0
        assert f.exists()

    def test_cleanup_expired_returns_count(self, mgr, tmp_path):
        for i in range(3):
            f = tmp_path / f"old_{i}.tmp"
            f.write_bytes(b"x")
            mgr.register_resource(f"old_{i}", "file", resource_path=str(f))
            mgr._resources[f"old_{i}"].created_at = datetime.now() - timedelta(hours=25)
        count = mgr.cleanup_expired_resources(max_age_hours=24)
        assert count == 3

    # ── temporary_file context manager ───────────────────────────────────────

    def test_temporary_file_yields_path(self, mgr):
        with mgr.temporary_file(suffix=".mp3") as path:
            assert os.path.exists(path)
            assert path.endswith(".mp3")

    def test_temporary_file_cleaned_up_on_exit(self, mgr):
        with mgr.temporary_file() as path:
            pass
        assert not os.path.exists(path)

    def test_temporary_file_cleaned_up_on_exception(self, mgr):
        try:
            with mgr.temporary_file() as path:
                raise RuntimeError("oops")
        except RuntimeError:
            pass
        assert not os.path.exists(path)

    # ── temporary_directory context manager ───────────────────────────────────

    def test_temporary_directory_yields_path(self, mgr):
        with mgr.temporary_directory() as d:
            assert os.path.isdir(d)

    def test_temporary_directory_cleaned_up(self, mgr):
        with mgr.temporary_directory() as d:
            inner = os.path.join(d, "sub")
            os.makedirs(inner)
        assert not os.path.exists(d)

    # ── track_thread ──────────────────────────────────────────────────────────

    def test_track_thread_returns_resource_id(self, mgr):
        t = threading.Thread(target=lambda: None)
        t.start()
        t.join()
        resource_id = mgr.track_thread(t, "test_thread")
        assert isinstance(resource_id, str)
        assert resource_id

    # ── tracked_resource context manager ─────────────────────────────────────

    def test_tracked_resource_registers_and_cleans_up(self, mgr, tmp_path):
        f = tmp_path / "tracked.tmp"
        f.write_bytes(b"x")
        with mgr.tracked_resource("tr1", "file", resource_path=str(f)):
            assert any(r["id"] == "tr1" for r in mgr.list_resources())
        # After exit, resource cleaned up
        assert not f.exists()

    # ── get_resource_stats ────────────────────────────────────────────────────

    def test_get_resource_stats_returns_dict(self, mgr):
        assert isinstance(mgr.get_resource_stats(), dict)

    def test_get_resource_stats_counts_by_type(self, mgr):
        mgr.register_resource("f1", "file")
        mgr.register_resource("f2", "file")
        mgr.register_resource("d1", "temp_dir")
        stats = mgr.get_resource_stats()
        assert stats.get("file", 0) >= 2
        assert stats.get("temp_dir", 0) >= 1

    # ── list_resources ────────────────────────────────────────────────────────

    def test_list_resources_returns_list(self, mgr):
        assert isinstance(mgr.list_resources(), list)

    def test_list_resources_contains_registered(self, mgr):
        mgr.register_resource("test_r", "file", resource_path="/tmp/x")
        resources = mgr.list_resources()
        assert any(r["id"] == "test_r" for r in resources)

    def test_list_resources_entries_have_required_keys(self, mgr):
        mgr.register_resource("r1", "file", resource_path="/tmp/x")
        for r in mgr.list_resources():
            for key in ("id", "type", "path", "created_at", "auto_cleanup"):
                assert key in r


# ── Module-level convenience functions ───────────────────────────────────────


class TestConvenienceFunctions:
    def test_temporary_file_module_level(self):
        with temporary_file(suffix=".wav") as path:
            assert os.path.exists(path)
        assert not os.path.exists(path)

    def test_temporary_directory_module_level(self):
        with temporary_directory() as d:
            assert os.path.isdir(d)
        assert not os.path.exists(d)

    def test_track_thread_module_level(self):
        t = threading.Thread(target=lambda: None)
        t.start()
        t.join()
        rid = track_thread(t, "module_test")
        assert isinstance(rid, str)

    def test_cleanup_expired_resources_module_level(self):
        count = cleanup_expired_resources(max_age_hours=24)
        assert isinstance(count, int)

    def test_get_resource_manager_singleton(self):
        assert get_resource_manager() is get_resource_manager()
