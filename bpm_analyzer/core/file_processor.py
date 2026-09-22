"""
file_processor.py - Migrated to use BaseFileProcessor for BPM analysis.

Eliminates ~150 lines of duplicated threading and error handling code
by using shared BaseFileProcessor infrastructure while preserving identical
functionality.
"""

from __future__ import annotations

import logging
import os
import threading
from enum import Enum, auto
from queue import Queue
from typing import Any, Callable, Optional

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.exceptions import handle_audio_errors
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.tag_helper import read_bpm, write_bpm

from .bpm_detector import BPMDetectionError, detect_bpm

logger = logging.getLogger(__name__)


class BPMAnalyzerProcessor(BaseFileProcessor):
    """
    BPM analyser using shared BaseFileProcessor infrastructure.

    Eliminates ~150 lines of duplicated threading and error handling code
    while maintaining identical functionality.
    """

    def __init__(self, max_workers: int = 4, parallel_mode: bool = False) -> None:
        super().__init__(
            operation_type="bpm_analysis",
            max_workers=max_workers,
            parallel_mode=parallel_mode,
        )


class ProcessingStatus(Enum):
    """Enumeration of processing status values for BPM analysis."""

    DRY_RUN = auto()
    TAGGED = auto()
    SKIPPED = auto()
    ERROR = auto()


def process_single_file(
    name: str,
    dir_path: str,
    is_dry_run: bool,
    min_bpm: int,
    max_bpm: int,
    analysis_duration: int,
    slot_idx: int,
    lock: threading.Lock,
    on_progress: Callable[..., None],
    **kwargs: Any,
) -> None:
    """
    Process a single audio file for BPM detection and optional tagging.

    Args:
        name:              File name (not full path) of the audio file.
        dir_path:          Directory containing the audio file.
        is_dry_run:        When True, detect BPM but do not write the tag.
        min_bpm:           Lower bound; detected tempo is clamped to this.
        max_bpm:           Upper bound; detected tempo is clamped to this.
        analysis_duration: Maximum seconds of audio to pass to librosa.
        slot_idx:          Index of the worker-slot display variable.
        lock:              Threading lock that gates calls to on_progress.
        on_progress:       Callback with signature (n_skipped, n_errors,
                           display_text, log_text) used by BaseFileProcessor.
        **kwargs:          Extra keyword arguments forwarded by the base class
                           (e.g. slot_vars).
    """
    slot_vars: list[Any] | None = kwargs.get("slot_vars")
    if slot_vars is not None:
        slot_vars[slot_idx].set(f"Analyzing: {name[:25]}...")

    full_path: str = os.path.join(dir_path, name)

    try:
        bpm: int = detect_bpm(full_path, analysis_duration, min_bpm, max_bpm)
    except BPMDetectionError as exc:
        logger.error(
            "[BPMDetectionError] process_single_file failed for '%s': %s",
            name,
            exc,
            exc_info=True,
        )
        display = f"[ERROR] {name}: BPM detection failed"
        log = f"[ERROR] {name}: BPM detection failed — {exc}\n"
        with lock:
            on_progress(n_skipped=0, n_errors=1, display_text=display, log_text=log)
        return

    # NOTE: detect_bpm() always hard-clamps its return value into
    # [min_bpm, max_bpm] (see bpm_detector.detect_bpm — octave correction
    # followed by a final clamp). There is therefore no range check here:
    # a returned value outside [min_bpm, max_bpm] cannot occur. Tracks whose
    # true tempo falls outside the configured range are tagged with the
    # nearest boundary value instead of being skipped.

    status: ProcessingStatus = ProcessingStatus.DRY_RUN
    action: str = f"BPM {bpm}"

    if not is_dry_run:
        if slot_vars is not None:
            slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")

        existing_bpm: Optional[int] = read_bpm(full_path)
        write_bpm(full_path, bpm)
        status = ProcessingStatus.TAGGED
        logger.info("[TAGGED] %s — BPM %d (was %s)", name, bpm, existing_bpm)

        if existing_bpm and existing_bpm != bpm:
            action += f" (was {existing_bpm})"
    else:
        logger.info("[DRY RUN] %s — BPM %d", name, bpm)

    status_label: str = status.name.replace("_", " ")  # DRY_RUN → DRY RUN
    display = f"[{status_label}] {name} → {action}"
    log = f"[{status_label}] {name} | BPM {bpm}\n"

    with lock:
        on_progress(n_skipped=0, n_errors=0, display_text=display, log_text=log)


def _detect_bpm_cpu(
    file_path: str,
    analysis_duration: int,
    min_bpm: int,
    max_bpm: int,
    **kwargs: object,
) -> dict[str, object]:
    """Top-level CPU worker for BPM detection (picklable for ProcessPoolExecutor).

    Runs in a separate process; no callback, lock, or UI references.

    Returns:
        ``{"status": "ok", "bpm": <int>}`` on success, or
        ``{"status": "error", "error": <str>}`` on failure.
    """
    try:
        bpm = detect_bpm(file_path, analysis_duration, min_bpm, max_bpm)
        return {"status": "ok", "bpm": bpm}
    except BPMDetectionError as exc:
        logger.error(
            "[BPMDetectionError] _detect_bpm_cpu failed for '%s': %s",
            file_path,
            exc,
            exc_info=True,
        )
        return {"status": "error", "error": str(exc)}
    except (ValueError, OSError, RuntimeError) as exc:
        logger.error(
            "[Unexpected] _detect_bpm_cpu failed for '%s': %s",
            file_path,
            exc,
            exc_info=True,
        )
        return {"status": "error", "error": str(exc)}


def _handle_bpm_result(
    filename: str,
    dir_path: str,
    result: dict[str, object],
    slot_idx: int,
    lock: threading.Lock,
    on_progress: Callable[..., None],
    **kwargs: Any,
) -> None:
    """Main-thread handler for BPM CPU results.  Reads/writes tags and
    reports progress."""
    is_dry_run = kwargs.get("is_dry_run", False)
    slot_vars: list[Any] | None = kwargs.get("slot_vars")
    if slot_vars is not None:
        slot_vars[slot_idx].set(f"Processing: {filename[:25]}...")

    full_path: str = os.path.join(dir_path, filename)

    if result.get("status") == "error":
        display = f"[ERROR] {filename}: {result.get('error', 'unknown error')}"
        log = f"[ERROR] {filename}: BPM detection failed — {result.get('error')}\n"
        with lock:
            on_progress(n_skipped=0, n_errors=1, display_text=display, log_text=log)
        return

    bpm: int = result["bpm"]  # type: ignore[assignment]

    if not is_dry_run:
        if slot_vars is not None:
            slot_vars[slot_idx].set(f"Tagging: {filename[:25]}...")

        existing_bpm: int | None = read_bpm(full_path)
        write_bpm(full_path, bpm)

        action = f"BPM {bpm}"
        if existing_bpm and existing_bpm != bpm:
            action += f" (was {existing_bpm})"
        display = f"[TAGGED] {filename} \u2192 {action}"
        log = f"[TAGGED] {filename} | BPM {bpm}\n"
        logger.info("[TAGGED] %s \u2014 BPM %d (was %s)", filename, bpm, existing_bpm)
    else:
        display = f"[DRY RUN] {filename} \u2192 BPM {bpm}"
        log = f"[DRY RUN] {filename} | BPM {bpm}\n"
        logger.info("[DRY RUN] %s \u2014 BPM %d", filename, bpm)

    with lock:
        on_progress(n_skipped=0, n_errors=0, display_text=display, log_text=log)


@handle_audio_errors(reraise=False, context="bpm_analyzer_run_analysis")
def run_analysis(
    dir_path: str,
    is_dry_run: bool,
    min_bpm: int,
    max_bpm: int,
    analysis_duration: int,
    slot_vars: list[Any],
    slot_queue: Queue,  # type: ignore[type-arg]  # kept for interface compatibility
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
    parallel_mode: bool = False,
    max_workers: int | None = None,
) -> None:
    """
    Run parallel BPM analysis using shared BaseFileProcessor infrastructure.

    Maintains the same external interface as the original implementation.
    slot_queue is accepted for API compatibility but is managed internally
    by BaseFileProcessor.

    When *parallel_mode* is True, uses ``ProcessPoolExecutor`` via
    ``run_cpu_bound_processing`` for true multi-process CPU parallelism
    (bypasses the GIL for librosa FFT).

    Args:
        dir_path:          Directory of audio files to analyse.
        is_dry_run:        When True, detect only — do not write tags.
        min_bpm:           Minimum valid BPM; detected tempo is clamped to this.
        max_bpm:           Maximum valid BPM; detected tempo is clamped to this.
        analysis_duration: Seconds of audio to pass to librosa.
        slot_vars:         List of tk.StringVar for worker-slot status labels.
        slot_queue:        Accepted for interface compatibility; not used directly.
        on_progress:       UI progress callback forwarded to BaseFileProcessor.
        on_complete:       Completion callback forwarded to BaseFileProcessor.
        on_error:          Error callback forwarded to BaseFileProcessor.
        parallel_mode:     When True, use ProcessPoolExecutor for CPU-bound
            detection; when False (default), use ThreadPoolExecutor.
        max_workers:       Number of parallel workers.  Defaults to 4.
    """
    logger.info(
        "run_analysis: dir=%s dry_run=%s bpm=[%d,%d] duration=%ds "
        "parallel=%s workers=%s",
        dir_path,
        is_dry_run,
        min_bpm,
        max_bpm,
        analysis_duration,
        parallel_mode,
        max_workers,
    )

    processor = BPMAnalyzerProcessor(
        max_workers=max_workers or 4,
        parallel_mode=parallel_mode,
    )

    # Join an active undo batch if the caller opened one.  Worker threads
    # record tag snapshots against it via use_batch().
    undo_batch: str | None = get_active_batch_id()

    if parallel_mode:
        cpu_kwargs = {
            "analysis_duration": analysis_duration,
            "min_bpm": min_bpm,
            "max_bpm": max_bpm,
        }
        handler_kwargs = {
            "is_dry_run": is_dry_run,
            "slot_vars": slot_vars,
        }
        combined_kwargs: dict[str, object] = {**cpu_kwargs, **handler_kwargs}

        processor.run_cpu_bound_processing(
            dir_path=dir_path,
            cpu_worker=_detect_bpm_cpu,
            result_handler=_handle_bpm_result,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
            extensions=SUPPORTED_EXTENSIONS,
            max_workers=max_workers,
            **combined_kwargs,
        )
    else:

        def processor_func(
            filename: str,
            dir_path: str,
            slot_idx: int,
            lock: threading.Lock,
            on_progress: Callable[..., None],
            **kwargs: object,
        ) -> None:
            with use_batch(undo_batch):
                process_single_file(
                    name=filename,
                    dir_path=dir_path,
                    is_dry_run=is_dry_run,
                    min_bpm=min_bpm,
                    max_bpm=max_bpm,
                    analysis_duration=analysis_duration,
                    slot_idx=slot_idx,
                    lock=lock,
                    on_progress=on_progress,
                    slot_vars=slot_vars,
                    **kwargs,
                )

        processor.run_parallel_processing(
            dir_path=dir_path,
            processor_func=processor_func,
            on_progress=on_progress,
            on_complete=on_complete,
            on_error=on_error,
            extensions=SUPPORTED_EXTENSIONS,
        )
