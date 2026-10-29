"""
file_processor.py - Migrated to use BaseFileProcessor for BPM analysis.

Eliminates ~150 lines of duplicated threading and error handling code
by using shared BaseFileProcessor infrastructure while preserving identical
functionality.

Changed in 1.4.0: the worker count resolves from ``default_max_workers()``
when not supplied (PLAN D56).
Changed in 1.4.0: a failed file reports the reason in plain language and logs
one line; the stack trace goes to the DEBUG log instead of the console.
Changed in 1.4.0: skipped and failed files are collected as structured records
(filename, reason, and the periodicity score or exception type) and handed to
``on_complete`` so the CLI's ``--json`` output can explain an outcome instead of
only counting it.

Changed in 1.4.1: ``run_analysis`` warms librosa's kernels before the worker
pool starts, so a thread batch no longer pays one compile per thread
(backlog P6).

Changed in 1.4.1: the band no longer rewrites a tempo the onsets cannot
corroborate, so a file whose measured BPM sits outside it is tagged as measured
and its line says ``(outside 75-175)`` (PLAN D108).
Changed in 1.4.1: those files are also collected as structured records and
handed to ``on_complete``, so the run summary and the CLI's ``--json`` can
count them instead of leaving the evidence only in per-file lines (D109).
"""
# Changed in 2.1.7: ASCII-only status output (R-14) - typography stays in
# comments and docs; a cp1252 console cannot encode these glyphs.

from __future__ import annotations

import logging
import os
import threading
from enum import Enum, auto
from queue import Queue
from typing import Any, Callable, Optional

from audio_suite_shared.analysis_loader import warm_analysis_stack
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.constants import cap_workers_to_slot_grid, default_max_workers
from audio_suite_shared.exceptions import (
    failure_reason,
    handle_audio_errors,
    log_handled_failure,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.tag_helper import read_bpm, write_bpm

from .bpm_detector import BPMDetectionError, NoTempoDetectedError, detect_bpm

logger = logging.getLogger(__name__)


class BPMAnalyzerProcessor(BaseFileProcessor):
    """
    BPM analyser using shared BaseFileProcessor infrastructure.

    Eliminates ~150 lines of duplicated threading and error handling code
    while maintaining identical functionality.
    """

    def __init__(
        self, max_workers: int | None = None, parallel_mode: bool = False
    ) -> None:
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


def _error_record(filename: str, reason: str, exc: BaseException) -> dict[str, object]:
    """Build the structured record for one failed file.

    ``error_type`` lets a script separate a corrupt/unreadable file from other
    failures without matching prose; the reason stays the same plain-language
    sentence the per-file log shows.
    """
    return {
        "filename": filename,
        "reason": reason,
        "error_type": type(exc).__name__,
    }


def _skip_record(
    filename: str, reason: str, exc: NoTempoDetectedError
) -> dict[str, object]:
    """Build the structured record for one refused file.

    The score comes from the exception's context, not from the rendered
    ``reason``: parsing the sentence would break the moment its wording
    changes.  A non-positive tempo estimate never measured periodicity, so
    that field is ``None`` rather than a fabricated zero.
    """
    score = exc.context.get("onset_periodicity")
    return {
        "filename": filename,
        "reason": reason,
        "onset_periodicity": (
            float(score) if isinstance(score, (int, float)) else None
        ),
    }


def _range_note(bpm: int, min_bpm: int | None, max_bpm: int | None) -> str:
    """Return a note when a measured tempo sits outside the configured band.

    The band chooses between octave-equivalent readings, but it never rewrites
    a measurement the onsets support (see ``bpm_detector.detect_bpm`` and PLAN
    D108).  A file whose real tempo is below the floor is therefore tagged as
    measured rather than doubled; saying so on the file's own line keeps that
    visible instead of looking like the range the user set was ignored.

    Args:
        bpm:     The tempo actually measured.
        min_bpm: Lower bound the run was configured with, or None when the
                 caller did not supply a band.
        max_bpm: Upper bound the run was configured with, or None.

    Returns:
        ``" (outside 75-175)"`` for an out-of-band tempo, otherwise ``""``.
    """
    if min_bpm is None or max_bpm is None:
        return ""
    if min_bpm <= bpm <= max_bpm:
        return ""
    return f" (outside {min_bpm}-{max_bpm})"


def _outside_record(
    filename: str, bpm: int, min_bpm: int, max_bpm: int
) -> dict[str, object]:
    """Build the structured record for one file whose tempo missed the band.

    The band travels with the record, so a summary or a JSON consumer can word
    the shortfall without knowing which flags the run was given.  The tempo is
    the value that was measured and (in a live run) tagged.

    Args:
        filename: The file name, not the full path.
        bpm:      The measured tempo.
        min_bpm:  Lower bound the run was configured with.
        max_bpm:  Upper bound the run was configured with.

    Returns:
        ``{"filename", "bpm", "min_bpm", "max_bpm"}`` for the completion list.
    """
    return {
        "filename": filename,
        "bpm": bpm,
        "min_bpm": min_bpm,
        "max_bpm": max_bpm,
    }


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
    skipped_files: list[dict[str, object]] | None = None,
    error_files: list[dict[str, object]] | None = None,
    outside_range_files: list[dict[str, object]] | None = None,
    **kwargs: Any,
) -> None:
    """
    Process a single audio file for BPM detection and optional tagging.

    Args:
        name:              File name (not full path) of the audio file.
        dir_path:          Directory containing the audio file.
        is_dry_run:        When True, detect BPM but do not write the tag.
        min_bpm:           Lower bound of the band used to choose between
                           octave-equivalent readings; never a clamp.
        max_bpm:           Upper bound of that band.
        analysis_duration: Maximum seconds of audio to pass to librosa.
        slot_idx:          Index of the worker-slot display variable.
        lock:              Threading lock that gates calls to on_progress.
        on_progress:       Callback with signature (n_skipped, n_errors,
                           display_text, log_text) used by BaseFileProcessor.
        skipped_files:     Optional shared list that receives one structured
                           record per refused file; appended under *lock*.
        error_files:       Optional shared list that receives one structured
                           record per failed file; appended under *lock*.
        outside_range_files: Optional shared list that receives one record per
                           file whose measured tempo fell outside the band;
                           appended under *lock*.
        **kwargs:          Extra keyword arguments forwarded by the base class
                           (e.g. slot_vars).
    """
    slot_vars: list[Any] | None = kwargs.get("slot_vars")
    if slot_vars is not None:
        slot_vars[slot_idx].set(f"Analyzing: {name[:25]}...")

    full_path: str = os.path.join(dir_path, name)

    try:
        bpm: int = detect_bpm(full_path, analysis_duration, min_bpm, max_bpm)
    except NoTempoDetectedError as exc:
        # Beatless audio is not a failure: there is simply nothing to tag. The
        # old behaviour clamped the tracker's zero estimate to min_bpm and
        # wrote that invented value, which looks exactly like a measurement.
        reason = failure_reason(exc)
        display = f"[SKIP] {name}: {reason}"
        log = f"[SKIP] {name}: {reason}\n"
        logger.info("[SKIP] %s - %s", name, reason)
        with lock:
            if skipped_files is not None:
                skipped_files.append(_skip_record(name, reason, exc))
            on_progress(n_skipped=1, n_errors=0, display_text=display, log_text=log)
        return
    except BPMDetectionError as exc:
        reason = failure_reason(exc)
        log_handled_failure(
            logger,
            "[BPMDetectionError] process_single_file failed for '%s': %s",
            name,
            reason,
            exc=exc,
        )
        display = f"[ERROR] {name}: {reason}"
        log = f"[ERROR] {name}: BPM detection failed — {reason}\n"
        with lock:
            if error_files is not None:
                error_files.append(_error_record(name, reason, exc))
            on_progress(n_skipped=0, n_errors=1, display_text=display, log_text=log)
        return

    # NOTE: detect_bpm() can return a tempo outside [min_bpm, max_bpm]: the
    # band chooses between octave-equivalent readings but never overwrites a
    # measurement the onsets support (D108). The value is tagged as measured
    # and the file's line says it is out of band. There is deliberately no
    # range check that skips it — a real tempo outside the band is still a
    # real tempo, and the user chose that band as a prior, not as a filter.

    note: str = _range_note(bpm, min_bpm, max_bpm)
    status: ProcessingStatus = ProcessingStatus.DRY_RUN
    action: str = f"BPM {bpm}"

    if not is_dry_run:
        if slot_vars is not None:
            slot_vars[slot_idx].set(f"Tagging: {name[:25]}...")

        existing_bpm: Optional[int] = read_bpm(full_path)
        write_bpm(full_path, bpm)
        status = ProcessingStatus.TAGGED
        logger.info("[TAGGED] %s - BPM %d%s (was %s)", name, bpm, note, existing_bpm)

        if existing_bpm and existing_bpm != bpm:
            action += f" (was {existing_bpm})"
        action += note
    else:
        action += note
        logger.info("[DRY RUN] %s - BPM %d%s", name, bpm, note)

    status_label: str = status.name.replace("_", " ")  # DRY_RUN → DRY RUN
    display = f"[{status_label}] {name} → {action}"
    log = f"[{status_label}] {name} | BPM {bpm}{note}\n"

    with lock:
        if note and outside_range_files is not None:
            outside_range_files.append(_outside_record(name, bpm, min_bpm, max_bpm))
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
        ``{"status": "ok", "bpm": <int>}`` on success,
        ``{"status": "no_tempo", "error": <str>, "onset_periodicity":
        <float | None>}`` when the audio has no discernible beat, or
        ``{"status": "error", "error": <str>}`` on failure.
    """
    try:
        bpm = detect_bpm(file_path, analysis_duration, min_bpm, max_bpm)
        return {"status": "ok", "bpm": bpm}
    except NoTempoDetectedError as exc:
        record = _skip_record(os.path.basename(file_path), failure_reason(exc), exc)
        return {
            "status": "no_tempo",
            "error": record["reason"],
            "onset_periodicity": record["onset_periodicity"],
        }
    except BPMDetectionError as exc:
        reason = failure_reason(exc)
        log_handled_failure(
            logger,
            "[BPMDetectionError] _detect_bpm_cpu failed for '%s': %s",
            file_path,
            reason,
            exc=exc,
        )
        return {
            "status": "error",
            "error": reason,
            "error_type": type(exc).__name__,
        }
    except (ValueError, OSError, RuntimeError) as exc:
        reason = failure_reason(exc)
        log_handled_failure(
            logger,
            "[Unexpected] _detect_bpm_cpu failed for '%s': %s",
            file_path,
            reason,
            exc=exc,
        )
        return {
            "status": "error",
            "error": reason,
            "error_type": type(exc).__name__,
        }


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
    skipped_files = kwargs.get("skipped_files")
    error_files = kwargs.get("error_files")
    outside_range_files = kwargs.get("outside_range_files")
    if slot_vars is not None:
        slot_vars[slot_idx].set(f"Processing: {filename[:25]}...")

    full_path: str = os.path.join(dir_path, filename)

    if result.get("status") == "no_tempo":
        reason = str(result.get("error", "unknown error"))
        score = result.get("onset_periodicity")
        display = f"[SKIP] {filename}: {reason}"
        log = f"[SKIP] {filename}: {reason}\n"
        with lock:
            if isinstance(skipped_files, list):
                skipped_files.append(
                    {
                        "filename": filename,
                        "reason": reason,
                        "onset_periodicity": (
                            float(score) if isinstance(score, (int, float)) else None
                        ),
                    }
                )
            on_progress(n_skipped=1, n_errors=0, display_text=display, log_text=log)
        return

    if result.get("status") == "error":
        reason = str(result.get("error", "unknown error"))
        error_type = str(result.get("error_type", "BPMDetectionError"))
        display = f"[ERROR] {filename}: {reason}"
        log = f"[ERROR] {filename}: BPM detection failed — {reason}\n"
        with lock:
            if isinstance(error_files, list):
                error_files.append(
                    {
                        "filename": filename,
                        "reason": reason,
                        "error_type": error_type,
                    }
                )
            on_progress(n_skipped=0, n_errors=1, display_text=display, log_text=log)
        return

    bpm: int = result["bpm"]  # type: ignore[assignment]
    note = _range_note(bpm, kwargs.get("min_bpm"), kwargs.get("max_bpm"))

    if not is_dry_run:
        if slot_vars is not None:
            slot_vars[slot_idx].set(f"Tagging: {filename[:25]}...")

        existing_bpm: int | None = read_bpm(full_path)
        write_bpm(full_path, bpm)

        action = f"BPM {bpm}"
        if existing_bpm and existing_bpm != bpm:
            action += f" (was {existing_bpm})"
        action += note
        display = f"[TAGGED] {filename} \u2192 {action}"
        log = f"[TAGGED] {filename} | BPM {bpm}{note}\n"
        logger.info(
            "[TAGGED] %s - BPM %d%s (was %s)", filename, bpm, note, existing_bpm
        )
    else:
        display = f"[DRY RUN] {filename} \u2192 BPM {bpm}{note}"
        log = f"[DRY RUN] {filename} | BPM {bpm}{note}\n"
        logger.info("[DRY RUN] %s - BPM %d%s", filename, bpm, note)

    with lock:
        if note and isinstance(outside_range_files, list):
            band = kwargs.get("min_bpm")
            top = kwargs.get("max_bpm")
            if isinstance(band, int) and isinstance(top, int):
                outside_range_files.append(_outside_record(filename, bpm, band, top))
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
        min_bpm:           Lower bound of the band used to choose between
                           octave-equivalent readings; never a clamp.
        max_bpm:           Upper bound of that band.
        analysis_duration: Seconds of audio to pass to librosa.
        slot_vars:         List of tk.StringVar for worker-slot status labels.
        slot_queue:        Accepted for interface compatibility; not used directly.
        on_progress:       UI progress callback forwarded to BaseFileProcessor.
        on_complete:       Completion callback forwarded to BaseFileProcessor.
        on_error:          Error callback forwarded to BaseFileProcessor.
        parallel_mode:     When True, use ProcessPoolExecutor for CPU-bound
            detection; when False (default), use ThreadPoolExecutor.
        max_workers:       Number of parallel workers.  Defaults to
            ``default_max_workers()``.
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

    # One compile of librosa's lazy numba kernels, before any worker thread
    # can trigger (and contend on) its own copy — see PLAN_feature_expansion P6.
    warm_analysis_stack()

    processor = BPMAnalyzerProcessor(
        # Never build a pool wider than the caller's slot grid: the thread
        # path sizes its queue from this count and the worker writes
        # slot_vars[slot_idx], so a surplus worker raises IndexError (D66).
        max_workers=cap_workers_to_slot_grid(
            max_workers or default_max_workers(), slot_vars
        ),
        parallel_mode=parallel_mode,
    )

    # Structured skip records for the CLI's --json output.  Appended by the
    # thread worker under its progress lock and by the process-pool result
    # handler in the main thread; sorted once at completion so output order is
    # deterministic regardless of which worker finished first.
    skipped_files: list[dict[str, object]] = []
    error_files: list[dict[str, object]] = []
    # Files whose measured tempo fell outside the configured band.  They are
    # neither skipped nor failed - they were tagged as measured - so they get
    # their own list and the completion summary counts them (D109).
    outside_range_files: list[dict[str, object]] = []

    def _complete(**cb_kwargs: object) -> None:
        on_complete(
            **cb_kwargs,
            skipped_files=sorted(
                skipped_files, key=lambda record: str(record["filename"])
            ),
            error_files=sorted(error_files, key=lambda record: str(record["filename"])),
            outside_range_files=sorted(
                outside_range_files, key=lambda record: str(record["filename"])
            ),
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
            "skipped_files": skipped_files,
            "error_files": error_files,
            "outside_range_files": outside_range_files,
        }
        combined_kwargs: dict[str, object] = {**cpu_kwargs, **handler_kwargs}

        processor.run_cpu_bound_processing(
            dir_path=dir_path,
            cpu_worker=_detect_bpm_cpu,
            result_handler=_handle_bpm_result,
            on_progress=on_progress,
            on_complete=_complete,
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
                    skipped_files=skipped_files,
                    error_files=error_files,
                    outside_range_files=outside_range_files,
                    **kwargs,
                )

        processor.run_parallel_processing(
            dir_path=dir_path,
            processor_func=processor_func,
            on_progress=on_progress,
            on_complete=_complete,
            on_error=on_error,
            extensions=SUPPORTED_EXTENSIONS,
        )
