"""
file_processor_base.py — Base file processor class for Audio Suite applications.

Provides common infrastructure for parallel file processing, eliminating duplication
across multiple applications while preserving all existing functionality.
"""

from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from queue import Queue
from typing import Any, TypeVar

from pydub import AudioSegment

from .audio_formats import SUPPORTED_EXTENSIONS, get_export_args
from .batch_undo import (
    get_active_batch_id,
    record_tag_edit_snapshot,
    use_batch,
)
from .constants import (
    CPU_WORKER_TIMEOUT_SECS,
    DEFAULT_MAX_WORKERS,
    WORKER_TIMEOUT_SECS,
)
from .error_recovery import (
    RecoveryAction,
    RetryConfig,
    get_recovery_action,
    retry_with_backoff,
)
from .exceptions import (
    AudioDirectoryError,
    AudioPermissionError,
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from .resource_manager import (
    cleanup_expired_resources,
    get_resource_manager,
    track_thread,
)

logger = logging.getLogger(__name__)

_T = TypeVar("_T")

# Type aliases for callback signatures
ProgressCallback = Callable[..., None]
CompleteCallback = Callable[..., None]
ErrorCallback = Callable[[str], None]


@dataclass(frozen=True)
class InplaceDspResult:
    """Outcome of a per-tool DSP pass over a single file.

    Mirrors the shape of the per-tool DSP results (``NoiseReductionResult`` /
    ``DeclickResult``): ``audio`` is always present — the DSP implementations
    return the untouched input when there is nothing to do — and
    ``was_modified`` carries the verdict.  ``action`` is the human-readable
    summary the shared report displays; ``repaired_suffix`` is appended to it
    only once the repaired audio has actually been written back to disk.

    This is the *only* thing a tool has to supply to plug its DSP into the
    shared in-place workflow; the DSP itself stays in the tool module.
    """

    audio: AudioSegment
    was_modified: bool
    action: str
    repaired_suffix: str = ""


#: Per-tool DSP adapter: takes the decoded segment, returns the shared result.
InplaceDspFn = Callable[[AudioSegment], InplaceDspResult]

#: Builds a per-file worker.  Called once per batch with the shared temp dir,
#: counter lock and inner progress callback; returns the ``worker(name)`` that
#: :meth:`BaseFileProcessor.run_inplace_dsp_batch` submits to the thread pool.
InplaceWorkerFactory = Callable[
    [str, threading.Lock, ProgressCallback], Callable[[str], None]
]


class BaseFileProcessor:
    """
    Base class for file processing operations across Audio Suite applications.

    Eliminates common duplication in threading, progress tracking, and error handling
    while maintaining compatibility with existing callback interfaces.
    """

    def __init__(
        self,
        max_workers: int = DEFAULT_MAX_WORKERS,
        operation_type: str = "file_processing",
        parallel_mode: bool = False,
    ):
        self.max_workers = max_workers
        self.operation_type = operation_type
        self.parallel_mode = parallel_mode
        self.resource_manager = get_resource_manager()

    def discover_audio_files(
        self, dir_path: str, extensions: tuple[str, ...] | None = None
    ) -> list[str]:
        """
        Discover audio files in directory with consistent filtering logic.

        Raises AudioPermissionError or AudioDirectoryError on failure —
        never swallows OS errors silently.
        """
        if extensions is None:
            extensions = SUPPORTED_EXTENSIONS

        try:
            files = [
                e.name
                for e in os.scandir(dir_path)
                if e.is_file() and e.name.lower().endswith(extensions)
            ]
            return files
        except PermissionError as exc:
            raise AudioPermissionError(
                f"Permission denied accessing directory: {dir_path}",
                path=dir_path,
                original=exc,
            ) from exc
        except OSError as exc:
            raise AudioDirectoryError(
                f"Could not read directory: {dir_path}",
                context={"path": dir_path},
                original=exc,
            ) from exc

    def create_progress_tracker(
        self, on_progress: ProgressCallback, total_files: int
    ) -> tuple[list[int], list[int], list[int], list[str], Callable[..., None]]:
        """Create standardised progress tracking infrastructure."""
        processed = [0]
        skipped = [0]
        errors = [0]
        log_entries: list[str] = []
        lock = threading.Lock()

        def _on_progress(
            n_skipped: int = 0,
            n_errors: int = 0,
            display_text: str = "",
            log_text: str = "",
        ) -> None:
            with lock:
                processed[0] += 1
                skipped[0] += n_skipped
                errors[0] += n_errors
                log_entries.append(log_text)
            on_progress(
                processed=processed[0],
                total=total_files,
                skipped=skipped[0],
                errors=errors[0],
                display_text=display_text,
            )

        return processed, skipped, errors, log_entries, _on_progress

    def create_retry_config(
        self,
        max_retries: int = 3,
        retry_delay: float = 0.5,
        backoff_factor: float = 1.5,
    ) -> RetryConfig:
        """Create standardised retry configuration."""
        return RetryConfig(
            max_retries=max_retries,
            retry_delay=retry_delay,
            backoff_factor=backoff_factor,
            retry_on_exceptions=[IOError, OSError, PermissionError],
        )

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
        # Discover files
        try:
            files = self.discover_audio_files(dir_path, extensions)
        except AudioSuiteError as exc:
            logger.error(
                "File discovery failed for %s: %s", dir_path, exc, exc_info=True
            )
            on_error(user_message_for(exc))
            return

        if not files:
            on_error("No supported audio files found in selected directory.")
            return

        processed, skipped, errors, log_entries, _on_progress = (
            self.create_progress_tracker(on_progress, len(files))
        )

        slot_queue: Queue[int] = Queue()
        for i in range(self.max_workers):
            slot_queue.put(i)

        lock = threading.Lock()
        start_time = time.time()

        main_thread = threading.current_thread()
        track_thread(main_thread, f"{self.operation_type}_main")

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
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
                f.result(timeout=WORKER_TIMEOUT_SECS)

        on_complete(
            total=len(files),
            processed=processed[0],
            skipped=skipped[0],
            errors=errors[0],
            duration_secs=time.time() - start_time,
            log_entries=log_entries,
        )

        cleanup_expired_resources(max_age_hours=1)

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
        try:
            files = self.discover_audio_files(dir_path, extensions)
        except AudioSuiteError as exc:
            logger.error(
                "File discovery failed for %s: %s", dir_path, exc, exc_info=True
            )
            on_error(user_message_for(exc))
            return

        if not files:
            on_error("No supported audio files found in selected directory.")
            return

        processed, skipped, errors, log_entries, _on_progress = (
            self.create_progress_tracker(on_progress, len(files))
        )

        lock = threading.Lock()
        start_time = time.time()
        effective_workers = max_workers or self.max_workers

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

        on_complete(
            total=len(files),
            processed=processed[0],
            skipped=skipped[0],
            errors=errors[0],
            duration_secs=time.time() - start_time,
            log_entries=log_entries,
        )

        cleanup_expired_resources(max_age_hours=1)

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

    def process_audio_file_inplace(
        self,
        name: str,
        dir_path: str,
        temp_dir: str,
        slot_vars: list[Any],
        slot_queue: Queue[int],
        lock: threading.Lock,
        on_progress: ProgressCallback,
        *,
        run_dsp: InplaceDspFn,
        dsp_label: str,
        tag_operation: str,
        is_dry_run: bool,
    ) -> None:
        """Run one file through the shared in-place DSP workflow.

        This is the single implementation of the discover/temp-file/write/undo
        sequence that the in-place repair tools share; only ``run_dsp`` (and
        the wording it produces) differs between them.

        Steps
        -----
        1. Copy the source into a per-worker temp directory, so the source
           file is never opened for writing until the final copy-back.
        2. Read and preserve all metadata tags.
        3. Run the tool's DSP via *run_dsp*.
        4. Live run only: export the processed audio, re-apply the tags,
           record the undo snapshot, then copy back over the source.
        5. Report the outcome through *on_progress* under *lock*.

        The slot index is always returned to *slot_queue* and the per-worker
        temp directory is always removed, so neither can leak on an exception.

        Args:
            name: Filename (basename only) to process.
            dir_path: Directory containing *name*.
            temp_dir: Shared batch temp directory; a per-worker
                sub-directory is created inside it and removed afterwards.
            slot_vars: Per-worker status label variables.
            slot_queue: Pool of available slot indices.
            lock: Serialises writes to shared counters and *on_progress*.
            on_progress: Inner progress callback
                ``(status, display_text, log_text)`` where status is one of
                ``"SKIP"``, ``"FOUND"``, ``"FIXED"`` or ``"ERROR"``.
            run_dsp: Tool-supplied DSP adapter returning an
                :class:`InplaceDspResult`.
            dsp_label: Progress label, e.g. ``"Reducing noise"``.
            tag_operation: Undo operation name recorded for a live write.
            is_dry_run: When ``True``, detect but never write audio back.
        """
        from .tag_helper import read_tags_raw, write_tags_raw

        slot_idx = slot_queue.get()
        full_path = os.path.join(dir_path, name)
        ext = os.path.splitext(name)[1].lower()

        worker_temp = tempfile.mkdtemp(dir=temp_dir)
        temp_input = os.path.join(worker_temp, f"in{ext}")
        temp_output = os.path.join(worker_temp, f"out{ext}")

        try:
            slot_vars[slot_idx].set(f"Loading: {name[:25]}...")
            original_tags = read_tags_raw(full_path)
            shutil.copy2(full_path, temp_input)

            slot_vars[slot_idx].set(f"{dsp_label}: {name[:25]}...")
            audio = AudioSegment.from_file(temp_input)
            outcome = run_dsp(audio)

            if not outcome.was_modified:
                status = "SKIP"
                action = outcome.action
            else:
                action = outcome.action
                status = "FOUND"  # dry run: detected but not written
                if not is_dry_run:
                    slot_vars[slot_idx].set(f"Exporting: {name[:25]}...")
                    fmt, export_params = get_export_args(ext)
                    outcome.audio.export(
                        temp_output, format=fmt, parameters=export_params
                    )

                    slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")
                    write_tags_raw(temp_output, original_tags, record_snapshot=False)
                    record_tag_edit_snapshot(full_path, tag_operation)
                    shutil.copy2(temp_output, full_path)
                    action += outcome.repaired_suffix
                    status = "FIXED"

            display = f"[{status}] {name} → {action}"
            log = f"[{status}] {name} | {action}\n"

            with lock:
                on_progress(status=status, display_text=display, log_text=log)

        except Exception as exc:
            mapped = map_to_audio_error(exc)
            logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
            display = f"[ERROR] {name}: {str(exc)[:80]}"
            log = f"[ERROR] {name}: {exc}\n"
            with lock:
                on_progress(status="ERROR", display_text=display, log_text=log)

        finally:
            shutil.rmtree(worker_temp, ignore_errors=True)
            slot_vars[slot_idx].set("IDLE")
            slot_queue.put(slot_idx)

    @handle_audio_errors(reraise=False, context="run_inplace_dsp_batch")
    def run_inplace_dsp_batch(
        self,
        dir_path: str,
        make_worker: InplaceWorkerFactory,
        on_progress: ProgressCallback,
        on_complete: CompleteCallback,
        on_error: ErrorCallback,
        extensions: tuple[str, ...] | None = None,
    ) -> None:
        """Discover, dispatch and summarise a batch of in-place DSP repairs.

        The batch-level half of the shared in-place workflow: sorted discovery,
        the succeeded/skipped/errors counters, joining the caller's undo batch,
        the shared temp directory and the completion callback.  Each file is
        handled by :meth:`process_audio_file_inplace` via the worker that
        *make_worker* builds.

        Unlike :meth:`run_parallel_processing` this method does **not** wrap
        files in a retry loop: a per-file failure is already reported through
        the counters by the worker, so a retry could never observe it.

        Args:
            dir_path: Directory of audio files to process.
            make_worker: Factory called once as
                ``make_worker(temp_dir, lock, on_progress)`` and expected to
                return a ``worker(name)`` callable.
            on_progress: Called per finished file with
                ``(processed, total, succeeded, skipped, errors, display_text)``.
            on_complete: Called once after every file finished with
                ``(total, processed, succeeded, skipped, errors, duration_secs,
                log_entries)``.
            on_error: Called for fatal errors that prevent the batch from
                starting, with a sanitised ``user_message_for()`` string.
            extensions: Extensions to discover.  Defaults to
                ``SUPPORTED_EXTENSIONS``.
        """
        try:
            files = sorted(self.discover_audio_files(dir_path, extensions))
        except AudioSuiteError as exc:
            logger.error(
                "File discovery failed for %s: %s", dir_path, exc, exc_info=True
            )
            on_error(user_message_for(exc))
            return

        if not files:
            on_error("No supported audio files found in the selected directory.")
            return

        lock = threading.Lock()
        processed = [0]
        succeeded = [0]
        skipped = [0]
        errors = [0]
        log_entries: list[str] = []
        undo_batch = get_active_batch_id()

        def _on_progress(status: str, display_text: str, log_text: str) -> None:
            """Inner callback — called under *lock* from each worker thread."""
            processed[0] += 1
            if status == "ERROR":
                errors[0] += 1
            elif status == "SKIP":
                skipped[0] += 1
            else:  # "FOUND" or "FIXED"
                succeeded[0] += 1
            log_entries.append(log_text)
            on_progress(
                processed=processed[0],
                total=len(files),
                succeeded=succeeded[0],
                skipped=skipped[0],
                errors=errors[0],
                display_text=display_text,
            )

        start = time.monotonic()
        temp_dir = tempfile.mkdtemp()
        worker = make_worker(temp_dir, lock, _on_progress)

        def _worker(name: str) -> None:
            """Run one file inside the caller's undo batch."""
            with use_batch(undo_batch):
                worker(name)

        try:
            self.process_batch(files, _worker, max_workers=self.max_workers)
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        on_complete(
            total=len(files),
            processed=succeeded[0] + skipped[0] + errors[0],
            succeeded=succeeded[0],
            skipped=skipped[0],
            errors=errors[0],
            duration_secs=time.monotonic() - start,
            log_entries=log_entries,
        )
