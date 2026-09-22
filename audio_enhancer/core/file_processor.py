"""
core/file_processor.py - Migrated to use BaseFileProcessor for audio enhancement.

Eliminates duplicated threading, slot management, and error-handling code
by using shared BaseFileProcessor infrastructure while preserving identical
callback signatures and functionality.

Concurrency model
-----------------
A ThreadPoolExecutor with DEFAULT_MAX_WORKERS threads is used.  The same
constant is imported by app.py to size its slot-display pool so the two are
always in sync.

All callbacks from worker threads are fire-and-forget; app.py is
responsible for marshalling them onto the Tkinter main thread via
root.after(0, fn).

Counter semantics
-----------------
  processed : every file attempted (done + errors + skipped)
  done      : files successfully enhanced and written
  errors    : files that raised an exception during processing and were
              NOT cleanly skippable (JobStatus.FAILED)
  (skipped files, e.g. those that vanished between discovery and
  processing, are tracked in `results` with JobStatus.SKIPPED but are
  not counted in `errors`)
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from queue import Queue
from typing import Any

from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    AudioFileNotFoundError,
    AudioPermissionError,
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor

from .inspector import find_audio_files, inspect
from .models import EnhancementParams, JobStatus, ProcessingResult
from .processor import process_file

logger = logging.getLogger(__name__)


class AudioEnhancerProcessor(BaseFileProcessor):
    """Audio enhancer using shared BaseFileProcessor infrastructure.

    Eliminates ~150 lines of duplicated threading and error handling code
    while maintaining identical functionality.
    """

    def __init__(self) -> None:
        super().__init__(operation_type="audio_enhancement")


def process_single_file(
    name: str,
    dir_path: str,
    params: EnhancementParams,
    output_dir: Path,
    slot_idx: int,
    lock: threading.Lock,
    on_progress: Callable[..., None],
    **kwargs: Any,
) -> None:
    """Process a single audio file for enhancement.

    Designed to be used with BaseFileProcessor.run_parallel_processing().
    Maintains slot-variable updates and progress reporting via the
    standardised ``on_progress(n_skipped, n_errors, display_text, log_text)``
    callback signature from the base class.

    Args:
        name:       File name (not full path) of the audio file.
        dir_path:   Directory containing the audio file.
        params:     DSP enhancement parameters.
        output_dir: Directory to write the enhanced file into.
        slot_idx:   Index of the worker-slot display variable.
        lock:       Threading lock that gates calls to on_progress.
        on_progress: Base-class progress callback with signature
                     (n_skipped, n_errors, display_text, log_text).
        **kwargs:   Extra keyword arguments (e.g. slot_vars).
    """
    slot_vars: list[Any] | None = kwargs.get("slot_vars")
    if slot_vars is not None:
        slot_vars[slot_idx].set(f"Inspecting: {name[:22]}...")

    safe_name = name.replace(" ", "_").replace("-", "_")
    file_path = Path(dir_path) / name

    try:
        if slot_vars is not None:
            slot_vars[slot_idx].set(f"Processing: {safe_name[:22]}...")

        info = inspect(file_path)
        result = process_file(info, params, output_dir)

        if result.status == JobStatus.DONE:
            display = (
                f"[DONE] {result.source.name}  "
                f"{result.gain_db:+.1f} dB  tags:{result.tags_copied}"
            )
        elif result.status == JobStatus.ERROR:
            display = f"[ERROR] {safe_name}: {result.error_message}"
        else:
            display = result.display_text

        with lock:
            on_progress(display_text=display, log_text=display + "\n")

    except AudioFileNotFoundError as exc:
        logger.warning(
            "File not found during enhancement, skipping: %s | %s",
            safe_name,
            exc.message,
            exc_info=True,
        )
        display = f"[SKIP] {safe_name}: {user_message_for(exc)}"
        with lock:
            on_progress(n_skipped=1, display_text=display, log_text=display + "\n")

    except AudioPermissionError as exc:
        logger.error(
            "Permission denied for %s: %s", safe_name, exc.message, exc_info=True
        )
        display = f"[ERROR] {safe_name}: {user_message_for(exc)}"
        with lock:
            on_progress(n_errors=1, display_text=display, log_text=display + "\n")

    except AudioSuiteError as exc:
        logger.error(
            "[%s] Enhancement failed for %s: %s",
            type(exc).__name__,
            safe_name,
            exc.message,
            exc_info=True,
        )
        display = f"[ERROR] {safe_name}: {user_message_for(exc)}"
        with lock:
            on_progress(n_errors=1, display_text=display, log_text=display + "\n")

    except (OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc, context={"file": name})
        logger.error(
            "[%s] Unexpected error enhancing %s: %s",
            type(mapped).__name__,
            safe_name,
            mapped,
            exc_info=True,
        )
        display = f"[ERROR] {safe_name}: {user_message_for(mapped)}"
        with lock:
            on_progress(n_errors=1, display_text=display, log_text=display + "\n")


@handle_audio_errors(reraise=False, context="audio_enhancer_run_enhancement")
def run_enhancement(
    source_path: Path,
    output_dir: Path,
    params: EnhancementParams,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: Callable[
        ..., None
    ],  # (processed, total, done, errors, result, display_text)
    on_complete: Callable[..., None],  # (total, done, errors, duration_secs, results)
    on_error: Callable[[str], None],  # (message)
) -> None:
    """
    Discover audio files under source_path and process them in parallel.

    Callbacks (all invoked from worker/orchestrator threads — caller must
    marshal to the Tk main thread via root.after(0, fn)):

    on_progress(processed, total, done, errors, result, display_text)
        Called after each file completes.

    on_complete(total, done, errors, duration_secs, results)
        Called once after all workers finish.

    on_error(message)
        Called for fatal errors that prevent any processing from starting.
    """
    processor = AudioEnhancerProcessor()

    try:
        files = find_audio_files(source_path)
    except OSError as exc:
        logger.error(
            "File discovery failed for %s: %s", source_path, exc, exc_info=True
        )
        on_error(f"Error: Cannot access directory {source_path}.")
        return

    if not files:
        on_error("No supported audio files found at the selected path.")
        return

    lock = threading.Lock()
    processed = [0]
    done = [0]
    errors = [0]
    results: list[ProcessingResult] = []

    def _after_file(result: ProcessingResult) -> None:
        """Aggregate counters and fire on_progress — called under lock.

        For JobStatus.DONE, the display string is built here from the
        result's measured values. For SKIPPED/FAILED results, the caller
        (_worker's except branches) already built a correct, specific
        display_text (e.g. "[SKIP] track.mp3: file not found") since
        `source` is not meaningful on those paths (see ProcessingResult
        docstring) — that pre-built text is used as-is rather than being
        regenerated from empty fields.
        """
        processed[0] += 1
        if result.status == JobStatus.DONE:
            done[0] += 1
        elif result.status == JobStatus.SKIPPED:
            pass  # skips are neither successes nor errors
        else:
            errors[0] += 1
        results.append(result)

        if result.status == JobStatus.DONE:
            display = (
                f"[DONE] {result.source.name}  "
                f"{result.gain_db:+.1f} dB  tags:{result.tags_copied}"
            )
        else:
            display = result.display_text

        on_progress(
            processed=processed[0],
            total=len(files),
            done=done[0],
            errors=errors[0],
            result=result,
            display_text=display,
        )

    def _worker(file_name: Path) -> None:
        """Process a single file with error recovery."""
        safe_name = str(file_name).replace(" ", "_").replace("-", "_")

        def _enhance() -> ProcessingResult:
            info = inspect(source_path / file_name)
            result = process_file(info, params, output_dir)
            return result

        try:
            result = processor.run_with_retry(
                _enhance,
                max_retries=3,
                base_delay=0.5,
                label=f"enhance_{safe_name}",
            )
            with lock:
                _after_file(result)

        except AudioFileNotFoundError as exc:
            logger.warning(
                "File not found during enhancement, skipping: %s | %s",
                safe_name,
                exc.message,
                exc_info=True,
            )
            with lock:
                _after_file(
                    ProcessingResult(
                        status=JobStatus.SKIPPED,
                        display_text=f"[SKIP] {safe_name}: {user_message_for(exc)}",
                    )
                )

        except AudioPermissionError as exc:
            logger.error(
                "Permission denied for %s: %s", safe_name, exc.message, exc_info=True
            )
            with lock:
                _after_file(
                    ProcessingResult(
                        status=JobStatus.FAILED,
                        display_text=f"[ERROR] {safe_name}: {user_message_for(exc)}",
                    )
                )

        except AudioSuiteError as exc:
            logger.error(
                "[%s] Enhancement failed for %s: %s",
                type(exc).__name__,
                safe_name,
                exc.message,
                exc_info=True,
            )
            with lock:
                _after_file(
                    ProcessingResult(
                        status=JobStatus.FAILED,
                        display_text=f"[ERROR] {safe_name}: {user_message_for(exc)}",
                    )
                )

        except (OSError, ValueError) as exc:
            mapped = map_to_audio_error(exc, context={"file": file_name})
            logger.error(
                "[%s] Unexpected error enhancing %s: %s",
                type(mapped).__name__,
                safe_name,
                mapped,
                exc_info=True,
            )
            with lock:
                _after_file(
                    ProcessingResult(
                        status=JobStatus.FAILED,
                        display_text=f"[ERROR] {safe_name}: {user_message_for(mapped)}",
                    )
                )

    start = time.monotonic()

    processor.process_batch(files, _worker, max_workers=DEFAULT_MAX_WORKERS)

    on_complete(
        total=len(files),
        processed=done[0] + errors[0],
        done=done[0],
        skipped=0,
        errors=errors[0],
        duration_secs=time.monotonic() - start,
        results=results,
    )
