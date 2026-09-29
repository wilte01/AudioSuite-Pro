"""
file_processor.py
Per-file processing worker and ThreadPoolExecutor orchestration
for Key Detector & Tagger.

All UI interaction via injected callbacks — no tkinter imports.

Bug fixed vs original: the original released the worker slot manually
inside the skip branch, meaning a crash there would leak the slot
permanently.  Here the finally block is always responsible for release.

Supports: MP3, FLAC, OGG, M4A, MP4, Opus, WAV, AIFF
"""

import logging
import os
import threading
import time
from collections.abc import Callable
from queue import Queue
from typing import Any

import librosa
import numpy as np
import numpy.typing as npt

from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.error_recovery import RecoveryAction, get_recovery_action
from audio_suite_shared.exceptions import (
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.resource_manager import (
    cleanup_expired_resources,
    get_resource_manager,
    track_thread,
)
from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS, read_key, write_key

from .key_engine import UNKNOWN_KEY, detect_key

logger = logging.getLogger(__name__)

# ── Low-confidence KEY policy (iteration-6 B3) ────────────────────────────────
# Single source of truth for both the serial and the parallel tag path, so the
# decided policy cannot drift between them. `detect_key` returns UNKNOWN_KEY
# when the vote is not decisive; the maintainer's decision is that an
# undecidable key is never written to a real tag, because a `KEY="Unknown"`
# in a library is a statement of fact the analyser cannot support and it
# suppresses the value the user would otherwise get on a later, better run.
# The detection is still reported, so the user learns the file was analysed
# and nothing was tagged.
_TAG_STATUS_UNKNOWN = "DETECTED (not tagged)"


def _should_tag_key(detected_key: str) -> bool:
    """Return whether *detected_key* may be written to a file's KEY tag.

    Args:
        detected_key: The display key returned by :func:`detect_key`.

    Returns:
        ``False`` for :data:`UNKNOWN_KEY` (leave the file's tags untouched),
        ``True`` for any defensible key.
    """
    return detected_key != UNKNOWN_KEY


# ── Type aliases ──────────────────────────────────────────────────────────────

# Signature of the internal progress callback accepted by process_single_file.
# Called under lock; all parameters are keyword-only.
_ProgressCallback = Callable[..., None]

# Signature of the public on_progress callback accepted by run_analysis.
# Called with: processed, total, skipped, errors, display_text.
_PublicProgressCallback = Callable[[int, int, int, int, str], None]

# Signature of the on_complete callback accepted by run_analysis.
_CompleteCallback = Callable[..., None]

# Signature of the on_error callback accepted by run_analysis.
_ErrorCallback = Callable[[str], None]


class KeyDetectorProcessor(BaseFileProcessor):
    """Key detection file processor using BaseFileProcessor infrastructure."""

    def __init__(self, max_workers: int = 4, parallel_mode: bool = False) -> None:
        super().__init__(
            operation_type="key_detection",
            max_workers=max_workers,
            parallel_mode=parallel_mode,
        )


def process_single_file(
    processor: KeyDetectorProcessor,
    name: str,
    dir_path: str,
    is_dry_run: bool,
    analysis_duration: int,
    slot_vars: list[Any],
    slot_idx: int,
    lock: threading.Lock,
    on_progress: _ProgressCallback,
) -> None:
    """Process a single audio file: detect key, optionally write tag.

    Args:
        processor:         KeyDetectorProcessor instance for retry utilities.
        name:              Filename (not full path).
        dir_path:          Directory containing the file.
        is_dry_run:        When True, detect but do not write tags.
        analysis_duration: Maximum seconds of audio to load for analysis.
        slot_vars:         Shared list of UI status StringVars (one per worker).
        slot_idx:          Assigned worker slot index.
        lock:              Mutex guarding *on_progress* calls.
        on_progress:       Callback invoked (under lock) after each file outcome.
    """
    file_path = os.path.join(dir_path, name)
    safe_name = name.replace(" ", "_").replace("-", "_")

    def _detect_file() -> None:
        existing_key = read_key(file_path)

        if existing_key and is_dry_run:
            display = f"[SKIP] {name} (Already has key: {existing_key})"
            log = f"[SKIP] {name} | Existing: {existing_key}\n"
            with lock:
                on_progress(n_skipped=1, display_text=display, log_text=log)
            return

        slot_vars[slot_idx].set(f"Analyzing: {name[:25]}...")
        y_raw: npt.NDArray[np.float32]
        y_raw, _sr = librosa.load(file_path, duration=analysis_duration)
        loaded_sr: int = int(_sr)
        y: npt.NDArray[np.float64] = y_raw.astype(np.float64)
        detected_key: str = detect_key(y, loaded_sr)

        status = "DETECTED"

        if not is_dry_run and _should_tag_key(detected_key):
            slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")
            write_key(file_path, detected_key)
            status = "TAGGED"
        elif not is_dry_run:
            status = _TAG_STATUS_UNKNOWN

        display = f"[{status}] {name} \u2192 {detected_key}"
        if existing_key and existing_key != detected_key:
            display += f" (was {existing_key})"

        log = f"[{status}] {name} | Detected: {detected_key}"
        if existing_key:
            log += f" | Previous: {existing_key}"
        log += "\n"

        with lock:
            on_progress(n_skipped=0, n_errors=0, display_text=display, log_text=log)

    try:
        processor.run_with_retry(_detect_file, label=f"detector_{safe_name}")

    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("[%s] %s", type(mapped).__name__, mapped, exc_info=True)
        action = get_recovery_action(exc, "key_detection")

        if action == RecoveryAction.SKIP:
            display = f"[SKIP] {safe_name}: {exc}"
            with lock:
                on_progress(
                    n_skipped=1,
                    display_text=display,
                    log_text=f"[SKIP] {safe_name}: {exc}\n",
                )
        else:
            display = f"[ERROR] {safe_name}: {exc}"
            with lock:
                on_progress(
                    n_errors=1,
                    display_text=display,
                    log_text=f"[ERROR] {safe_name}: {exc}\n",
                )


def _detect_key_cpu(
    file_path: str,
    analysis_duration: int,
    **kwargs: object,
) -> dict[str, object]:
    """Top-level CPU worker for key detection (picklable for ProcessPoolExecutor).

    Runs librosa.load + detect_key in a separate process.  No callback, lock,
    or UI references.

    Returns:
        ``{"status": "ok", "key": <str>}`` on success, or
        ``{"status": "error", "error": <str>}`` on failure.
    """
    try:
        y_raw: npt.NDArray[np.float32]
        y_raw, _sr = librosa.load(file_path, duration=analysis_duration)
        loaded_sr: int = int(_sr)
        y: npt.NDArray[np.float64] = y_raw.astype(np.float64)
        detected_key: str = detect_key(y, loaded_sr)
        return {"status": "ok", "key": detected_key}
    except Exception as exc:
        logger.error(
            "[Unexpected] _detect_key_cpu failed for '%s': %s",
            file_path,
            exc,
            exc_info=True,
        )
        return {"status": "error", "error": str(exc)}


def _handle_key_result(
    filename: str,
    dir_path: str,
    result: dict[str, object],
    slot_idx: int,
    lock: threading.Lock,
    on_progress: Callable[..., None],
    **kwargs: Any,
) -> None:
    """Main-thread handler for key CPU results.  Reads/writes tags and
    reports progress."""
    is_dry_run = kwargs.get("is_dry_run", False)
    slot_vars: list[Any] = kwargs.get("slot_vars", [])
    file_path = os.path.join(dir_path, filename)

    if result.get("status") == "error":
        display = f"[ERROR] {filename}: {result.get('error', 'unknown error')}"
        log = f"[ERROR] {filename}: key detection failed — {result.get('error')}\n"
        with lock:
            on_progress(n_skipped=0, n_errors=1, display_text=display, log_text=log)
        return

    detected_key: str = result["key"]  # type: ignore[assignment]

    existing_key = read_key(file_path)

    if existing_key and is_dry_run:
        display = f"[SKIP] {filename} (Already has key: {existing_key})"
        log = f"[SKIP] {filename} | Existing: {existing_key}\n"
        with lock:
            on_progress(n_skipped=1, n_errors=0, display_text=display, log_text=log)
        return

    status = "DETECTED"
    if not is_dry_run and _should_tag_key(detected_key):
        slot_vars[slot_idx].set(f"Tagging: {filename[:25]}...")
        write_key(file_path, detected_key)
        status = "TAGGED"
    elif not is_dry_run:
        status = _TAG_STATUS_UNKNOWN

    display = f"[{status}] {filename} \u2192 {detected_key}"
    if existing_key and existing_key != detected_key:
        display += f" (was {existing_key})"

    log = f"[{status}] {filename} | Detected: {detected_key}"
    if existing_key:
        log += f" | Previous: {existing_key}"
    log += "\n"

    with lock:
        on_progress(n_skipped=0, n_errors=0, display_text=display, log_text=log)


@handle_audio_errors(reraise=False, context="key_detector_run_analysis")
def run_analysis(
    dir_path: str,
    is_dry_run: bool,
    analysis_duration: int,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: _PublicProgressCallback,
    on_complete: _CompleteCallback,
    on_error: _ErrorCallback,
    parallel_mode: bool = False,
    max_workers: int | None = None,
) -> None:
    """Scan directory, process all supported audio files with a worker thread
    pool, then call *on_complete* with the summary.

    When *parallel_mode* is True, uses ``ProcessPoolExecutor`` via
    ``run_cpu_bound_processing`` for true multi-process CPU parallelism
    (bypasses the GIL for librosa FFT / chroma CQT).

    Args:
        dir_path:          Path to the directory containing audio files.
        is_dry_run:        When True, analyse only — do not write tags.
        analysis_duration: Maximum seconds of audio to load per file.
        slot_vars:         List of UI status StringVars (one per worker slot).
        slot_queue:        Queue pre-loaded with worker slot indices 0-3.
        on_progress:       Called after each file with
                           (processed, total, skipped, errors, display_text).
        on_complete:       Called once with summary keyword arguments.
        on_error:          Called with a human-readable message on fatal errors.
        parallel_mode:     When True, use ProcessPoolExecutor for CPU-bound
            detection; when False (default), use ThreadPoolExecutor.
        max_workers:       Number of parallel workers.  Defaults to 4.
    """
    get_resource_manager()

    processor = KeyDetectorProcessor(
        max_workers=max_workers or 4,
        parallel_mode=parallel_mode,
    )

    if parallel_mode:
        cpu_kwargs = {"analysis_duration": analysis_duration}
        handler_kwargs = {"is_dry_run": is_dry_run, "slot_vars": slot_vars}
        combined_kwargs: dict[str, object] = {**cpu_kwargs, **handler_kwargs}

        processor.run_cpu_bound_processing(
            dir_path=dir_path,
            cpu_worker=_detect_key_cpu,
            result_handler=_handle_key_result,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
            extensions=SUPPORTED_EXTENSIONS,
            max_workers=max_workers,
            **combined_kwargs,
        )
        return

    try:
        files = processor.discover_audio_files(
            dir_path, extensions=SUPPORTED_EXTENSIONS
        )
    except Exception as exc:
        mapped = map_to_audio_error(exc)
        logger.error("Directory scan failed: %s", mapped, exc_info=True)
        on_error(user_message_for(mapped))
        return

    if not files:
        on_error("No supported audio files found in the selected directory.")
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
    track_thread(main_thread, "key_detector_main")

    # Join an active undo batch if the caller opened one.  Worker threads
    # record tag snapshots against it via use_batch().
    undo_batch: str | None = get_active_batch_id()

    def _worker(name: str) -> None:
        slot_idx = slot_queue.get()
        try:
            with use_batch(undo_batch):
                process_single_file(
                    processor=processor,
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

    processor.process_batch(
        files,
        _worker,
        max_workers=processor.max_workers,
    )

    on_complete(
        total=len(files),
        processed=processed[0],
        skipped=skipped[0],
        errors=errors[0],
        duration_secs=time.time() - start,
        log_entries=log_entries,
    )

    cleanup_expired_resources(max_age_hours=1)
