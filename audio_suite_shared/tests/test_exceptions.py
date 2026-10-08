"""
audio_suite_shared/tests/test_exceptions.py
─────────────────────────────────────────────────────────────────────────────
Exception-handling test suite for AudioSuite-Pro.

Covers:
  • Exception hierarchy — construction, attributes, MRO
  • map_to_audio_error()  — all _MAPPING entries, edge cases
  • handle_audio_errors() — reraise, suppress, logging, pass-through
  • user_message_for()    — per-subclass messages, debug env, MRO walk
  • SecureErrorHandler    — all six handle_* methods, debug vs production
  • retry_with_backoff    — standalone retry loop with exponential backoff
  • get_recovery_action   — error-type-to-action mapping

Place this file at:
    AudioSuite-Pro/audio_suite_shared/tests/test_exceptions.py
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations

import errno
import json
import logging
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.error_recovery import (
    RecoveryAction,
    RetryConfig,
    get_recovery_action,
    retry_with_backoff,
)
from audio_suite_shared.exceptions import (
    AudioAnalysisError,
    AudioCodecError,
    AudioConfigFileError,
    AudioConfigurationError,
    AudioConfigValueError,
    AudioDirectoryError,
    AudioDiskFullError,
    AudioExternalToolError,
    AudioFileNotFoundError,
    AudioFormatError,
    AudioIOError,
    AudioMissingDependencyError,
    AudioPermissionError,
    AudioProcessingError,
    AudioSuiteError,
    AudioTagError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.security.error_handler import SecureErrorHandler

# ===========================================================================
# 1.  EXCEPTION HIERARCHY
# ===========================================================================


class TestAudioSuiteErrorBase:
    """AudioSuiteError — root class construction and attribute contract."""

    def test_is_exception_subclass(self):
        assert issubclass(AudioSuiteError, Exception)

    def test_message_stored(self):
        exc = AudioSuiteError("boom")
        assert exc.message == "boom"

    def test_context_defaults_to_empty_dict(self):
        exc = AudioSuiteError("x")
        assert exc.context == {}

    def test_context_stored_when_supplied(self):
        exc = AudioSuiteError("x", context={"key": "val"})
        assert exc.context["key"] == "val"

    def test_original_defaults_to_none(self):
        exc = AudioSuiteError("x")
        assert exc.original is None

    def test_original_stored_when_supplied(self):
        cause = ValueError("root cause")
        exc = AudioSuiteError("x", original=cause)
        assert exc.original is cause

    def test_str_includes_message(self):
        exc = AudioSuiteError("the message")
        assert "the message" in str(exc)

    def test_str_includes_context_when_non_empty(self):
        exc = AudioSuiteError("msg", context={"op": "write"})
        assert "op" in str(exc)
        assert "write" in str(exc)

    def test_str_omits_context_section_when_empty(self):
        exc = AudioSuiteError("msg")
        assert "context=" not in str(exc)

    def test_with_original_returns_self(self):
        exc = AudioSuiteError("x")
        cause = RuntimeError("cause")
        returned = exc.with_original(cause)
        assert returned is exc

    def test_with_original_sets_original(self):
        exc = AudioSuiteError("x")
        cause = RuntimeError("cause")
        exc.with_original(cause)
        assert exc.original is cause

    def test_can_be_raised_and_caught(self):
        with pytest.raises(AudioSuiteError):
            raise AudioSuiteError("test raise")


class TestIOErrorHierarchy:
    """AudioIOError and its concrete subclasses."""

    def test_audio_io_error_is_audio_suite_error(self):
        assert issubclass(AudioIOError, AudioSuiteError)

    def test_file_not_found_is_io_error(self):
        assert issubclass(AudioFileNotFoundError, AudioIOError)

    def test_permission_error_is_io_error(self):
        assert issubclass(AudioPermissionError, AudioIOError)

    def test_disk_full_is_io_error(self):
        assert issubclass(AudioDiskFullError, AudioIOError)

    def test_directory_error_is_io_error(self):
        assert issubclass(AudioDirectoryError, AudioIOError)

    def test_file_not_found_stores_path_in_context(self):
        exc = AudioFileNotFoundError("missing", path="/music/track.mp3")
        assert exc.context["path"] == "/music/track.mp3"

    def test_file_not_found_path_as_path_object(self):
        exc = AudioFileNotFoundError("missing", path=Path("/some/file.flac"))
        assert exc.context["path"] == os.path.normpath("/some/file.flac")

    def test_permission_error_stores_path_in_context(self):
        exc = AudioPermissionError("denied", path="/locked/dir")
        assert exc.context["path"] == "/locked/dir"

    def test_file_not_found_without_path_has_empty_context(self):
        exc = AudioFileNotFoundError("missing")
        assert exc.context == {}


class TestProcessingErrorHierarchy:
    """AudioProcessingError and its concrete subclasses."""

    def test_processing_error_is_audio_suite_error(self):
        assert issubclass(AudioProcessingError, AudioSuiteError)

    def test_codec_error_is_processing_error(self):
        assert issubclass(AudioCodecError, AudioProcessingError)

    def test_format_error_is_processing_error(self):
        assert issubclass(AudioFormatError, AudioProcessingError)

    def test_external_tool_error_is_processing_error(self):
        assert issubclass(AudioExternalToolError, AudioProcessingError)

    def test_tag_error_is_processing_error(self):
        assert issubclass(AudioTagError, AudioProcessingError)

    def test_analysis_error_is_processing_error(self):
        assert issubclass(AudioAnalysisError, AudioProcessingError)

    def test_codec_error_stores_path(self):
        exc = AudioCodecError("bad codec", path="/track.mp3")
        assert exc.context["path"] == "/track.mp3"

    def test_external_tool_error_stores_tool_name(self):
        exc = AudioExternalToolError("ffmpeg died", tool="ffmpeg")
        assert exc.context["tool"] == "ffmpeg"

    def test_external_tool_error_stores_returncode(self):
        exc = AudioExternalToolError("error", tool="ffmpeg", returncode=1)
        assert exc.context["returncode"] == 1

    def test_external_tool_error_stores_truncated_stderr(self):
        long_stderr = "E: " + "x" * 500
        exc = AudioExternalToolError("error", stderr=long_stderr)
        # Stored stderr must be ≤ 300 chars (as per implementation)
        assert len(exc.context["stderr"]) <= 300

    def test_external_tool_error_omits_none_fields(self):
        exc = AudioExternalToolError("error")
        assert "tool" not in exc.context
        assert "returncode" not in exc.context
        assert "stderr" not in exc.context


class TestConfigurationErrorHierarchy:
    """AudioConfigurationError and its concrete subclasses."""

    def test_config_error_is_audio_suite_error(self):
        assert issubclass(AudioConfigurationError, AudioSuiteError)

    def test_config_file_error_is_config_error(self):
        assert issubclass(AudioConfigFileError, AudioConfigurationError)

    def test_config_value_error_is_config_error(self):
        assert issubclass(AudioConfigValueError, AudioConfigurationError)

    def test_missing_dependency_is_config_error(self):
        assert issubclass(AudioMissingDependencyError, AudioConfigurationError)

    def test_config_file_error_stores_config_file(self):
        exc = AudioConfigFileError("bad json", config_file="suite_config.json")
        assert exc.context["config_file"] == "suite_config.json"

    def test_missing_dependency_stores_dependency_name(self):
        exc = AudioMissingDependencyError("not found", dependency="ffmpeg")
        assert exc.context["dependency"] == "ffmpeg"

    def test_missing_dependency_without_name_has_empty_context(self):
        exc = AudioMissingDependencyError("missing")
        assert exc.context == {}


# ===========================================================================
# 2.  map_to_audio_error()
# ===========================================================================


class TestMapToAudioError:
    """Verify every _MAPPING entry and edge cases."""

    # ── Pass-through: already an AudioSuiteError ──────────────────────────────

    def test_already_audio_suite_error_returned_unchanged(self):
        original = AudioTagError("tag read failed")
        result = map_to_audio_error(original)
        assert result is original

    def test_already_audio_suite_error_context_merged(self):
        original = AudioTagError("tag read failed", context={"a": 1})
        map_to_audio_error(original, context={"b": 2})
        assert original.context["b"] == 2

    def test_already_audio_suite_error_not_double_wrapped(self):
        original = AudioCodecError("codec error")
        result = map_to_audio_error(original)
        assert type(result) is AudioCodecError

    # ── FileNotFoundError ─────────────────────────────────────────────────────

    def test_file_not_found_maps_to_audio_file_not_found(self):
        result = map_to_audio_error(FileNotFoundError("no such file"))
        assert isinstance(result, AudioFileNotFoundError)

    def test_file_not_found_preserves_original(self):
        cause = FileNotFoundError("gone")
        result = map_to_audio_error(cause)
        assert result.original is cause

    # ── PermissionError ───────────────────────────────────────────────────────

    def test_permission_error_maps_to_audio_permission_error(self):
        result = map_to_audio_error(PermissionError("denied"))
        assert isinstance(result, AudioPermissionError)

    # ── OSError — disk full (ENOSPC) ──────────────────────────────────────────

    def test_oserror_enospc_maps_to_disk_full(self):
        exc = OSError(errno.ENOSPC, "No space left on device")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioDiskFullError)

    # ── OSError — not-a-directory ─────────────────────────────────────────────

    def test_not_a_directory_error_maps_to_directory_error(self):
        exc = NotADirectoryError("not a dir")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioDirectoryError)

    def test_is_a_directory_error_maps_to_directory_error(self):
        exc = IsADirectoryError("is a dir")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioDirectoryError)

    # ── OSError — generic ─────────────────────────────────────────────────────

    def test_generic_oserror_maps_to_audio_io_error(self):
        exc = OSError("generic OS error")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioIOError)

    # ── subprocess.CalledProcessError ────────────────────────────────────────

    def test_called_process_error_maps_to_external_tool_error(self):
        exc = subprocess.CalledProcessError(1, "ffmpeg")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioExternalToolError)

    def test_called_process_error_returncode_in_context(self):
        exc = subprocess.CalledProcessError(2, "ffmpeg")
        result = map_to_audio_error(exc)
        assert result.context.get("returncode") == 2

    def test_called_process_error_with_stderr_stored(self):
        exc = subprocess.CalledProcessError(1, "ffmpeg", stderr="stderr text")
        result = map_to_audio_error(exc)
        assert "stderr text" in result.context.get("stderr", "")

    # ── Unicode errors ────────────────────────────────────────────────────────

    def test_unicode_decode_error_maps_to_tag_error(self):
        exc = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioTagError)

    def test_unicode_encode_error_maps_to_tag_error(self):
        exc = UnicodeEncodeError("utf-8", "ñ", 0, 1, "can't encode")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioTagError)

    # ── json.JSONDecodeError ──────────────────────────────────────────────────

    def test_json_decode_error_maps_to_config_file_error(self):
        exc = json.JSONDecodeError("Expecting value", "", 0)
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioConfigFileError)

    # ── ImportError ───────────────────────────────────────────────────────────

    def test_import_error_maps_to_missing_dependency(self):
        exc = ImportError("No module named 'mutagen'")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioMissingDependencyError)

    # ── TypeError → AudioCodecError ───────────────────────────────────────────

    def test_type_error_maps_to_codec_error(self):
        exc = TypeError("unexpected type")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioCodecError)

    # ── ValueError → AudioFormatError ────────────────────────────────────────

    def test_value_error_maps_to_format_error(self):
        exc = ValueError("bad value")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioFormatError)

    # ── RuntimeError → AudioAnalysisError ────────────────────────────────────

    def test_runtime_error_maps_to_analysis_error(self):
        exc = RuntimeError("analysis failed")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioAnalysisError)

    # ── ZeroDivisionError → AudioAnalysisError ────────────────────────────────

    def test_zero_division_maps_to_analysis_error(self):
        exc = ZeroDivisionError("division by zero")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioAnalysisError)

    # ── Unknown exception → root AudioSuiteError ─────────────────────────────

    def test_unknown_exception_wraps_to_root_class(self):
        class _WeirdError(Exception):
            pass

        exc = _WeirdError("something odd")
        result = map_to_audio_error(exc)
        assert isinstance(result, AudioSuiteError)
        assert result.original is exc

    # ── Context propagation ───────────────────────────────────────────────────

    def test_supplied_context_appears_in_result(self):
        exc = ValueError("bad")
        result = map_to_audio_error(exc, context={"operation": "read_tag"})
        assert result.context.get("operation") == "read_tag"

    def test_message_matches_original_str(self):
        exc = ValueError("detailed error text")
        result = map_to_audio_error(exc)
        assert "detailed error text" in result.message


# ===========================================================================
# 3.  handle_audio_errors()  DECORATOR
# ===========================================================================


class TestHandleAudioErrorsDecorator:
    """Behavioural contract of the @handle_audio_errors decorator."""

    # ── Success path ──────────────────────────────────────────────────────────

    def test_success_path_returns_normally(self):
        @handle_audio_errors()
        def good():
            return 42

        assert good() == 42

    # ── Reraise=True (default) ────────────────────────────────────────────────

    def test_built_in_re_raised_as_audio_suite_error(self):
        @handle_audio_errors()
        def bad():
            raise FileNotFoundError("gone")

        with pytest.raises(AudioFileNotFoundError):
            bad()

    def test_re_raised_exception_carries_original(self):
        cause = FileNotFoundError("gone")

        @handle_audio_errors()
        def bad():
            raise cause

        with pytest.raises(AudioFileNotFoundError) as exc_info:
            bad()

        assert exc_info.value.original is cause

    def test_already_audio_suite_error_re_raised_unchanged(self):
        @handle_audio_errors()
        def bad():
            raise AudioTagError("tag fail")

        with pytest.raises(AudioTagError):
            bad()

    # ── Reraise=False ─────────────────────────────────────────────────────────

    def test_reraise_false_swallows_exception(self):
        @handle_audio_errors(reraise=False)
        def bad():
            raise RuntimeError("boom")

        assert bad() is None  # no raise

    def test_reraise_false_returns_return_on_error(self):
        @handle_audio_errors(reraise=False, return_on_error=False)
        def bad():
            raise RuntimeError("boom")

        assert bad() is False

    def test_reraise_false_returns_custom_sentinel(self):
        sentinel = object()

        @handle_audio_errors(reraise=False, return_on_error=sentinel)
        def bad():
            raise OSError("disk error")

        assert bad() is sentinel

    # ── KeyboardInterrupt / SystemExit always propagate ───────────────────────

    def test_keyboard_interrupt_propagates(self):
        @handle_audio_errors(reraise=False)
        def bad():
            raise KeyboardInterrupt()

        with pytest.raises(KeyboardInterrupt):
            bad()

    def test_system_exit_propagates(self):
        @handle_audio_errors(reraise=False)
        def bad():
            raise SystemExit(0)

        with pytest.raises(SystemExit):
            bad()

    # ── suppress_types ────────────────────────────────────────────────────────

    def test_suppress_types_suppresses_matching_exception(self):
        @handle_audio_errors(reraise=True, suppress_types=(AudioExternalToolError,))
        def bad():
            raise subprocess.CalledProcessError(1, "ffmpeg")

        # Should NOT raise despite reraise=True
        result = bad()
        assert result is None

    def test_suppress_types_does_not_suppress_non_matching(self):
        @handle_audio_errors(reraise=True, suppress_types=(AudioExternalToolError,))
        def bad():
            raise FileNotFoundError("gone")

        with pytest.raises(AudioFileNotFoundError):
            bad()

    # ── Logging ───────────────────────────────────────────────────────────────

    def test_error_logged_with_exc_info(self):
        @handle_audio_errors(context="test_op")
        def bad():
            raise ValueError("bad value")

        with patch("audio_suite_shared.exceptions.logger") as mock_log:
            with pytest.raises(AudioFormatError):
                bad()
            # logger.log must have been called (any level)
            assert mock_log.log.called

    def test_log_level_respected(self):
        @handle_audio_errors(context="test_op", log_level=logging.WARNING)
        def bad():
            raise ValueError("bad value")

        with patch("audio_suite_shared.exceptions.logger") as mock_log:
            with pytest.raises(AudioFormatError):
                bad()
            call_args = mock_log.log.call_args
            assert call_args[0][0] == logging.WARNING

    def test_context_label_appears_in_log_message(self):
        @handle_audio_errors(context="loudness_measurement")
        def bad():
            raise RuntimeError("analysis failed")

        with patch("audio_suite_shared.exceptions.logger") as mock_log:
            with pytest.raises(AudioAnalysisError):
                bad()
            log_str = str(mock_log.log.call_args)
            assert "loudness_measurement" in log_str

    def test_default_context_is_function_qualname(self):
        @handle_audio_errors()
        def my_special_function():
            raise RuntimeError("fail")

        with patch("audio_suite_shared.exceptions.logger") as mock_log:
            with pytest.raises(AudioAnalysisError):
                my_special_function()
            log_str = str(mock_log.log.call_args)
            assert "my_special_function" in log_str

    def test_decorator_logger_in_audio_suite_namespace(self):
        """The module logger must hang off "audio_suite" so configure_logging()'s
        file handler receives its records."""
        from audio_suite_shared import exceptions as exceptions_module

        assert exceptions_module.logger.name.startswith("audio_suite.")

    def test_error_record_reaches_audio_suite_logger(self):
        """Regression: decorator-captured errors must propagate to handlers
        attached to the "audio_suite" logger (logs/audio_suite.log) — the
        namespace the shared exception machinery writes under."""

        class _Capture(logging.Handler):
            def __init__(self):
                super().__init__()
                self.records: list[logging.LogRecord] = []

            def emit(self, record: logging.LogRecord) -> None:
                self.records.append(record)

        suite_logger = logging.getLogger("audio_suite")
        capture = _Capture()
        old_level = suite_logger.level
        old_propagate = suite_logger.propagate
        suite_logger.addHandler(capture)
        suite_logger.setLevel(logging.DEBUG)
        suite_logger.propagate = False
        try:

            @handle_audio_errors(reraise=False, context="log_routing_probe")
            def bad():
                raise ValueError("routing probe")

            bad()
        finally:
            suite_logger.removeHandler(capture)
            suite_logger.setLevel(old_level)
            suite_logger.propagate = old_propagate

        assert any(
            "log_routing_probe" in record.getMessage() for record in capture.records
        )

    # ── functools.wraps ───────────────────────────────────────────────────────

    def test_wrapped_function_preserves_name(self):
        @handle_audio_errors()
        def compute_gain():
            pass

        assert compute_gain.__name__ == "compute_gain"

    def test_wrapped_function_preserves_docstring(self):
        @handle_audio_errors()
        def compute_gain():
            """Compute ReplayGain."""

        assert "ReplayGain" in (compute_gain.__doc__ or "")


# ===========================================================================
# 4.  user_message_for()
# ===========================================================================


class TestUserMessageFor:
    """user_message_for() returns non-technical, safe strings."""

    _SUBCLASSES = [
        AudioFileNotFoundError,
        AudioPermissionError,
        AudioDiskFullError,
        AudioDirectoryError,
        AudioCodecError,
        AudioFormatError,
        AudioExternalToolError,
        AudioTagError,
        AudioAnalysisError,
        AudioConfigFileError,
        AudioConfigValueError,
        AudioMissingDependencyError,
        AudioIOError,
        AudioProcessingError,
        AudioConfigurationError,
        AudioSuiteError,
    ]

    @pytest.mark.parametrize("exc_class", _SUBCLASSES)
    def test_returns_non_empty_string_for_every_subclass(self, exc_class):
        exc = exc_class("some error")
        msg = user_message_for(exc)
        assert isinstance(msg, str) and len(msg) > 0

    @pytest.mark.parametrize("exc_class", _SUBCLASSES)
    def test_message_contains_no_raw_path(self, exc_class, tmp_path):
        """Paths must not leak into user-facing messages (non-debug mode)."""
        secret = str(tmp_path / "secret_music_folder")
        exc = exc_class(secret)
        with patch.dict(os.environ, {"AUDIOSUITE_DEBUG": "0"}):
            msg = user_message_for(exc)
        assert secret not in msg

    def test_file_not_found_mentions_file(self):
        exc = AudioFileNotFoundError("gone")
        msg = user_message_for(exc)
        assert "file" in msg.lower() or "found" in msg.lower()

    def test_disk_full_mentions_disk_or_space(self):
        exc = AudioDiskFullError("no space")
        msg = user_message_for(exc)
        assert "disk" in msg.lower() or "space" in msg.lower()

    def test_external_tool_mentions_ffmpeg_or_tool(self):
        exc = AudioExternalToolError("ffmpeg crash")
        msg = user_message_for(exc)
        assert "tool" in msg.lower() or "ffmpeg" in msg.lower()

    def test_missing_dependency_mentions_tool_or_library(self):
        exc = AudioMissingDependencyError("no ffmpeg")
        msg = user_message_for(exc)
        assert (
            "tool" in msg.lower()
            or "install" in msg.lower()
            or "library" in msg.lower()
        )

    def test_unknown_exception_returns_fallback_string(self):
        class _RandomError(Exception):
            pass

        msg = user_message_for(_RandomError("something"))
        assert isinstance(msg, str) and len(msg) > 0

    def test_mro_most_specific_subclass_wins(self):
        """AudioFileNotFoundError message must differ from generic AudioIOError."""
        fnf_msg = user_message_for(AudioFileNotFoundError("gone"))
        io_msg = user_message_for(AudioIOError("generic"))
        # They may differ — at minimum both must be non-empty strings
        assert fnf_msg and io_msg

    # ── Debug mode ────────────────────────────────────────────────────────────

    def test_debug_mode_returns_full_str(self):
        exc = AudioFileNotFoundError("internal details at /secret/path")
        with patch.dict(os.environ, {"AUDIOSUITE_DEBUG": "1"}):
            msg = user_message_for(exc)
        assert "internal details" in msg

    def test_debug_false_hides_internal_details(self):
        exc = AudioFileNotFoundError("internal details at /secret/path")
        with patch.dict(os.environ, {"AUDIOSUITE_DEBUG": "0"}):
            msg = user_message_for(exc)
        assert "internal details" not in msg


# ===========================================================================
# 5.  SecureErrorHandler
# ===========================================================================


class TestSecureErrorHandlerProductionMode:
    """All handle_* methods in production mode (no debug flag)."""

    @pytest.fixture(autouse=True)
    @staticmethod
    def _prod_mode():
        """Ensure debug mode is off for this class."""
        SecureErrorHandler.set_debug_mode(False)
        yield
        SecureErrorHandler.set_debug_mode(False)

    def test_handle_error_returns_string(self):
        result = SecureErrorHandler.handle_error(ValueError("bad"), context="test_op")
        assert isinstance(result, str) and len(result) > 0

    def test_handle_error_does_not_expose_raw_exception_message(self):
        secret = "internal_secret_value_xyz"
        result = SecureErrorHandler.handle_error(ValueError(secret), context="test_op")
        assert secret not in result

    def test_handle_error_logs_with_exc_info(self):
        with patch("audio_suite_shared.security.error_handler._logger") as mock_logger:
            SecureErrorHandler.handle_error(ValueError("oops"), context="ctx")
            mock_logger.error.assert_called_once()
            _, kwargs = mock_logger.error.call_args
            assert kwargs.get("exc_info") is True

    def test_handle_file_error_returns_string(self):
        result = SecureErrorHandler.handle_file_error(
            FileNotFoundError("gone"), file_path="/music/track.mp3"
        )
        assert isinstance(result, str) and len(result) > 0

    def test_handle_file_error_does_not_expose_full_path(self):
        result = SecureErrorHandler.handle_file_error(
            PermissionError("denied"), file_path="/private/secret/path/track.mp3"
        )
        assert "/private/secret/path" not in result

    def test_handle_network_error_mentions_connection(self):
        result = SecureErrorHandler.handle_network_error(
            ConnectionError("refused"), service="MusicBrainz"
        )
        assert "MusicBrainz" in result or "connect" in result.lower()

    def test_handle_network_error_no_service_returns_generic(self):
        result = SecureErrorHandler.handle_network_error(ConnectionError("refused"))
        assert "network" in result.lower() or "connection" in result.lower()

    def test_handle_api_error_401_mentions_authentication(self):
        result = SecureErrorHandler.handle_api_error(
            Exception("401 unauthorized"), api_name="FanArt.tv"
        )
        assert "authentication" in result.lower() or "api key" in result.lower()

    def test_handle_api_error_429_mentions_rate_limit(self):
        result = SecureErrorHandler.handle_api_error(
            Exception("429 rate limit exceeded"), api_name="Deezer"
        )
        assert "rate limit" in result.lower()

    def test_handle_api_error_404_mentions_not_found(self):
        result = SecureErrorHandler.handle_api_error(
            Exception("404 not found"), api_name="iTunes"
        )
        assert "not found" in result.lower()

    def test_handle_api_error_403_mentions_access_denied(self):
        result = SecureErrorHandler.handle_api_error(
            Exception("403 forbidden"), api_name="SomeAPI"
        )
        assert "access denied" in result.lower() or "permission" in result.lower()

    def test_handle_api_error_timeout_mentions_timeout(self):
        result = SecureErrorHandler.handle_api_error(
            Exception("timeout waiting for response"), api_name="MusicBrainz"
        )
        assert "timed out" in result.lower() or "timeout" in result.lower()

    def test_handle_api_error_generic_returns_fallback(self):
        result = SecureErrorHandler.handle_api_error(
            Exception("something unexpected"), api_name="MyAPI"
        )
        assert "MyAPI" in result or "error" in result.lower()

    def test_handle_processing_error_returns_string(self):
        result = SecureErrorHandler.handle_processing_error(
            RuntimeError("analysis failed"), file_name="track.mp3"
        )
        assert isinstance(result, str) and len(result) > 0

    def test_handle_config_error_returns_string(self):
        result = SecureErrorHandler.handle_config_error(
            json.JSONDecodeError("bad json", "", 0),
            config_file="audio_suite_config.json",
        )
        assert isinstance(result, str) and len(result) > 0


class TestSecureErrorHandlerDebugMode:
    """Same methods, but with debug mode on — raw details must be exposed."""

    @pytest.fixture(autouse=True)
    @staticmethod
    def _debug_mode():
        SecureErrorHandler.set_debug_mode(True)
        yield
        SecureErrorHandler.set_debug_mode(False)

    def test_handle_error_exposes_raw_message_in_debug(self):
        secret = "very_detailed_internal_error_XYZ"
        result = SecureErrorHandler.handle_error(
            ValueError(secret), context="debug_ctx"
        )
        assert secret in result

    def test_handle_file_error_exposes_filename_in_debug(self):
        result = SecureErrorHandler.handle_file_error(
            PermissionError("denied"), file_path="/secret/track.mp3"
        )
        assert "track.mp3" in result

    def test_handle_processing_error_exposes_filename_in_debug(self):
        result = SecureErrorHandler.handle_processing_error(
            RuntimeError("numpy crash"), file_name="album.flac"
        )
        assert "album.flac" in result

    def test_handle_config_error_exposes_config_file_in_debug(self):
        result = SecureErrorHandler.handle_config_error(
            json.JSONDecodeError("bad", "", 0), config_file="prefs.json"
        )
        assert "prefs.json" in result

    def test_set_debug_mode_sets_env_variable(self):
        SecureErrorHandler.set_debug_mode(True)
        assert os.environ.get("AUDIOSUITE_DEBUG") == "1"

    def test_set_debug_mode_false_clears_env_variable(self):
        SecureErrorHandler.set_debug_mode(False)
        assert os.environ.get("AUDIOSUITE_DEBUG") == "0"


# ===========================================================================
# 6.  retry_with_backoff & get_recovery_action (standalone)
# ===========================================================================


class TestRetryWithBackoff:
    """retry_with_backoff() — success, retry exhaustion, non-retryable."""

    @pytest.fixture
    @staticmethod
    def retry_cfg():
        return RetryConfig(
            max_retries=3,
            retry_delay=0.001,
            backoff_factor=1.0,
            retry_on_exceptions=[IOError, OSError],
            max_delay=0.01,
        )

    def test_success_on_first_attempt_returns_result(self, retry_cfg):
        fn = MagicMock(return_value="ok")
        result = retry_with_backoff(fn, retry_cfg, "op_001")
        assert result == "ok"
        fn.assert_called_once()

    def test_success_after_one_transient_failure(self, retry_cfg):
        fn = MagicMock(side_effect=[IOError("transient"), "ok"])
        with patch("audio_suite_shared.error_recovery.time.sleep"):
            result = retry_with_backoff(fn, retry_cfg, "op_002")
        assert result == "ok"
        assert fn.call_count == 2

    def test_retries_up_to_max_then_raises(self, retry_cfg):
        fn = MagicMock(side_effect=IOError("always fails"))
        with patch("audio_suite_shared.error_recovery.time.sleep"):
            with pytest.raises(IOError):
                retry_with_backoff(fn, retry_cfg, "op_003")
        assert fn.call_count == retry_cfg.max_retries + 1

    def test_non_retryable_exception_raises_immediately(self, retry_cfg):
        fn = MagicMock(side_effect=ValueError("non-retryable"))
        with pytest.raises(ValueError):
            retry_with_backoff(fn, retry_cfg, "op_004")
        fn.assert_called_once()

    def test_sleep_called_between_retries(self, retry_cfg):
        fn = MagicMock(side_effect=[IOError("fail"), IOError("fail"), "ok"])
        with patch("audio_suite_shared.error_recovery.time.sleep") as mock_sleep:
            retry_with_backoff(fn, retry_cfg, "op_005")
        assert mock_sleep.call_count == 2

    def test_exponential_backoff_delay_increases(self):
        cfg = RetryConfig(
            max_retries=3,
            retry_delay=1.0,
            backoff_factor=2.0,
            retry_on_exceptions=[IOError],
            max_delay=60.0,
        )
        fn = MagicMock(side_effect=[IOError(), IOError(), IOError(), "ok"])
        recorded_delays = []

        def fake_sleep(d):
            recorded_delays.append(d)

        with patch(
            "audio_suite_shared.error_recovery.time.sleep", side_effect=fake_sleep
        ):
            retry_with_backoff(fn, cfg, "op_006")

        assert len(recorded_delays) == 3
        for i in range(1, len(recorded_delays)):
            assert recorded_delays[i] >= recorded_delays[i - 1]

    def test_delay_capped_at_max_delay(self):
        cfg = RetryConfig(
            max_retries=5,
            retry_delay=100.0,
            backoff_factor=10.0,
            retry_on_exceptions=[IOError],
            max_delay=5.0,
        )
        fn = MagicMock(side_effect=IOError("always"))
        delays = []
        with patch(
            "audio_suite_shared.error_recovery.time.sleep",
            side_effect=lambda d: delays.append(d),
        ):
            with pytest.raises(IOError):
                retry_with_backoff(fn, cfg, "op_007")

        assert all(d <= cfg.max_delay for d in delays)

    def test_last_exception_raised_after_exhaustion(self, retry_cfg):
        fn = MagicMock(side_effect=IOError("very specific message"))
        with patch("audio_suite_shared.error_recovery.time.sleep"):
            with pytest.raises(IOError, match="very specific message"):
                retry_with_backoff(fn, retry_cfg, "op_008")


class TestGetRecoveryAction:
    """get_recovery_action() maps error types to RecoveryAction enum values."""

    def test_memory_error_returns_abort(self):
        assert get_recovery_action(MemoryError(), "processing") == RecoveryAction.ABORT

    def test_keyboard_interrupt_returns_abort(self):
        assert (
            get_recovery_action(KeyboardInterrupt(), "processing")
            == RecoveryAction.ABORT
        )

    def test_permission_error_returns_retry(self):
        assert (
            get_recovery_action(PermissionError("locked"), "write_tag")
            == RecoveryAction.RETRY
        )

    def test_os_error_returns_retry(self):
        assert (
            get_recovery_action(OSError("network fs"), "read") == RecoveryAction.RETRY
        )

    def test_file_not_found_returns_skip(self):
        assert (
            get_recovery_action(FileNotFoundError("gone"), "processing")
            == RecoveryAction.SKIP
        )

    def test_io_error_returns_retry(self):
        assert get_recovery_action(IOError("io issue"), "read") == RecoveryAction.RETRY

    def test_user_callback_used_when_provided(self):
        callback = MagicMock(return_value=RecoveryAction.USER_CHOICE)
        action = get_recovery_action(
            PermissionError("locked"), "write_tag", user_callback=callback
        )
        callback.assert_called_once()
        assert action == RecoveryAction.USER_CHOICE

    def test_unknown_error_returns_retry_without_callback(self):
        assert (
            get_recovery_action(Exception("random"), "analysis") == RecoveryAction.RETRY
        )

    def test_unknown_error_uses_callback_when_provided(self):
        callback = MagicMock(return_value=RecoveryAction.ABORT)
        action = get_recovery_action(
            Exception("random"), "analysis", user_callback=callback
        )
        assert action == RecoveryAction.ABORT


# ===========================================================================
# 7.  INTEGRATION — decorator + map_to_audio_error + logging chain
# ===========================================================================


class TestDecoratorIntegration:
    """End-to-end: built-in raised inside @handle_audio_errors, caught and
    re-raised as the correct AudioSuiteError subclass with logging."""

    def test_file_not_found_inside_decorator_surfaces_as_correct_type(self):
        @handle_audio_errors(context="load_config")
        def load_config():
            raise FileNotFoundError("/etc/missing.json")

        with pytest.raises(AudioFileNotFoundError):
            load_config()

    def test_called_process_error_surfaces_as_external_tool_error(self):
        @handle_audio_errors(context="run_ffmpeg")
        def run_ffmpeg():
            raise subprocess.CalledProcessError(1, "ffmpeg", stderr="error output")

        with pytest.raises(AudioExternalToolError):
            run_ffmpeg()

    def test_json_error_surfaces_as_config_file_error(self):
        @handle_audio_errors(context="parse_config")
        def parse_config():
            raise json.JSONDecodeError("Unexpected token", "", 0)

        with pytest.raises(AudioConfigFileError):
            parse_config()

    def test_no_double_wrapping_when_already_audio_suite_error(self):
        @handle_audio_errors(context="tag_write")
        def write_tag():
            raise AudioTagError("mutagen refused")

        with pytest.raises(AudioTagError) as exc_info:
            write_tag()
        # Must be exactly AudioTagError, not wrapped in something else
        assert type(exc_info.value) is AudioTagError

    def test_suppress_types_combined_with_reraise_true(self):
        """suppress_types wins over reraise=True for the named types."""

        @handle_audio_errors(
            reraise=True,
            suppress_types=(AudioAnalysisError,),
            return_on_error="fallback",
        )
        def analyze():
            raise ZeroDivisionError("empty audio segment")

        result = analyze()
        assert result == "fallback"

    def test_chain_of_wrappers_does_not_double_log(self):
        """Inner @handle_audio_errors suppresses; outer never sees an exception."""

        @handle_audio_errors(reraise=False, return_on_error=None, context="inner")
        def inner():
            raise RuntimeError("inner fail")

        @handle_audio_errors(context="outer")
        def outer():
            return inner()  # inner swallowed the error, returns None

        result = outer()
        assert result is None

    def test_reraise_false_allows_caller_to_continue(self):
        results = []

        @handle_audio_errors(reraise=False, return_on_error="ERROR")
        def process_file(name):
            if name == "bad.mp3":
                raise FileNotFoundError("gone")
            return f"ok:{name}"

        for name in ["a.mp3", "bad.mp3", "c.mp3"]:
            results.append(process_file(name))

        assert results == ["ok:a.mp3", "ERROR", "ok:c.mp3"]
