"""
file_processor_base.py — Base file processor class for Audio Suite applications.

Provides common infrastructure for parallel file processing, eliminating duplication
across multiple applications while preserving all existing functionality.

Changed in 2.1.7: in-place writes pass ``preserve_depth_params``, so a lossless
source keeps its bit depth instead of falling back to FFmpeg's 16-bit default
(F-10).

Changed in 1.0.1: the in-place error path now reports
``user_message_for(map_to_audio_error(exc))`` instead of the raw ``str(exc)``,
so internal paths/details no longer leak into the display and log callbacks.

Changed in 1.1.0: the shared in-place DSP workflow now skips read-only formats before
any decode or write.

Changed in 1.4.0: ``max_workers`` defaults to ``None`` and resolves through
``default_max_workers()``, so the pool sizes itself from the host instead of
freezing at an import-time 4.

Changed in 2.4.3: split into ``file_discovery`` (discovery), ``parallel_pool``
(the two pool loops and their per-file recovery), ``inplace_workflow`` (the
in-place DSP batch and its result type) and ``reporting`` (progress tracker,
retry config and completion payload). ``BaseFileProcessor`` composes the four
mixins and keeps ``process_batch``/``run_analysis_workflow``; every moved name
is re-exported here (PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from typing import Any, TypeVar

from .batch_undo import get_active_batch_id, use_batch
from .constants import cap_workers_to_slot_grid, default_max_workers
from .exceptions import map_to_audio_error, user_message_for
from .file_discovery import FileDiscoveryMixin as FileDiscoveryMixin
from .inplace_workflow import InplaceDspFn as InplaceDspFn
from .inplace_workflow import InplaceDspResult as InplaceDspResult
from .inplace_workflow import InplaceWorkerFactory as InplaceWorkerFactory
from .inplace_workflow import InplaceWorkflowMixin as InplaceWorkflowMixin
from .parallel_pool import ParallelPoolMixin as ParallelPoolMixin
from .reporting import CompleteCallback as CompleteCallback
from .reporting import ErrorCallback as ErrorCallback
from .reporting import ProgressCallback as ProgressCallback
from .reporting import ReportingMixin as ReportingMixin
from .reporting import _emit_completion, _preflight_discover
from .resource_manager import get_resource_manager, track_thread

logger = logging.getLogger(f"audio_suite.{__name__}")

_T = TypeVar("_T")


class BaseFileProcessor(
    ReportingMixin,
    FileDiscoveryMixin,
    ParallelPoolMixin,
    InplaceWorkflowMixin,
):
    """
    Base class for file processing operations across Audio Suite applications.

    Eliminates common duplication in threading, progress tracking, and error handling
    while maintaining compatibility with existing callback interfaces.  The four
    mixins supply discovery, the executor loops, the in-place DSP batch and the
    reporting helpers; this class composes them and owns ``process_batch``.
    """

    def __init__(
        self,
        max_workers: int | None = None,
        operation_type: str = "file_processing",
        parallel_mode: bool = False,
    ):
        self.max_workers = (
            max_workers if max_workers is not None else default_max_workers()
        )
        self.operation_type = operation_type
        self.parallel_mode = parallel_mode
        self.resource_manager = get_resource_manager()

    def process_batch(
        self,
        files: list[_T],
        worker_fn: Callable[[_T], object],
        *,
        max_workers: int | None = None,
        future_timeout: float | None = None,
        progress_callback: Callable[[int, int], None] | None = None,
        on_error: Callable[[str], None] | None = None,
    ) -> list[object]:
        """Thread-pool dispatch with progress tracking, shared by all tools.

        Processes a list of items in parallel using a ThreadPoolExecutor.
        Each item is passed to worker_fn as a single positional argument.

        Args:
            files: List of items to process (Paths, filenames, or tool-defined
                job objects).
            worker_fn: Callable that accepts a single item of the same type as
                ``files`` and returns a result. The worker is responsible for
                its own error handling.
            max_workers: Max thread pool workers. Defaults to self.max_workers.
            future_timeout: Per-future timeout in seconds.  On expiry the
                future raises ``concurrent.futures.TimeoutError`` (the builtin
                ``TimeoutError``, an ``OSError`` subclass since Python 3.11 —
                not the fictional ``concurrent.futures.TimeoutExpired``), which
                is explicitly caught, logged as a timed-out worker, and turned
                into a ``None`` result without abandoning the batch.  ``None``
                (the default) blocks until each worker finishes.
            progress_callback: Optional callback invoked after each file
                completes, with ``(completed, total)``.
            on_error: Optional callback invoked with a human-readable message
                whenever a worker raises an exception that escapes (i.e. the
                worker did not catch its own failure) or times out.  Most
                workers self-report per-file progress; this hook lets a caller
                feed escaped errors back into its progress/summary counters so
                ``on_complete`` reflects real failures instead of a padded
                "all done" count.

        Returns:
            List of results from worker_fn, one per file, in submission order.
        """
        n_total = len(files)
        results: list[object] = []
        completed = [0]

        with ThreadPoolExecutor(max_workers=max_workers or self.max_workers) as pool:
            futures = [pool.submit(worker_fn, f) for f in files]
            for f in futures:
                try:
                    result = f.result(timeout=future_timeout)
                except TimeoutError as exc:
                    mapped = map_to_audio_error(
                        exc, context={"operation": self.operation_type}
                    )
                    logger.error(
                        "[%s] Worker timed out after %ss in %s",
                        type(mapped).__name__,
                        future_timeout,
                        self.operation_type,
                        exc_info=True,
                    )
                    if on_error is not None:
                        on_error(
                            f"Worker timed out after {future_timeout}s"
                            f" in {self.operation_type}: "
                            f"{user_message_for(mapped)}"
                        )
                    result = None
                except Exception as exc:
                    mapped = map_to_audio_error(
                        exc, context={"operation": self.operation_type}
                    )
                    logger.error(
                        "[%s] Worker error in %s: %s",
                        type(mapped).__name__,
                        self.operation_type,
                        mapped,
                        exc_info=True,
                    )
                    if on_error is not None:
                        on_error(user_message_for(mapped))
                    result = None
                results.append(result)
                completed[0] += 1
                if progress_callback:
                    progress_callback(completed[0], n_total)

        return results


def run_analysis_workflow(
    processor: BaseFileProcessor,
    dir_path: str,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: Callable[[int, int, int, int, str], None],
    on_complete: CompleteCallback,
    on_error: ErrorCallback,
    *,
    extensions: tuple[str, ...],
    is_dry_run: bool,
    analysis_duration: int,
    main_thread_label: str,
    process_file: Callable[..., None],
    cpu_worker: Callable[..., dict[str, object]],
    cpu_result_handler: Callable[..., None],
    parallel_mode: bool,
    max_workers: int | None = None,
) -> None:
    """Run the shared analyse-and-tag batch workflow end-to-end.

    The workflow every analysis tool previously repeated verbatim
    (discover, analyse per file in a thread pool, report, join the active
    undo batch): only the analyser and its tag-write semantics differ per
    tool, and they are injected as callables.

    In worker-thread mode each file goes through ``process_file`` — which
    must accept ``(name, dir_path, is_dry_run, analysis_duration,
    slot_vars, slot_idx, lock, on_progress)`` — inside the worker's
    ``use_batch`` join. In parallel-CPU mode the batch is delegated to
    :meth:`BaseFileProcessor.run_cpu_bound_processing` with the tool's
    picklable worker and result handler.

    Args:
        processor: The tool's ``BaseFileProcessor`` instance driving the
            batch (discover/process/slot management).
        dir_path: Directory of audio files to analyse.
        slot_vars: Per-worker status label variables.
        slot_queue: Queue pre-loaded with worker slot indices.
        on_progress: Called after each file with
            ``(processed, total, skipped, errors, display_text)``.
        on_complete: Called once with the summary keyword arguments.
        on_error: Called with a human-readable message on fatal errors.
        extensions: Discoverable audio extensions.
        is_dry_run: Forwarded to ``process_file``.
        analysis_duration: Forwarded to ``process_file`` and the CPU
            worker kwargs.
        main_thread_label: Resource-manager thread label.
        process_file: Per-file step (thread mode).
        cpu_worker: Picklable per-file CPU stage (parallel mode).
        cpu_result_handler: Main-thread I/O/completion handler for CPU
            results (parallel mode).
        parallel_mode: When True, use the CPU-bound pool.
        max_workers: Parallel-pool size (parallel mode only).
    """
    get_resource_manager()

    if parallel_mode:
        cpu_kwargs: dict[str, object] = {"analysis_duration": analysis_duration}
        handler_kwargs: dict[str, object] = {
            "is_dry_run": is_dry_run,
            "slot_vars": slot_vars,
        }
        processor.run_cpu_bound_processing(
            dir_path=dir_path,
            cpu_worker=cpu_worker,
            result_handler=cpu_result_handler,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
            extensions=extensions,
            max_workers=max_workers,
            **{**cpu_kwargs, **handler_kwargs},
        )
        return

    files = _preflight_discover(
        processor,
        dir_path,
        extensions,
        on_error,
        empty_message="No supported audio files found in the selected directory.",
    )
    if files is None:
        return

    processed, skipped, errors, log_entries, _on_progress = (
        processor.create_progress_tracker(
            lambda processed, total, skipped, errors, display_text: on_progress(
                processed, total, skipped, errors, display_text
            ),
            len(files),
        )
    )

    lock = threading.Lock()
    start = time.time()

    main_thread = threading.current_thread()
    track_thread(main_thread, main_thread_label)

    # Join an active undo batch if the caller opened one.  Worker threads
    # record tag snapshots against it via use_batch().
    undo_batch: str | None = get_active_batch_id()

    def _worker(name: str) -> None:
        slot_idx = slot_queue.get()
        try:
            with use_batch(undo_batch):
                process_file(
                    name=name,
                    dir_path=dir_path,
                    is_dry_run=is_dry_run,
                    analysis_duration=analysis_duration,
                    slot_vars=slot_vars,
                    slot_idx=slot_idx,
                    lock=lock,
                    on_progress=_on_progress,
                )
        finally:
            slot_vars[slot_idx].set("IDLE")
            slot_queue.put(slot_idx)

    # KEEP-IN-SYNC: run_parallel_processing, run_cpu_bound_processing,
    # run_inplace_dsp_batch — the executor loops are intentionally
    # ununified (D5) because each uses a different pool/process model.
    processor.process_batch(
        files,
        _worker,
        max_workers=cap_workers_to_slot_grid(processor.max_workers, slot_vars),
    )

    _emit_completion(
        on_complete,
        len(files),
        processed[0],
        skipped[0],
        errors[0],
        start,
        log_entries,
    )
