"""
parallel_pool.py - part of BaseFileProcessor, split out in 2.4.3.

WP-9 #2 moved this group of methods off :class:`BaseFileProcessor` into
``ParallelPoolMixin``. Method bodies are unchanged, and ``file_processor_base``
still re-exports every public name, so existing importers are
unaffected.

Changed in 2.4.3: split out of ``audio_suite_shared.file_processor_base``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from queue import Queue
from typing import Any, Callable, TypeVar

from .constants import (
    CPU_WORKER_TIMEOUT_SECS,
    WORKER_TIMEOUT_SECS,
    cap_workers_to_slot_grid,
)
from .error_recovery import (
    RecoveryAction,
    RetryConfig,
    get_recovery_action,
    retry_with_backoff,
)
from .exceptions import (
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from .reporting import (
    CompleteCallback,
    ErrorCallback,
    ProgressCallback,
    _emit_completion,
    _preflight_discover,
)
from .resource_manager import track_thread

logger = logging.getLogger(f"audio_suite.{__name__}")

_T = TypeVar("_T")


class ParallelPoolMixin:
    """The two executor loops (threads and processes) and their recovery."""

    #: Host surface provided by ``BaseFileProcessor``'s other mixins.
    max_workers: int
    operation_type: str
    create_progress_tracker: Callable[..., Any]
    create_retry_config: Callable[..., RetryConfig]

    def discover_audio_files(
        self, dir_path: str, extensions: tuple[str, ...] | None = None
    ) -> list[str]:
        """Provided by ``FileDiscoveryMixin``, composed ahead of this one."""
        raise NotImplementedError

    @handle_audio_errors(reraise=False, context="run_parallel_processing")
    def run_parallel_processing(
        self,
        dir_path: str,
        processor_func: Callable[..., None],
        on_progress: ProgressCallback,
        on_complete: CompleteCallback,
        on_error: ErrorCallback,
        extensions: tuple[str, ...] | None = None,
        **processor_kwargs: Any,
    ) -> None:
        """
        Execute parallel file processing with standardised infrastructure.

        on_error() receives a sanitised user_message_for() string — never
        a raw str(exc) with internal path or traceback details.
        """
        files = _preflight_discover(self, dir_path, extensions, on_error)
        if files is None:
            return

        processed, skipped, errors, log_entries, _on_progress = (
            self.create_progress_tracker(on_progress, len(files))
        )

        # Never open a pool wider than the slot grid: each worker takes its
        # index from this queue, and the progress write would index past the
        # end of slot_vars (D66).
        effective_workers = cap_workers_to_slot_grid(
            self.max_workers, processor_kwargs.get("slot_vars")
        )
        if effective_workers != self.max_workers:
            logger.warning(
                "%s: %d workers requested but the slot grid holds %d; capping the pool",
                self.operation_type,
                self.max_workers,
                effective_workers,
            )

        slot_queue: Queue[int] = Queue()
        for i in range(effective_workers):
            slot_queue.put(i)

        lock = threading.Lock()
        start_time = time.time()

        main_thread = threading.current_thread()
        track_thread(main_thread, f"{self.operation_type}_main")

        # KEEP-IN-SYNC: run_cpu_bound_processing, run_inplace_dsp_batch,
        # run_analysis_workflow — the executor loops are intentionally
        # ununified (D5) because each uses a different pool/process model.
        with ThreadPoolExecutor(max_workers=effective_workers) as executor:
            futures = [
                executor.submit(
                    self._process_with_recovery,
                    processor_func,
                    name,
                    dir_path,
                    lock,
                    slot_queue,
                    _on_progress,
                    **processor_kwargs,
                )
                for name in files
            ]
            for f in futures:
                try:
                    f.result(timeout=WORKER_TIMEOUT_SECS)
                except TimeoutError:
                    logger.error(
                        "Worker timed out after %ss in %s",
                        WORKER_TIMEOUT_SECS,
                        self.operation_type,
                        exc_info=True,
                    )
                    with lock:
                        _on_progress(
                            n_skipped=0,
                            n_errors=1,
                            display_text=(
                                f"[TIMEOUT] Worker timed out after"
                                f" {WORKER_TIMEOUT_SECS}s"
                            ),
                            log_text=(
                                f"[TIMEOUT] Worker timed out after"
                                f" {WORKER_TIMEOUT_SECS}s\n"
                            ),
                        )

        _emit_completion(
            on_complete,
            len(files),
            processed[0],
            skipped[0],
            errors[0],
            start_time,
            log_entries,
        )

    @handle_audio_errors(reraise=False, context="run_cpu_bound_processing")
    def run_cpu_bound_processing(
        self,
        dir_path: str,
        cpu_worker: Callable[..., dict[str, object]],
        result_handler: Callable[..., None],
        on_progress: ProgressCallback,
        on_complete: CompleteCallback,
        on_error: ErrorCallback,
        extensions: tuple[str, ...] | None = None,
        max_workers: int | None = None,
        **worker_kwargs: object,
    ) -> None:
        """
        Execute CPU-bound file processing using ProcessPoolExecutor.

        This method is designed for DSP-heavy stages (FFT, spectrogram, pitch
        detection) that benefit from bypassing the GIL.  The CPU worker runs
        in a separate process; the result handler runs in the main process
        thread for I/O (tag writing, progress reporting).

        Args:
            dir_path: Directory of audio files to process.
            cpu_worker: Top-level picklable function that performs CPU-heavy
                work. Must accept ``(file_path, **worker_kwargs)`` and return
                a dict with at least ``{"status": "ok" | "error"}``.
            result_handler: Called in the main thread for each CPU result.
                Signature: ``(filename, dir_path, result_dict, slot_idx,
                lock, on_progress, **worker_kwargs)``.  Responsible for I/O
                and progress callbacks.
            on_progress: Progress callback forwarded to result_handler.
            on_complete: Completion callback after all files are processed.
            on_error: Error callback on fatal failures.
            extensions: Audio file extensions to scan for.
            max_workers: Max process-pool workers.  Defaults to
                ``self.max_workers``.
            **worker_kwargs: Forwarded to both cpu_worker and result_handler.
        """
        files = _preflight_discover(self, dir_path, extensions, on_error)
        if files is None:
            return

        processed, skipped, errors, log_entries, _on_progress = (
            self.create_progress_tracker(on_progress, len(files))
        )

        lock = threading.Lock()
        start_time = time.time()
        effective_workers = cap_workers_to_slot_grid(
            max_workers or self.max_workers, worker_kwargs.get("slot_vars")
        )

        def _safe_result_handler(
            filename: str,
            result: dict[str, object],
            slot_idx: int,
        ) -> None:
            """Wrap result_handler so that any exception in the handler is
            caught and reported rather than crashing the collection loop."""
            try:
                result_handler(
                    filename=filename,
                    dir_path=dir_path,
                    result=result,
                    slot_idx=slot_idx,
                    lock=lock,
                    on_progress=_on_progress,
                    **worker_kwargs,
                )
            except Exception as exc:
                mapped = map_to_audio_error(
                    exc, context={"file": filename, "operation": self.operation_type}
                )
                logger.error(
                    "[%s] Result-handler error on %s: %s",
                    type(mapped).__name__,
                    filename,
                    mapped,
                    exc_info=True,
                )
                with lock:
                    _on_progress(
                        n_skipped=0,
                        n_errors=1,
                        display_text=f"[ERROR] {filename}: {user_message_for(mapped)}",
                        log_text=f"[ERROR] {filename}: {mapped}\n",
                    )

        pool_kwargs = {
            k: v
            for k, v in worker_kwargs.items()
            if k not in ("slot_vars", "slot_queue", "lock", "on_progress")
        }

        slot_counter = 0
        # KEEP-IN-SYNC: run_parallel_processing, run_inplace_dsp_batch,
        # run_analysis_workflow — the executor loops are intentionally
        # ununified (D5) because each uses a different pool/process model.
        with ProcessPoolExecutor(max_workers=effective_workers) as executor:
            future_to_file = {
                executor.submit(
                    cpu_worker,
                    os.path.join(dir_path, name),
                    **pool_kwargs,
                ): name
                for name in files
            }
            for future in as_completed(list(future_to_file.keys())):
                filename = future_to_file[future]
                slot_idx = slot_counter % effective_workers
                slot_counter += 1
                try:
                    result = future.result(timeout=CPU_WORKER_TIMEOUT_SECS)
                except Exception as exc:
                    mapped = map_to_audio_error(
                        exc,
                        context={
                            "file": filename,
                            "operation": self.operation_type,
                        },
                    )
                    logger.error(
                        "[%s] CPU worker failed on %s: %s",
                        type(mapped).__name__,
                        filename,
                        mapped,
                        exc_info=True,
                    )
                    with lock:
                        _on_progress(
                            n_skipped=0,
                            n_errors=1,
                            display_text=(
                                f"[ERROR] {filename}: {user_message_for(mapped)}"
                            ),
                            log_text=f"[ERROR] {filename}: {mapped}\n",
                        )
                else:
                    _safe_result_handler(filename, result, slot_idx)

        _emit_completion(
            on_complete,
            len(files),
            processed[0],
            skipped[0],
            errors[0],
            start_time,
            log_entries,
        )

    def _process_with_recovery(
        self,
        processor_func: Callable[..., None],
        filename: str,
        dir_path: str,
        lock: threading.Lock,
        slot_queue: "Queue[int]",
        on_progress: Callable[..., None],
        **processor_kwargs: Any,
    ) -> None:
        """
        Process a single file with error recovery and slot management.

        Catches AudioSuiteError (domain hierarchy) before the broad OSError
        family so callers see the precise type. Always logs with exc_info=True.
        Slot is always released in finally — a raised exception can never starve
        the thread pool.
        """
        slot_idx = slot_queue.get()
        safe_name = filename.replace(" ", "_").replace("-", "_")

        try:
            retry_config = self.create_retry_config()

            retry_with_backoff(
                lambda: processor_func(
                    filename=filename,
                    dir_path=dir_path,
                    slot_idx=slot_idx,
                    lock=lock,
                    on_progress=on_progress,
                    **processor_kwargs,
                ),
                retry_config,
                f"{self.operation_type}_{safe_name}",
            )

        except AudioSuiteError as exc:
            logger.error(
                "[%s] %s failed on %s: %s",
                type(exc).__name__,
                self.operation_type,
                filename,
                exc.message,
                exc_info=True,
            )
            action = get_recovery_action(exc.original or exc, self.operation_type)
            clean_msg = user_message_for(exc)
            prefix = "[SKIP]" if action == RecoveryAction.SKIP else "[ERROR]"
            n_skip = 1 if action == RecoveryAction.SKIP else 0
            n_err = 0 if action == RecoveryAction.SKIP else 1
            with lock:
                on_progress(
                    n_skipped=n_skip,
                    n_errors=n_err,
                    display_text=f"{prefix} {filename}: {clean_msg}",
                    log_text=f"{prefix} {filename}: {clean_msg}\n",
                )

        except Exception as exc:
            mapped = map_to_audio_error(exc, context={"file": filename})
            logger.error(
                "[%s] Unexpected error in %s on %s: %s",
                type(mapped).__name__,
                self.operation_type,
                filename,
                mapped,
                exc_info=True,
            )
            action = get_recovery_action(exc, self.operation_type)
            clean_msg = user_message_for(mapped)
            prefix = "[SKIP]" if action == RecoveryAction.SKIP else "[ERROR]"
            n_skip = 1 if action == RecoveryAction.SKIP else 0
            n_err = 0 if action == RecoveryAction.SKIP else 1
            with lock:
                on_progress(
                    n_skipped=n_skip,
                    n_errors=n_err,
                    display_text=f"{prefix} {filename}: {clean_msg}",
                    log_text=f"{prefix} {filename}: {clean_msg}\n",
                )

        finally:
            slot_queue.put(slot_idx)

    def run_with_retry(
        self,
        func: Callable[[], _T],
        *,
        max_retries: int = 3,
        base_delay: float = 1.0,
        label: str = "",
    ) -> _T:
        """Wrap a callable with retry_with_backoff using default retry config.

        Args:
            func: Zero-argument callable to retry.
            max_retries: Maximum retry attempts (default 3).
            base_delay: Initial delay in seconds (default 1.0).
            label: Human-readable label for the operation (for logging).

        Returns:
            The return value of func if it succeeds.

        Raises:
            The last exception raised by func after all retries are exhausted.
        """
        config = RetryConfig(
            max_retries=max_retries,
            retry_delay=base_delay,
            backoff_factor=2.0,
            retry_on_exceptions=[IOError, OSError, PermissionError],
        )
        return retry_with_backoff(func, config, label)
