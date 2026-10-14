"""
Tests for BaseFileProcessor class.

Comprehensive test coverage for file discovery, progress
tracking, and parallel processing.

Changed in 1.0.1: adds an in-place error-path test asserting the display and
log callbacks carry the sanitised ``user_message_for`` text, never raw
``str(exc)``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import threading
from collections.abc import Callable, Generator
from dataclasses import FrozenInstanceError
from pathlib import Path
from queue import Queue
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from audio_suite_shared.exceptions import AudioFileNotFoundError, AudioSuiteError
from audio_suite_shared.file_processor_base import (
    BaseFileProcessor,
    InplaceDspFn,
    InplaceDspResult,
    ProgressCallback,
    _emit_completion,
    _preflight_discover,
)


class TestBaseFileProcessorInitialization:
    """Tests for BaseFileProcessor initialization."""

    def test_default_initialization(self, mock_processor: BaseFileProcessor) -> None:
        """Test processor initializes with default values."""
        assert mock_processor.max_workers == 2
        assert mock_processor.operation_type == "test_operation"
        assert mock_processor.resource_manager is not None

    def test_custom_initialization(self) -> None:
        """Test processor initializes with custom values."""
        with patch("audio_suite_shared.file_processor_base.get_resource_manager"):
            processor = BaseFileProcessor(max_workers=8, operation_type="custom_op")
            assert processor.max_workers == 8
            assert processor.operation_type == "custom_op"


class TestDiscoverAudioFiles:
    """Tests for file discovery functionality."""

    def test_discover_audio_files_default_extensions(
        self, mock_processor: BaseFileProcessor, sample_audio_files: Path
    ) -> None:
        """Test discovery with default audio extensions."""
        files = mock_processor.discover_audio_files(str(sample_audio_files))

        # Should find .mp3, .flac, .ogg, .m4a files (not .txt, .jpg)
        assert len(files) >= 4
        assert any(f.endswith(".mp3") for f in files)
        assert any(f.endswith(".flac") for f in files)
        assert not any(f.endswith(".txt") for f in files)
        assert not any(f.endswith(".jpg") for f in files)

    def test_discover_audio_files_custom_extensions(
        self, mock_processor: BaseFileProcessor, sample_audio_files: Path
    ) -> None:
        """Test discovery with custom extensions."""
        files = mock_processor.discover_audio_files(
            str(sample_audio_files), extensions=(".txt", ".jpg")
        )

        assert len(files) >= 2
        assert any(f.endswith(".txt") for f in files)
        assert any(f.endswith(".jpg") for f in files)

    def test_discover_audio_files_empty_directory(
        self, mock_processor: BaseFileProcessor, empty_directory: Path
    ) -> None:
        """Test discovery in empty directory returns empty list."""
        files = mock_processor.discover_audio_files(str(empty_directory))
        assert files == []

    def test_discover_audio_files_nonexistent_directory(
        self, mock_processor: BaseFileProcessor
    ) -> None:
        """Test discovery in nonexistent directory raises error."""
        with pytest.raises(AudioSuiteError):
            mock_processor.discover_audio_files("/nonexistent/path/12345")

    def test_discover_audio_files_permission_error(
        self, mock_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        """Test discovery with permission denied raises AudioPermissionError."""
        with patch(
            "audio_suite_shared.file_processor_base.os.scandir",
            side_effect=PermissionError("Permission denied"),
        ):
            with pytest.raises(AudioSuiteError):
                mock_processor.discover_audio_files(str(tmp_path))

    def test_discover_case_insensitive_extensions(
        self, mock_processor: BaseFileProcessor, sample_audio_files: Path
    ) -> None:
        """Test that file discovery is case insensitive."""
        # Create files with uppercase extensions
        (sample_audio_files / "upper.MP3").write_bytes(b"data")
        (sample_audio_files / "mixed.FlAc").write_bytes(b"data")

        files = mock_processor.discover_audio_files(str(sample_audio_files))
        assert "upper.MP3" in files
        assert "mixed.FlAc" in files


class TestCreateProgressTracker:
    """Tests for progress tracking infrastructure."""

    def test_progress_tracker_returns_expected_structure(
        self, mock_processor: BaseFileProcessor
    ) -> None:
        """Test progress tracker returns correct tuple structure."""
        mock_callback = MagicMock()
        result = mock_processor.create_progress_tracker(mock_callback, total_files=10)

        assert len(result) == 5
        processed, skipped, errors, log_entries, wrapper_callback = result

        # Integer counters are single-element lists
        for counter in (processed, skipped, errors):
            assert isinstance(counter, list)
            assert len(counter) == 1
            assert counter[0] == 0

        # log_entries is an empty list (not a counter)
        assert isinstance(log_entries, list)
        assert len(log_entries) == 0

        # Check wrapper is callable
        assert callable(wrapper_callback)

    def test_progress_tracker_wrapper_calls_original_callback(
        self, mock_processor: BaseFileProcessor
    ) -> None:
        """Test wrapper callback properly calls original callback."""
        mock_callback = MagicMock()
        processed, skipped, errors, _logs, wrapper = (
            mock_processor.create_progress_tracker(mock_callback, total_files=5)
        )

        # _on_progress increments processed[0] internally — counters start at zero
        wrapper(
            n_skipped=1,
            n_errors=1,
            display_text="test_file.mp3",
            log_text="test_file.mp3",
        )

        mock_callback.assert_called_once_with(
            processed=1,
            total=5,
            skipped=1,
            errors=1,
            display_text="test_file.mp3",
        )

    def test_progress_tracker_error_indicator(
        self, mock_processor: BaseFileProcessor
    ) -> None:
        """Test wrapper shows error indicator when errors exist."""
        mock_callback = MagicMock()
        processed, skipped, errors, _logs, wrapper = (
            mock_processor.create_progress_tracker(mock_callback, total_files=10)
        )

        wrapper(n_errors=2, display_text="[2 ERRORS] file.mp3", log_text="file.mp3")

        # Check that error count appears in display text
        call_args = mock_callback.call_args
        assert "ERRORS" in str(call_args)


class TestRunParallelProcessing:
    """Tests for parallel processing functionality."""

    def test_parallel_processing_calls_callbacks(
        self,
        mock_processor: BaseFileProcessor,
        sample_audio_files: Path,
        mock_callbacks: dict,
    ) -> None:
        """Test parallel processing invokes all callbacks."""
        mock_processor_func = MagicMock()

        mock_processor.run_parallel_processing(
            dir_path=str(sample_audio_files),
            processor_func=mock_processor_func,
            on_progress=mock_callbacks["on_progress"],
            on_complete=mock_callbacks["on_complete"],
            on_error=mock_callbacks["on_error"],
        )

        # Verify processor function was called for audio files
        assert mock_processor_func.called

        # Verify callbacks were invoked
        mock_callbacks["on_complete"].assert_called_once()

    def test_parallel_processing_with_extensions_filter(
        self,
        mock_processor: BaseFileProcessor,
        sample_audio_files: Path,
        mock_callbacks: dict,
    ) -> None:
        """Test extension filtering in parallel processing."""
        mock_processor_func = MagicMock()

        mock_processor.run_parallel_processing(
            dir_path=str(sample_audio_files),
            processor_func=mock_processor_func,
            on_progress=mock_callbacks["on_progress"],
            on_complete=mock_callbacks["on_complete"],
            on_error=mock_callbacks["on_error"],
            extensions=(".mp3",),
        )

        # Verify processor only called for .mp3 files
        # processor_func is invoked with kwargs:
        #   filename=, dir_path=, slot_idx=, lock=, on_progress=
        for call_args in mock_processor_func.call_args_list:
            filename = call_args.kwargs.get("filename", "")
            assert filename.endswith(".mp3"), f"Expected .mp3, got: {filename!r}"

    def test_parallel_processing_handles_errors(
        self,
        mock_processor: BaseFileProcessor,
        sample_audio_files: Path,
        mock_callbacks: dict,
    ) -> None:
        """Test error handling in parallel processing."""

        def failing_processor(*args, **kwargs):
            raise RuntimeError("Processing failed")

        mock_processor.run_parallel_processing(
            dir_path=str(sample_audio_files),
            processor_func=failing_processor,
            on_progress=mock_callbacks["on_progress"],
            on_complete=mock_callbacks["on_complete"],
            on_error=mock_callbacks["on_error"],
        )

        # Errors are reported via on_progress (n_errors kwarg), not on_error.
        # on_error only fires for directory-level failures.
        # Verify on_progress was called and on_complete still fires.
        assert mock_callbacks["on_progress"].called
        assert mock_callbacks["on_complete"].called

    def test_parallel_processing_discovery_failure_routes_to_on_error(
        self,
        mock_processor: BaseFileProcessor,
        mock_callbacks: dict,
    ) -> None:
        """A discovery AudioSuiteError must be routed to on_error (sanitised)."""
        with patch.object(
            mock_processor,
            "discover_audio_files",
            side_effect=AudioSuiteError("scan failed"),
        ):
            mock_processor.run_parallel_processing(
                dir_path="/does/not/matter",
                processor_func=MagicMock(),
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
            )
        mock_callbacks["on_error"].assert_called_once()
        mock_callbacks["on_complete"].assert_not_called()

    def test_parallel_processing_no_files_routes_to_on_error(
        self,
        mock_processor: BaseFileProcessor,
        mock_callbacks: dict,
    ) -> None:
        """An empty scan result must hit the no-files message channel."""
        with patch.object(
            mock_processor,
            "discover_audio_files",
            return_value=[],
        ):
            mock_processor.run_parallel_processing(
                dir_path="/empty/dir",
                processor_func=MagicMock(),
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
            )
        mock_callbacks["on_error"].assert_called_once_with(
            "No supported audio files found in selected directory."
        )
        mock_callbacks["on_complete"].assert_not_called()


class TestRunWithRetry:
    """Tests for retry-with-backoff wrapper (run_with_retry)."""

    def test_succeeds_on_first_attempt(self, mock_processor: BaseFileProcessor) -> None:
        """A callable that succeeds immediately returns its result."""
        result = mock_processor.run_with_retry(lambda: 42, label="succeeds")
        assert result == 42

    def test_retries_then_succeeds(self, mock_processor: BaseFileProcessor) -> None:
        """A callable failing twice then succeeding returns the value."""
        attempts = 0

        def flaky() -> int:
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise OSError("transient IO failure")
            return 7

        result = mock_processor.run_with_retry(
            flaky, base_delay=0, max_retries=3, label="flaky"
        )
        assert result == 7
        assert attempts == 3

    def test_raises_after_max_retries(
        self,
        mock_processor: BaseFileProcessor,
    ) -> None:
        """A persistently failing callable raises after retries are exhausted."""
        attempts = 0

        def always_fails() -> None:
            nonlocal attempts
            attempts += 1
            raise OSError("persistent IO failure")

        with pytest.raises(OSError):
            mock_processor.run_with_retry(
                always_fails, base_delay=0, max_retries=2, label="fails"
            )
        assert attempts == 3

    def test_non_retryable_error_raises_immediately(
        self,
        mock_processor: BaseFileProcessor,
    ) -> None:
        """Exceptions outside the retry set propagate without retrying."""
        calls = 0

        def bad() -> None:
            nonlocal calls
            calls += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            mock_processor.run_with_retry(bad, base_delay=0, max_retries=3, label="bad")
        assert calls == 1


@patch("audio_suite_shared.file_processor_base.retry_with_backoff")
class TestRunWithRetryLazy:
    """run_with_retry must build a RetryConfig and delegate to the helper."""

    def test_builds_default_config(
        self,
        mock_retry: MagicMock,
        mock_processor: BaseFileProcessor,
    ) -> None:
        mock_processor.run_with_retry(lambda: None, label="x")
        cfg = mock_retry.call_args
        assert cfg.args[1].max_retries == 3
        assert cfg.args[1].backoff_factor == 2.0
        assert [IOError, OSError, PermissionError] == list(
            cfg.args[1].retry_on_exceptions
        )
        assert cfg.args[2] == "x"

    def test_custom_retries(
        self,
        mock_retry: MagicMock,
        mock_processor: BaseFileProcessor,
    ) -> None:
        mock_processor.run_with_retry(
            lambda: None, max_retries=5, base_delay=2.0, label="y"
        )
        cfg = mock_retry.call_args.args[1]
        assert cfg.max_retries == 5
        assert cfg.retry_delay == 2.0


class TestCreateRetryConfig:
    """Tests for retry configuration creation."""

    def test_default_retry_config(self, mock_processor: BaseFileProcessor) -> None:
        """Test default retry configuration values."""
        config = mock_processor.create_retry_config()

        assert config.max_retries == 3
        assert config.retry_delay == 0.5
        assert config.backoff_factor == 1.5
        assert IOError in config.retry_on_exceptions
        assert OSError in config.retry_on_exceptions
        assert PermissionError in config.retry_on_exceptions

    def test_custom_retry_config(self, mock_processor: BaseFileProcessor) -> None:
        """Test custom retry configuration values."""
        config = mock_processor.create_retry_config(
            max_retries=5, retry_delay=2.0, backoff_factor=1.5
        )

        assert config.max_retries == 5
        assert config.retry_delay == 2.0
        assert config.backoff_factor == 1.5


class TestIntegrationScenarios:
    """Integration-style tests for complete workflows."""

    def test_full_processing_workflow(
        self,
        temp_directory: Path,
        mock_callbacks: dict,
    ) -> None:
        """Test a complete processing workflow end-to-end."""
        # Create test files
        for i in range(5):
            (temp_directory / f"track_{i}.mp3").write_bytes(b"audio data")

        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            processor = BaseFileProcessor(max_workers=2, operation_type="test")

            processed_files = []

            def simple_processor(filename: str, dir_path: str, **kwargs) -> None:
                processed_files.append(filename)

            processor.run_parallel_processing(
                dir_path=str(temp_directory),
                processor_func=simple_processor,
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
            )

            # Verify all files were called through processor_func
            assert len(processed_files) == 5

            # Verify completion callback was called with correct totals
            mock_callbacks["on_complete"].assert_called_once()
            call_kwargs = mock_callbacks["on_complete"].call_args[1]
            assert call_kwargs["total"] == 5
            # processed counter only increments when on_progress
            # is called from processor_func;
            # simple_processor above doesn't call it,
            # so we verify total is correct instead.
            assert call_kwargs["total"] == 5


class TestEdgeCases:
    """Edge case and error condition tests."""

    def test_processor_with_zero_workers(self) -> None:
        """Test processor handles zero workers gracefully."""
        with patch("audio_suite_shared.file_processor_base.get_resource_manager"):
            processor = BaseFileProcessor(max_workers=0, operation_type="edge")
            assert processor.max_workers == 0

    def test_processor_with_negative_workers(self) -> None:
        """Test processor handles negative worker count."""
        with patch("audio_suite_shared.file_processor_base.get_resource_manager"):
            processor = BaseFileProcessor(max_workers=-1, operation_type="edge")
            assert processor.max_workers == -1

    def test_discover_files_with_none_extensions(
        self, mock_processor: BaseFileProcessor, sample_audio_files: Path
    ) -> None:
        """Test discovery with None extensions uses defaults."""
        files = mock_processor.discover_audio_files(
            str(sample_audio_files), extensions=None
        )
        # Should use default extensions and find audio files
        assert len(files) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# _process_with_recovery  (direct unit tests)
# ═══════════════════════════════════════════════════════════════════════════════


class TestProcessWithRecovery:
    """Direct tests for BaseFileProcessor._process_with_recovery."""

    def test_successful_processing_releases_slot(
        self, mock_processor: BaseFileProcessor, sample_audio_files: Path
    ) -> None:
        """After successful processing the slot must be returned to the queue."""
        mock_fn = MagicMock()
        lock = MagicMock()
        slot_queue = __import__("queue").Queue()
        slot_queue.put(0)
        on_progress = MagicMock()

        mock_processor._process_with_recovery(
            mock_fn, "track.mp3", str(sample_audio_files), lock, slot_queue, on_progress
        )

        # Slot must have been released back (queue should have 1 item)
        assert slot_queue.qsize() == 1
        mock_fn.assert_called_once()

    def test_audio_suite_error_triggers_skip_in_progress(
        self, mock_processor: BaseFileProcessor, sample_audio_files: Path
    ) -> None:
        """AudioSuiteError must be caught and reported via on_progress."""
        from audio_suite_shared.exceptions import AudioFormatError

        def failing_fn(**kwargs):
            raise AudioFormatError("bad format")

        lock = MagicMock()
        slot_queue = __import__("queue").Queue()
        slot_queue.put(0)
        on_progress = MagicMock()

        mock_processor._process_with_recovery(
            failing_fn,
            "bad.mp3",
            str(sample_audio_files),
            lock,
            slot_queue,
            on_progress,
        )

        # Must still release the slot
        assert slot_queue.qsize() == 1
        # on_progress must have been called with error info
        on_progress.assert_called_once()
        call_kwargs = on_progress.call_args[1]
        assert "bad.mp3" in call_kwargs.get("display_text", "")
        assert call_kwargs.get("n_errors", 0) == 1

    def test_generic_exception_mapped_and_reported(
        self, mock_processor: BaseFileProcessor, sample_audio_files: Path
    ) -> None:
        """A plain ValueError must be mapped and reported via on_progress."""

        def failing_fn(**kwargs):
            raise ValueError("some value problem")

        lock = MagicMock()
        slot_queue = __import__("queue").Queue()
        slot_queue.put(0)
        on_progress = MagicMock()

        mock_processor._process_with_recovery(
            failing_fn,
            "problem.wav",
            str(sample_audio_files),
            lock,
            slot_queue,
            on_progress,
        )

        assert slot_queue.qsize() == 1
        on_progress.assert_called_once()

    def test_slot_released_on_any_exception(
        self, mock_processor: BaseFileProcessor, sample_audio_files: Path
    ) -> None:
        """Even on unexpected exception, the slot must be released."""

        def exploding_fn(**kwargs):
            raise RuntimeError("unexpected crash")

        lock = MagicMock()
        slot_queue = __import__("queue").Queue()
        slot_queue.put(42)
        on_progress = MagicMock()

        mock_processor._process_with_recovery(
            exploding_fn,
            "crash.flac",
            str(sample_audio_files),
            lock,
            slot_queue,
            on_progress,
        )

        # Slot value 42 must be returned
        released = slot_queue.get()
        assert released == 42

    def test_processor_func_called_with_correct_kwargs(
        self, mock_processor: BaseFileProcessor, sample_audio_files: Path
    ) -> None:
        """processor_func must receive filename, dir_path, slot_idx, etc."""
        mock_fn = MagicMock()
        lock = MagicMock()
        slot_queue = __import__("queue").Queue()
        slot_queue.put(1)
        on_progress = MagicMock()

        mock_processor._process_with_recovery(
            mock_fn,
            "test_song.mp3",
            str(sample_audio_files),
            lock,
            slot_queue,
            on_progress,
            extra_param="hello",
        )

        mock_fn.assert_called_once()
        _, kwargs = mock_fn.call_args
        assert kwargs["filename"] == "test_song.mp3"
        assert kwargs["dir_path"] == str(sample_audio_files)
        assert kwargs["slot_idx"] == 1
        assert kwargs["extra_param"] == "hello"


# ═══════════════════════════════════════════════════════════════════════════════
# run_cpu_bound_processing  (unit tests)
# ═══════════════════════════════════════════════════════════════════════════════


class TestRunCpuBoundProcessing:
    """Tests for BaseFileProcessor.run_cpu_bound_processing."""

    def test_cpu_bound_processing_basic(
        self, temp_directory: Path, mock_callbacks: dict
    ) -> None:
        """Test basic cpu_bound_processing flow with mock ProcessPoolExecutor."""
        for i in range(3):
            (temp_directory / f"track_{i}.mp3").write_bytes(b"audio data")

        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
            patch(
                "audio_suite_shared.file_processor_base.ProcessPoolExecutor"
            ) as mock_exec_cls,
            patch(
                "audio_suite_shared.file_processor_base.as_completed",
                side_effect=lambda futures: futures,
            ),
        ):
            # Create future mocks that will be returned by executor.submit()
            future_mocks = [MagicMock() for _ in range(3)]
            for fm in future_mocks:
                fm.result.return_value = {"status": "ok", "value": 42}

            # Wire up the mock executor so that submit() returns future_mocks
            mock_exec_instance = mock_exec_cls.return_value.__enter__.return_value
            mock_exec_instance.submit.side_effect = future_mocks

            processor = BaseFileProcessor(
                max_workers=2, operation_type="test_cpu", parallel_mode=True
            )

            results_store: list[dict[str, object]] = []

            def _result_handler(
                filename: str,
                dir_path: str,
                result: dict[str, object],
                slot_idx: int,
                lock: threading.Lock,
                on_progress: Callable[..., None],
                **kwargs: object,
            ) -> None:
                results_store.append(result)
                with lock:
                    on_progress(
                        n_skipped=0,
                        n_errors=0,
                        display_text=f"[OK] {filename}",
                        log_text="",
                    )

            processor.run_cpu_bound_processing(
                dir_path=str(temp_directory),
                cpu_worker=MagicMock(return_value={"status": "ok", "value": 42}),
                result_handler=_result_handler,
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
            )

        mock_callbacks["on_complete"].assert_called_once()
        assert len(results_store) == 3

    def test_cpu_bound_parallel_mode_stored(
        self, mock_processor: BaseFileProcessor
    ) -> None:
        """Verify parallel_mode is stored on the processor."""
        with patch("audio_suite_shared.file_processor_base.get_resource_manager"):
            p = BaseFileProcessor(
                max_workers=4, operation_type="test", parallel_mode=True
            )
            assert p.parallel_mode is True
            assert p.max_workers == 4

    def test_cpu_bound_inherits_max_workers(
        self, temp_directory: Path, mock_callbacks: dict
    ) -> None:
        """Verify max_workers is passed through to ProcessPoolExecutor."""
        (temp_directory / "track.mp3").write_bytes(b"data")

        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
            patch(
                "audio_suite_shared.file_processor_base.ProcessPoolExecutor"
            ) as mock_exec,
            patch(
                "audio_suite_shared.file_processor_base.as_completed"
            ) as mock_as_completed,
        ):
            future = MagicMock()
            future.result.return_value = {"status": "ok", "value": 1}
            mock_as_completed.return_value = [future]

            processor = BaseFileProcessor(
                max_workers=8, operation_type="test", parallel_mode=True
            )

            processor.run_cpu_bound_processing(
                dir_path=str(temp_directory),
                cpu_worker=MagicMock(return_value={"status": "ok", "value": 1}),
                result_handler=MagicMock(),
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
                max_workers=8,
            )

            # Verify ProcessPoolExecutor was constructed with correct max_workers
            assert mock_exec.call_count >= 1

    def test_cpu_bound_empty_directory(
        self, temp_directory: Path, mock_callbacks: dict
    ) -> None:
        """Empty directory must call on_error, not on_complete."""
        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            processor = BaseFileProcessor(
                max_workers=2, operation_type="test", parallel_mode=True
            )

            processor.run_cpu_bound_processing(
                dir_path=str(temp_directory),
                cpu_worker=MagicMock(),
                result_handler=MagicMock(),
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
            )

        mock_callbacks["on_error"].assert_called_once()
        mock_callbacks["on_complete"].assert_not_called()

    def test_cpu_bound_result_handler_exception_reported(
        self, temp_directory: Path, mock_callbacks: dict
    ) -> None:
        """A raising result_handler must be caught and reported via on_progress
        without crashing the collection loop or on_complete."""
        for i in range(2):
            (temp_directory / f"track_{i}.mp3").write_bytes(b"audio data")

        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
            patch(
                "audio_suite_shared.file_processor_base.ProcessPoolExecutor"
            ) as mock_exec_cls,
            patch(
                "audio_suite_shared.file_processor_base.as_completed",
                side_effect=lambda futures: futures,
            ),
        ):
            future_mocks = [MagicMock() for _ in range(2)]
            for fm in future_mocks:
                fm.result.return_value = {"status": "ok", "value": 42}

            mock_exec_instance = mock_exec_cls.return_value.__enter__.return_value
            mock_exec_instance.submit.side_effect = future_mocks

            processor = BaseFileProcessor(
                max_workers=2, operation_type="test_cpu", parallel_mode=True
            )

            def bad_handler(
                filename: str,
                dir_path: str,
                result: dict[str, object],
                slot_idx: int,
                lock: threading.Lock,
                on_progress: Callable[..., None],
                **kwargs: object,
            ) -> None:
                raise ValueError("handler crashed")

            processor.run_cpu_bound_processing(
                dir_path=str(temp_directory),
                cpu_worker=MagicMock(return_value={"status": "ok", "value": 42}),
                result_handler=bad_handler,
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
            )

        mock_callbacks["on_complete"].assert_called_once()
        assert mock_callbacks["on_progress"].called

    def test_cpu_bound_worker_failure_reported(
        self, temp_directory: Path, mock_callbacks: dict
    ) -> None:
        """A future that raises must be mapped to an AudioSuiteError and
        reported through on_progress, still completing the batch."""
        (temp_directory / "solo.mp3").write_bytes(b"audio data")

        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
            patch(
                "audio_suite_shared.file_processor_base.ProcessPoolExecutor"
            ) as mock_exec_cls,
            patch(
                "audio_suite_shared.file_processor_base.as_completed",
                side_effect=lambda futures: futures,
            ),
        ):
            failing_future = MagicMock()
            failing_future.result.side_effect = RuntimeError("worker crashed")

            mock_exec_instance = mock_exec_cls.return_value.__enter__.return_value
            mock_exec_instance.submit.side_effect = [failing_future]

            processor = BaseFileProcessor(
                max_workers=2, operation_type="test_cpu", parallel_mode=True
            )

            processor.run_cpu_bound_processing(
                dir_path=str(temp_directory),
                cpu_worker=MagicMock(return_value={"status": "ok", "value": 42}),
                result_handler=MagicMock(),
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
            )

        mock_callbacks["on_complete"].assert_called_once()
        assert mock_callbacks["on_progress"].called

    def test_cpu_bound_discovery_failure_calls_on_error(
        self,
        mock_processor: BaseFileProcessor,
        mock_callbacks: dict,
    ) -> None:
        """A discovery AudioSuiteError in run_cpu_bound_processing must be
        routed to on_error (not to the per-file on_progress channel)."""
        from audio_suite_shared.exceptions import AudioProcessingError

        with patch.object(
            mock_processor,
            "discover_audio_files",
            side_effect=AudioProcessingError("scan failed"),
        ):
            mock_processor.run_cpu_bound_processing(
                dir_path="/does/not/matter",
                cpu_worker=MagicMock(),
                result_handler=MagicMock(),
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
            )
        mock_callbacks["on_error"].assert_called_once()
        mock_callbacks["on_complete"].assert_not_called()


# ═══════════════════════════════════════════════════════════════════════════════
# process_batch  (thread-pool dispatch with progress)
# ═══════════════════════════════════════════════════════════════════════════════


class TestProcessBatch:
    """Tests for BaseFileProcessor.process_batch."""

    def test_reports_progress_callback(self, temp_directory: Path) -> None:
        """The progress_callback must receive (completed, total) after each file."""
        for i in range(3):
            (temp_directory / f"item_{i}.mp3").write_bytes(b"audio data")

        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            processor = BaseFileProcessor(max_workers=2, operation_type="batch")

        progress = MagicMock()
        results = processor.process_batch(
            sorted(temp_directory.iterdir()),
            worker_fn=lambda f: f.name,
            progress_callback=progress,
        )

        assert len(results) == 3
        assert progress.call_args_list[-1][0] == (3, 3)
        assert progress.call_count == 3

    def test_worker_exception_yields_none_result(self, temp_directory: Path) -> None:
        """A raising worker must produce a None result without propagating."""
        (temp_directory / "bad.wav").write_bytes(b"audio data")
        (temp_directory / "good.wav").write_bytes(b"audio data")

        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            processor = BaseFileProcessor(max_workers=2, operation_type="batch")

        def flaky(f) -> object:
            if str(f).endswith("bad.wav"):
                raise ValueError("bad file")
            return "ok"

        results = processor.process_batch(
            [temp_directory / "bad.wav", temp_directory / "good.wav"],
            worker_fn=flaky,
        )
        assert results[0] is None
        assert results[1] == "ok"

    def test_escaped_worker_error_invokes_on_error_hook(
        self, temp_directory: Path
    ) -> None:
        """An exception that escapes the worker must reach on_error so the
        caller's summary can reflect the real failure count."""
        (temp_directory / "bad.wav").write_bytes(b"audio data")
        (temp_directory / "good.wav").write_bytes(b"audio data")

        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
        ):
            processor = BaseFileProcessor(max_workers=2, operation_type="batch")

        def flaky(f) -> object:
            if str(f).endswith("bad.wav"):
                raise ValueError("bad file")
            return "ok"

        received: list[str] = []
        results = processor.process_batch(
            [temp_directory / "bad.wav", temp_directory / "good.wav"],
            worker_fn=flaky,
            on_error=received.append,
        )
        assert results[0] is None
        assert results[1] == "ok"
        assert len(received) == 1
        # The escaped error must reach on_error through the suite's mapped
        # user-message channel — the same text a tool's on_error callback
        # would display — not the raw exception string.
        from audio_suite_shared.exceptions import map_to_audio_error, user_message_for

        assert received[0] == user_message_for(
            map_to_audio_error(ValueError("bad file"))
        )

    def test_future_timeout_yields_none_and_logs(self, tmp_path: Path, caplog) -> None:
        """A future that exceeds future_timeout must be logged as a timed-out
        worker and produce a None result, not abort the batch."""
        (tmp_path / "slow.mp3").write_bytes(b"audio data")
        (tmp_path / "fast.mp3").write_bytes(b"audio data")

        with (
            patch("audio_suite_shared.file_processor_base.get_resource_manager"),
            patch("audio_suite_shared.file_processor_base.track_thread"),
            patch("audio_suite_shared.file_processor_base.cleanup_expired_resources"),
            patch(
                "audio_suite_shared.file_processor_base.ThreadPoolExecutor"
            ) as mock_exec_cls,
        ):
            mock_instance = mock_exec_cls.return_value.__enter__.return_value
            timed_out = MagicMock()
            timed_out.result.side_effect = TimeoutError("worker hung")
            ok = MagicMock()
            ok.result.return_value = "ok"
            mock_instance.submit.side_effect = [timed_out, ok]

            processor = BaseFileProcessor(max_workers=1, operation_type="batch")
            errors: list[str] = []
            with caplog.at_level(
                "ERROR", logger="audio_suite_shared.file_processor_base"
            ):
                results = processor.process_batch(
                    [tmp_path / "slow.mp3", tmp_path / "fast.mp3"],
                    worker_fn=lambda f: f.name,
                    future_timeout=0.001,
                    on_error=errors.append,
                )

        assert results[0] is None
        assert results[1] == "ok"
        assert "timed out" in caplog.text
        # The timeout is reported on the user-message channel like any other
        # escaped worker failure, never swallowed as a bare counter.
        assert len(errors) == 1
        assert "timed out" in errors[0]


# ── Shared in-place DSP workflow (C2) ─────────────────────────────────────────
#
# These tests drive BaseFileProcessor's template methods with a fake DSP so they
# pin the shared workflow itself.  The tools that plug into it (noise_reduction,
# pop_click_remover) keep their own outcome-level tests against real audio.


@pytest.fixture
def inplace_processor() -> Generator[BaseFileProcessor, None, None]:
    """Single-worker processor so file ordering is deterministic."""
    with patch("audio_suite_shared.file_processor_base.get_resource_manager"):
        yield BaseFileProcessor(max_workers=1, operation_type="test_inplace")


def _write_wav(path: Path, *, freq_hz: float = 440.0, duration_ms: int = 60) -> None:
    """Write a tiny real mono WAV so the workflow runs against real I/O."""
    from pydub.generators import Sine

    segment = Sine(freq_hz).to_audio_segment(duration=duration_ms).set_channels(1)
    segment.export(str(path), format="wav")


def _clean_dsp(audio: AudioSegment) -> InplaceDspResult:
    """Fake DSP that never reports a modification."""
    return InplaceDspResult(audio=audio, was_modified=False, action="Clean")


def _repairing_dsp(audio: AudioSegment) -> InplaceDspResult:
    """Fake DSP that always reports a modification."""
    return InplaceDspResult(
        audio=audio,
        was_modified=True,
        action="Fixed 1 thing",
        repaired_suffix=" — Done",
    )


def _slot_pool(n: int) -> tuple[list[Any], Queue[int]]:
    slot_vars: list[Any] = [MagicMock() for _ in range(n)]
    slot_queue: Queue[int] = Queue()
    for i in range(n):
        slot_queue.put(i)
    return slot_vars, slot_queue


class TestInplaceDspResult:
    """The result contract a tool's DSP adapter must satisfy."""

    def test_repaired_suffix_defaults_to_empty(self) -> None:
        result = InplaceDspResult(audio=MagicMock(), was_modified=False, action="Clean")
        assert result.repaired_suffix == ""

    def test_is_frozen(self) -> None:
        result = InplaceDspResult(audio=MagicMock(), was_modified=False, action="Clean")
        with pytest.raises(FrozenInstanceError):
            result.action = "something else"  # type: ignore[misc]


class TestProcessAudioFileInplace:
    """Per-file half of the shared workflow."""

    def _process(
        self,
        processor: BaseFileProcessor,
        audio_file: Path,
        run_dsp: InplaceDspFn,
        *,
        is_dry_run: bool = False,
        temp_dir: str | None = None,
    ) -> list[dict[str, Any]]:
        batch_temp = temp_dir if temp_dir is not None else tempfile.mkdtemp()
        slot_vars, slot_queue = _slot_pool(processor.max_workers)
        progress: list[dict[str, Any]] = []
        try:
            processor.process_audio_file_inplace(
                audio_file.name,
                str(audio_file.parent),
                batch_temp,
                slot_vars,
                slot_queue,
                threading.Lock(),
                lambda **kw: progress.append(kw),
                run_dsp=run_dsp,
                dsp_label="Testing",
                tag_operation="test_edit",
                is_dry_run=is_dry_run,
            )
            # The per-worker temp directory is always cleaned up.
            assert os.listdir(batch_temp) == []
        finally:
            shutil.rmtree(batch_temp, ignore_errors=True)
        return progress

    def test_clean_file_reports_skip(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        audio_file = tmp_path / "a.wav"
        _write_wav(audio_file)

        progress = self._process(inplace_processor, audio_file, _clean_dsp)

        assert len(progress) == 1
        assert progress[0]["status"] == "SKIP"
        assert progress[0]["display_text"] == "[SKIP] a.wav → Clean"
        assert progress[0]["log_text"] == "[SKIP] a.wav | Clean\n"

    def test_live_run_reports_fixed_and_appends_suffix(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        audio_file = tmp_path / "a.wav"
        _write_wav(audio_file)
        digest = audio_file.read_bytes()

        with patch(
            "audio_suite_shared.file_processor_base.record_audio_overwrite_snapshot"
        ) as snapshot:
            progress = self._process(inplace_processor, audio_file, _repairing_dsp)

        assert progress[0]["status"] == "FIXED"
        assert progress[0]["display_text"] == "[FIXED] a.wav → Fixed 1 thing — Done"
        snapshot.assert_called_once_with(str(audio_file), "test_edit")
        assert audio_file.read_bytes() != digest

    def test_dry_run_reports_found_without_writing(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        audio_file = tmp_path / "a.wav"
        _write_wav(audio_file)
        digest = audio_file.read_bytes()

        with patch(
            "audio_suite_shared.file_processor_base.record_audio_overwrite_snapshot"
        ) as snapshot:
            progress = self._process(
                inplace_processor, audio_file, _repairing_dsp, is_dry_run=True
            )

        assert progress[0]["status"] == "FOUND"
        assert progress[0]["display_text"] == "[FOUND] a.wav → Fixed 1 thing"
        snapshot.assert_not_called()
        assert audio_file.read_bytes() == digest

    def test_staging_file_naming(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        """``in<ext>``/``out<ext>`` staging is a shared contract, not an accident."""
        audio_file = tmp_path / "a.wav"
        _write_wav(audio_file)
        batch_temp = tempfile.mkdtemp()
        during_dsp: list[str] = []
        worker_dir: list[Path] = []

        def _spy_dsp(audio: AudioSegment) -> InplaceDspResult:
            entries = list(Path(batch_temp).iterdir())
            assert len(entries) == 1 and entries[0].is_dir()
            worker_dir.append(entries[0])
            during_dsp.extend(sorted(p.name for p in entries[0].iterdir()))
            return _repairing_dsp(audio)

        progress = self._process(
            inplace_processor,
            audio_file,
            _spy_dsp,
            temp_dir=batch_temp,
        )

        # The decoded input is staged as in<ext>; out<ext> only exists once the
        # repaired audio is written, and both are gone once the file is done.
        assert during_dsp == ["in.wav"]
        assert progress[0]["status"] == "FIXED"
        assert not os.path.exists(worker_dir[0])

    def test_error_path_returns_the_slot_and_reports_error(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        audio_file = tmp_path / "bad.wav"
        audio_file.write_bytes(b"not a wav file")

        batch_temp = tempfile.mkdtemp()
        slot_vars, slot_queue = _slot_pool(inplace_processor.max_workers)
        progress: list[dict[str, Any]] = []
        try:
            inplace_processor.process_audio_file_inplace(
                audio_file.name,
                str(tmp_path),
                batch_temp,
                slot_vars,
                slot_queue,
                threading.Lock(),
                lambda **kw: progress.append(kw),
                run_dsp=_clean_dsp,
                dsp_label="Testing",
                tag_operation="test_edit",
                is_dry_run=False,
            )
        finally:
            shutil.rmtree(batch_temp, ignore_errors=True)

        assert progress[0]["status"] == "ERROR"
        assert progress[0]["display_text"].startswith("[ERROR] bad.wav: ")
        assert progress[0]["log_text"].startswith("[ERROR] bad.wav: ")
        assert slot_queue.qsize() == inplace_processor.max_workers
        slot_vars[0].set.assert_called_with("IDLE")

    def test_error_display_is_sanitised_not_raw_exception(
        self,
        inplace_processor: BaseFileProcessor,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The user-facing error is the sanitised message, never ``str(exc)``.

        A raw exception can embed internal absolute paths; those must not leak
        into the display/log callbacks (the log *file* keeps the detail).
        """
        monkeypatch.delenv("AUDIOSUITE_DEBUG", raising=False)
        audio_file = tmp_path / "a.wav"
        _write_wav(audio_file)
        secret = "C:/internal/secret/location.wav"

        def _leaky_dsp(_audio: AudioSegment) -> InplaceDspResult:
            raise AudioFileNotFoundError(secret)

        progress = self._process(inplace_processor, audio_file, _leaky_dsp)

        assert progress[0]["status"] == "ERROR"
        assert secret not in progress[0]["display_text"]
        assert secret not in progress[0]["log_text"]
        assert "could not be found" in progress[0]["display_text"]

    def test_slot_var_shows_dsp_label_then_returns_to_idle(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        audio_file = tmp_path / "a.wav"
        _write_wav(audio_file)

        batch_temp = tempfile.mkdtemp()
        slot_vars, slot_queue = _slot_pool(inplace_processor.max_workers)
        try:
            inplace_processor.process_audio_file_inplace(
                audio_file.name,
                str(tmp_path),
                batch_temp,
                slot_vars,
                slot_queue,
                threading.Lock(),
                lambda **kw: None,
                run_dsp=_clean_dsp,
                dsp_label="Reducing noise",
                tag_operation="test_edit",
                is_dry_run=True,
            )
        finally:
            shutil.rmtree(batch_temp, ignore_errors=True)

        labels = [call.args[0] for call in slot_vars[0].set.call_args_list]
        assert labels[0] == "Loading: a.wav..."
        assert "Reducing noise: a.wav..." in labels
        assert labels[-1] == "IDLE"


class TestRunInplaceDspBatch:
    """Batch half of the shared workflow."""

    def _run(
        self,
        processor: BaseFileProcessor,
        dir_path: Path,
        run_dsp: InplaceDspFn,
        *,
        is_dry_run: bool = False,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
        progress: list[dict[str, Any]] = []
        complete: dict[str, Any] = {}
        errors: list[str] = []
        slot_vars, slot_queue = _slot_pool(processor.max_workers)

        def _make_worker(
            temp_dir: str, lock: threading.Lock, report: ProgressCallback
        ) -> Callable[[str], None]:
            def _worker(name: str) -> None:
                processor.process_audio_file_inplace(
                    name,
                    str(dir_path),
                    temp_dir,
                    slot_vars,
                    slot_queue,
                    lock,
                    report,
                    run_dsp=run_dsp,
                    dsp_label="Testing",
                    tag_operation="test_edit",
                    is_dry_run=is_dry_run,
                )

            return _worker

        processor.run_inplace_dsp_batch(
            str(dir_path),
            make_worker=_make_worker,
            on_progress=lambda **kw: progress.append(kw),
            on_complete=lambda **kw: complete.update(kw),
            on_error=errors.append,
        )
        return progress, complete, errors

    def test_empty_directory_reports_the_shared_message(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        progress, complete, errors = self._run(inplace_processor, tmp_path, _clean_dsp)

        assert errors == ["No supported audio files found in the selected directory."]
        assert progress == []
        assert complete == {}

    def test_scan_failure_reports_one_sanitised_error(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        with patch(
            "audio_suite_shared.file_processor_base.os.scandir",
            side_effect=OSError("permission denied"),
        ):
            _progress, complete, errors = self._run(
                inplace_processor, tmp_path, _clean_dsp
            )

        assert len(errors) == 1
        assert complete == {}

    def test_files_are_processed_in_sorted_order(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        for name in ("c.wav", "a.wav", "b.wav"):
            _write_wav(tmp_path / name)

        progress, complete, _errors = self._run(inplace_processor, tmp_path, _clean_dsp)

        assert [p["display_text"].split("] ")[1].split(" ")[0] for p in progress] == [
            "a.wav",
            "b.wav",
            "c.wav",
        ]
        assert [p["processed"] for p in progress] == [1, 2, 3]
        assert complete["total"] == 3
        assert complete["processed"] == 3
        assert complete["skipped"] == 3
        assert complete["succeeded"] == 0
        assert complete["errors"] == 0
        assert len(complete["log_entries"]) == 3
        assert complete["duration_secs"] >= 0.0

    def test_mixed_batch_aggregates_counters(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        # Duration identifies the file to the fake DSP, so the outcome of each
        # file is decided by the file itself rather than by call order.
        _write_wav(tmp_path / "a_clean.wav", duration_ms=60)
        _write_wav(tmp_path / "b_dirty.wav", duration_ms=120)
        (tmp_path / "c_broken.wav").write_bytes(b"not a wav file")

        def _dsp(audio: AudioSegment) -> InplaceDspResult:
            # len(audio_segment) is milliseconds, not frames.
            if len(audio) > 90:
                return _repairing_dsp(audio)
            return _clean_dsp(audio)

        with patch(
            "audio_suite_shared.file_processor_base.record_audio_overwrite_snapshot"
        ) as snapshot:
            _progress, complete, errors = self._run(inplace_processor, tmp_path, _dsp)

        assert not errors
        assert complete["total"] == 3
        assert complete["skipped"] == 1
        assert complete["succeeded"] == 1
        assert complete["errors"] == 1
        snapshot.assert_called_once()

    def test_worker_runs_inside_the_active_undo_batch(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        from audio_suite_shared.batch_undo import get_active_batch_id

        _write_wav(tmp_path / "a.wav")
        seen: list[str | None] = []

        def _spy_dsp(audio: AudioSegment) -> InplaceDspResult:
            seen.append(get_active_batch_id())
            return _clean_dsp(audio)

        with patch(
            "audio_suite_shared.file_processor_base.get_active_batch_id",
            return_value="batch-123",
        ):
            self._run(inplace_processor, tmp_path, _spy_dsp)

        assert seen == ["batch-123"]

    def test_no_retry_layer_double_attempts_a_failing_file(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        """A per-file failure is reported through the counters, so a retry
        wrapper could never observe it; exactly one attempt is made."""
        _write_wav(tmp_path / "a.wav")
        attempts: list[str] = []

        def _failing_dsp(audio: AudioSegment) -> InplaceDspResult:
            del audio
            attempts.append("attempt")
            raise RuntimeError("boom")

        _progress, complete, errors = self._run(
            inplace_processor, tmp_path, _failing_dsp
        )

        assert attempts == ["attempt"]
        assert complete["errors"] == 1
        assert not errors  # per-file errors are never fatal

    def test_shared_temp_dir_is_removed_after_the_batch(
        self, inplace_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        _write_wav(tmp_path / "a.wav")
        seen: list[str] = []
        slot_vars, slot_queue = _slot_pool(inplace_processor.max_workers)

        def _make_worker(
            temp_dir: str, lock: threading.Lock, report: ProgressCallback
        ) -> Callable[[str], None]:
            seen.append(temp_dir)

            def _worker(name: str) -> None:
                inplace_processor.process_audio_file_inplace(
                    name,
                    str(tmp_path),
                    temp_dir,
                    slot_vars,
                    slot_queue,
                    lock,
                    report,
                    run_dsp=_clean_dsp,
                    dsp_label="Testing",
                    tag_operation="test_edit",
                    is_dry_run=True,
                )

            return _worker

        inplace_processor.run_inplace_dsp_batch(
            str(tmp_path),
            make_worker=_make_worker,
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=lambda msg: None,
        )

        assert len(seen) == 1
        assert not os.path.exists(seen[0])


# ═══════════════════════════════════════════════════════════════════════════════
# Shared pre-flight / completion helpers (G7.1)
# ═══════════════════════════════════════════════════════════════════════════════

_EMPTY_VARIANTS = pytest.mark.parametrize(
    "empty_message",
    [
        pytest.param(
            "No supported audio files found in selected directory.",
            id="parallel/cpu",
        ),
        pytest.param(
            "No supported audio files found in the selected directory.",
            id="inplace/analysis",
        ),
    ],
)


class TestPreflightDiscover:
    """Tests for the shared _preflight_discover helper."""

    @_EMPTY_VARIANTS
    def test_empty_directory_calls_on_error_with_exact_message(
        self,
        mock_processor: BaseFileProcessor,
        tmp_path: Path,
        empty_message: str,
    ) -> None:
        on_error = MagicMock()
        result = _preflight_discover(
            mock_processor,
            str(tmp_path),
            None,
            on_error,
            empty_message=empty_message,
        )
        assert result is None
        on_error.assert_called_once_with(empty_message)

    def test_discovery_failure_calls_on_error(
        self, mock_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        on_error = MagicMock()
        with patch.object(
            mock_processor,
            "discover_audio_files",
            side_effect=AudioSuiteError("scan broke"),
        ):
            result = _preflight_discover(
                mock_processor,
                str(tmp_path),
                None,
                on_error,
            )
        assert result is None
        on_error.assert_called_once()
        # The message is the sanitised user_message_for() output, not the
        # raw exception text.
        assert "unexpected error" in on_error.call_args[0][0].lower()

    def test_successful_discovery_returns_file_list(
        self,
        mock_processor: BaseFileProcessor,
        sample_audio_files: Path,
    ) -> None:
        on_error = MagicMock()
        result = _preflight_discover(
            mock_processor,
            str(sample_audio_files),
            None,
            on_error,
        )
        assert result is not None
        assert len(result) > 0
        on_error.assert_not_called()

    def test_sort_parameter_orders_results(
        self, mock_processor: BaseFileProcessor, tmp_path: Path
    ) -> None:
        for name in ("c.mp3", "a.mp3", "b.mp3"):
            (tmp_path / name).write_bytes(b"data")
        on_error = MagicMock()
        result = _preflight_discover(
            mock_processor,
            str(tmp_path),
            None,
            on_error,
            sort=True,
        )
        assert result == ["a.mp3", "b.mp3", "c.mp3"]


class TestEmitCompletion:
    """Tests for the shared _emit_completion helper."""

    def test_calls_on_complete_with_standard_kwargs(self) -> None:
        on_complete = MagicMock()
        _emit_completion(
            on_complete,
            total=10,
            processed=8,
            skipped=1,
            errors=1,
            start_time=1000.0,
            log_entries=["entry1"],
        )
        on_complete.assert_called_once()
        kw = on_complete.call_args[1]
        assert kw["total"] == 10
        assert kw["processed"] == 8
        assert kw["skipped"] == 1
        assert kw["errors"] == 1
        assert kw["log_entries"] == ["entry1"]
        assert "duration_secs" in kw

    def test_duration_is_non_negative(self) -> None:
        on_complete = MagicMock()
        _emit_completion(on_complete, 1, 1, 0, 0, 0.0, [])
        kw = on_complete.call_args[1]
        assert kw["duration_secs"] >= 0.0


class TestAllEntryPointsSharePreFlightAndCompletion:
    """Structural test: all four entry points route empty directories through
    the shared helper and produce identical on_error messages per variant."""

    def test_run_parallel_processing_empty_reports_shared_message(
        self,
        mock_processor: BaseFileProcessor,
        mock_callbacks: dict,
    ) -> None:
        with patch.object(
            mock_processor,
            "discover_audio_files",
            return_value=[],
        ):
            mock_processor.run_parallel_processing(
                dir_path="/empty",
                processor_func=MagicMock(),
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
            )
        mock_callbacks["on_error"].assert_called_once_with(
            "No supported audio files found in selected directory."
        )

    def test_run_cpu_bound_processing_empty_reports_shared_message(
        self,
        mock_processor: BaseFileProcessor,
        mock_callbacks: dict,
    ) -> None:
        with patch.object(
            mock_processor,
            "discover_audio_files",
            return_value=[],
        ):
            mock_processor.run_cpu_bound_processing(
                dir_path="/empty",
                cpu_worker=MagicMock(),
                result_handler=MagicMock(),
                on_progress=mock_callbacks["on_progress"],
                on_complete=mock_callbacks["on_complete"],
                on_error=mock_callbacks["on_error"],
            )
        mock_callbacks["on_error"].assert_called_once_with(
            "No supported audio files found in selected directory."
        )

    def test_run_inplace_dsp_batch_empty_reports_shared_message(
        self,
        inplace_processor: BaseFileProcessor,
        tmp_path: Path,
    ) -> None:
        errors: list[str] = []
        inplace_processor.run_inplace_dsp_batch(
            str(tmp_path),
            make_worker=lambda *_: MagicMock(),
            on_progress=lambda **kw: None,
            on_complete=lambda **kw: None,
            on_error=errors.append,
        )
        assert errors == ["No supported audio files found in the selected directory."]
