"""
Tests for audio_suite_shared.error_logger  (updated for current API)

ErrorLogger is now a thin stdlib-logging wrapper.  Stale attributes
(.logger, .logs_dir, ._root) were removed in a refactor; these tests
target the *current* public API.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from audio_suite_shared.error_logger import ErrorLogger, cleanup_logs, get_logger

# ── Initialisation ────────────────────────────────────────────────────────────


class TestErrorLoggerInitialization:
    def test_program_name_stored(self):
        logger = ErrorLogger("TestProgram")
        assert logger.program_name == "TestProgram"

    def test_backing_stdlib_logger_exists(self):
        logger = ErrorLogger("TestInit")
        assert isinstance(logger._log, logging.Logger)

    def test_stdlib_logger_name_uses_namespace(self):
        logger = ErrorLogger("my_tool")
        assert "audio_suite" in logger._log.name
        assert "my_tool" in logger._log.name

    def test_two_loggers_different_names_have_different_stdlib_loggers(self):
        la = ErrorLogger("tool_a")
        lb = ErrorLogger("tool_b")
        assert la._log.name != lb._log.name


# ── set_root (no-op compat) ───────────────────────────────────────────────────


class TestSetRoot:
    def test_set_root_does_not_raise(self):
        logger = ErrorLogger("TestProgram")
        logger.set_root(MagicMock())  # must not raise

    def test_set_root_accepts_none(self):
        logger = ErrorLogger("TestProgram")
        logger.set_root(None)  # must not raise


# ── log_error ─────────────────────────────────────────────────────────────────


class TestLogError:
    def test_log_error_calls_stdlib_error(self):
        logger = ErrorLogger("TestProgram")
        with patch.object(logger._log, "error") as mock_err:
            logger.log_error("IOError", "file not found")
            mock_err.assert_called_once()

    def test_log_error_includes_error_type_in_message(self):
        logger = ErrorLogger("TestProgram")
        messages = []
        with patch.object(
            logger._log, "error", side_effect=lambda m, **kw: messages.append(m)
        ):
            logger.log_error("PermissionError", "cannot write")
        # Legacy string labels are mapped to the AudioSuiteError class name.
        assert any("AudioPermissionError" in m for m in messages)

    def test_log_error_unknown_type_passes_through(self):
        logger = ErrorLogger("TestProgram")
        messages = []
        with patch.object(
            logger._log, "error", side_effect=lambda m, **kw: messages.append(m)
        ):
            logger.log_error("TestError", "something failed")
        assert any("[TestError]" in m for m in messages)

    def test_log_error_includes_message_text(self):
        logger = ErrorLogger("TestProgram")
        messages = []
        with patch.object(
            logger._log, "error", side_effect=lambda m, **kw: messages.append(m)
        ):
            logger.log_error("IOError", "disk_full_sentinel_value")
        assert any("disk_full_sentinel_value" in m for m in messages)

    def test_log_error_with_context_appends_context(self):
        logger = ErrorLogger("TestProgram")
        messages = []
        with patch.object(
            logger._log, "error", side_effect=lambda m, **kw: messages.append(m)
        ):
            logger.log_error("IOError", "failed", context={"file": "/music/track.mp3"})
        combined = " ".join(messages)
        assert "/music/track.mp3" in combined

    def test_log_error_with_include_traceback_passes_exc_info(self):
        logger = ErrorLogger("TestProgram")
        calls = []
        with patch.object(
            logger._log, "error", side_effect=lambda m, **kw: calls.append(kw)
        ):
            logger.log_error("IOError", "fail", include_traceback=True)
        assert calls[0].get("exc_info") is True

    def test_log_error_without_traceback_does_not_set_exc_info(self):
        logger = ErrorLogger("TestProgram")
        calls = []
        with patch.object(
            logger._log, "error", side_effect=lambda m, **kw: calls.append(kw)
        ):
            logger.log_error("IOError", "fail", include_traceback=False)
        assert not calls[0].get("exc_info")

    def test_auto_traceback_attached_inside_except_block(self):
        logger = ErrorLogger("TestProgram")
        calls = []
        with patch.object(
            logger._log, "error", side_effect=lambda m, **kw: calls.append(kw)
        ):
            try:
                raise ValueError("active exception sentinel")
            except ValueError:
                logger.log_error("IOError", "fail")
        assert calls[0].get("exc_info") is True

    def test_explicit_false_suppresses_traceback_inside_except_block(self):
        logger = ErrorLogger("TestProgram")
        calls = []
        with patch.object(
            logger._log, "error", side_effect=lambda m, **kw: calls.append(kw)
        ):
            try:
                raise ValueError("suppressed sentinel")
            except ValueError:
                logger.log_error("IOError", "fail", include_traceback=False)
        assert not calls[0].get("exc_info")

    def test_no_active_exception_defaults_to_no_traceback(self):
        logger = ErrorLogger("TestProgram")
        calls = []
        with patch.object(
            logger._log, "error", side_effect=lambda m, **kw: calls.append(kw)
        ):
            logger.log_error("IOError", "fail")
        assert not calls[0].get("exc_info")


# ── log_and_show_error ────────────────────────────────────────────────────────


class TestLogAndShowError:
    def test_convenience_method_calls_log_error(self):
        logger = ErrorLogger("TestProgram")
        with patch.object(logger, "log_error") as mock:
            logger.log_and_show_error("IOError", "msg")
            mock.assert_called_once()

    def test_convenience_method_passes_context(self):
        logger = ErrorLogger("TestProgram")
        with patch.object(logger, "log_error") as mock:
            logger.log_and_show_error("IOError", "msg", context={"k": "v"})
            _, kwargs = mock.call_args
            assert kwargs.get("context") == {"k": "v"}


# ── log_info / log_warning / log_debug ───────────────────────────────────────


class TestLogInfo:
    def test_calls_stdlib_info(self):
        logger = ErrorLogger("TestProgram")
        with patch.object(logger._log, "info") as mock:
            logger.log_info("starting up")
            mock.assert_called_once_with("starting up")


class TestLogWarning:
    def test_calls_stdlib_warning(self):
        logger = ErrorLogger("TestProgram")
        with patch.object(logger._log, "warning") as mock:
            logger.log_warning("low disk space")
            mock.assert_called_once_with("low disk space")


class TestLogDebug:
    def test_calls_stdlib_debug(self):
        logger = ErrorLogger("TestProgram")
        with patch.object(logger._log, "debug") as mock:
            logger.log_debug("debug detail")
            mock.assert_called_once_with("debug detail")


# ── get_log_stats ─────────────────────────────────────────────────────────────


class TestGetLogStats:
    def test_returns_dict(self):
        logger = ErrorLogger("TestProgram")
        stats = logger.get_log_stats()
        assert isinstance(stats, dict)

    def test_has_required_keys(self):
        logger = ErrorLogger("TestProgram")
        stats = logger.get_log_stats()
        assert "total" in stats
        assert "by_type" in stats
        assert "log_files" in stats


# ── cleanup_logs (no-op compat) ───────────────────────────────────────────────


class TestCleanupLogs:
    def test_does_not_raise(self):
        cleanup_logs()  # must not raise

    def test_accepts_max_files_and_max_age(self):
        cleanup_logs(max_files_per_program=10, max_age_days=7)


# ── get_logger ────────────────────────────────────────────────────────────────


class TestGetLogger:
    def test_returns_error_logger_instance(self):
        logger = get_logger("bpm_analyzer")
        assert isinstance(logger, ErrorLogger)

    def test_program_name_set_correctly(self):
        logger = get_logger("genre_sync")
        assert logger.program_name == "genre_sync"

    def test_different_names_produce_different_loggers(self):
        la = get_logger("tool_a")
        lb = get_logger("tool_b")
        assert la._log.name != lb._log.name


# ── Integration ───────────────────────────────────────────────────────────────


class TestIntegration:
    def test_full_log_cycle_does_not_raise(self):
        logger = get_logger("integration_test")
        logger.set_root(None)
        logger.log_info("info message")
        logger.log_warning("warning message")
        logger.log_error("TestError", "something failed", context={"key": "val"})
        logger.log_and_show_error("TestError", "show error")
        logger.log_debug("debug detail")
        stats = logger.get_log_stats()
        assert stats is not None
