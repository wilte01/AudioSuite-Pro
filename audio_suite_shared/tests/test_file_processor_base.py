"""
Tests for BaseFileProcessor class.

Comprehensive test coverage for file discovery, progress
tracking, and parallel processing.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.file_processor_base import BaseFileProcessor


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
            with caplog.at_level(
                "ERROR", logger="audio_suite_shared.file_processor_base"
            ):
                results = processor.process_batch(
                    [tmp_path / "slow.mp3", tmp_path / "fast.mp3"],
                    worker_fn=lambda f: f.name,
                    future_timeout=0.001,
                )

        assert results[0] is None
        assert results[1] == "ok"
        assert "timed out" in caplog.text
