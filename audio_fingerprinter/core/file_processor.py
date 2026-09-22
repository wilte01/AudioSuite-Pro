"""
file_processor.py
Parallel fingerprinting + AcoustID lookup + optional tag writing using
BaseFileProcessor.

Each file is a self-contained job: generate the Chromaprint via fpcalc,
optionally query AcoustID, optionally write the AcoustID tags.  Worker slot
release happens only in ``finally`` so the slot queue can never be
over-emptied.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from queue import Queue
from typing import Any

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import get_active_batch_id, use_batch
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.tag_helper_reader import read_artist_title

from .acoustid_client import AcoustidClient, resolve_best_match
from .exceptions import FingerprintError
from .fingerprinter import generate_fingerprint, resolve_fpcalc
from .models import AcoustidRecording, FingerprintFileResult, FingerprintParams
from .tag_writer import write_acoustid_tags

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _FingerprintJob:
    """All context needed to fingerprint one audio file."""

    filename: str
    folder_path: str
    fpcalc_path: str
    params: FingerprintParams
    client: AcoustidClient | None
    api_key: str
    slot_idx: int
    on_slot_update: Callable[[int, str], None] | None
    slot_queue: Queue[Any]
    lock: threading.Lock
    on_progress: Callable[..., None]
    results: list[FingerprintFileResult]
    undo_batch: str | None
    processor: "FingerprintProcessor"


def _result_display(result: FingerprintFileResult) -> str:
    """Build the one-line status text streamed to the Processing tab / CLI."""
    if result.status == "ERROR":
        return f"[ERROR] {result.filename}: {result.message}"
    if result.status in {"MATCHED", "TAGGED", "TAG WRITE FAILED"}:
        return f"[{result.status}] {result.filename} — {result.message}"
    return f"[{result.status}] {result.filename}"


def _fingerprint_worker(job: _FingerprintJob) -> None:
    """Acquire a slot, process one file, store the result, release the slot."""
    slot_idx = job.slot_queue.get()
    full_path = os.path.join(job.folder_path, job.filename)

    def _report(result: FingerprintFileResult) -> None:
        with job.lock:
            job.results.append(result)
        job.on_progress(
            n_errors=1 if result.status == "ERROR" else 0,
            display_text=_result_display(result),
        )

    try:
        if job.on_slot_update:
            job.on_slot_update(slot_idx, f"Fingerprinting: {job.filename[:25]}...")

        with job.lock:
            if not os.path.isfile(full_path):
                _report(
                    FingerprintFileResult(
                        file_path=full_path,
                        filename=job.filename,
                        status="ERROR",
                        message="File no longer exists.",
                    )
                )
                return

        _report(_process_file(job, full_path))

    except FingerprintError as exc:
        logger.error("Fingerprint failed for %s: %s", job.filename, exc, exc_info=True)
        _report(
            FingerprintFileResult(
                file_path=full_path,
                filename=job.filename,
                status="ERROR",
                message=user_message_for(exc),
            )
        )
    except (OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc, context={"file": job.filename})
        logger.error(
            "Fingerprint processing failed for %s: %s",
            job.filename,
            mapped,
            exc_info=True,
        )
        _report(
            FingerprintFileResult(
                file_path=full_path,
                filename=job.filename,
                status="ERROR",
                message=user_message_for(mapped),
            )
        )
    finally:
        if job.on_slot_update:
            job.on_slot_update(slot_idx, "IDLE")
        job.slot_queue.put(slot_idx)


def _process_file(job: _FingerprintJob, full_path: str) -> FingerprintFileResult:
    """Fingerprint one file and optionally look it up / tag it.

    Args:
        job: Carrier dataclass with runtime context.
        full_path: Absolute path of the file.

    Returns:
        A ``FingerprintFileResult`` summarising the outcome.
    """
    fingerprint = generate_fingerprint(
        full_path,
        fpcalc_path=job.fpcalc_path,
        max_length=job.params.max_length,
    )

    if not job.params.lookup_enabled or not job.api_key:
        return FingerprintFileResult(
            file_path=full_path,
            filename=job.filename,
            duration=fingerprint.duration,
            fingerprint=fingerprint.fingerprint,
            status="LOOKUP SKIPPED",
            message="Lookup disabled or no API key.",
        )

    client = job.client
    if client is None:
        return FingerprintFileResult(
            file_path=full_path,
            filename=job.filename,
            duration=fingerprint.duration,
            fingerprint=fingerprint.fingerprint,
            status="LOOKUP SKIPPED",
            message="Lookup disabled.",
        )

    lookup = client.lookup(fingerprint.fingerprint, int(fingerprint.duration))
    if lookup.status == "error":
        return FingerprintFileResult(
            file_path=full_path,
            filename=job.filename,
            duration=fingerprint.duration,
            fingerprint=fingerprint.fingerprint,
            status="ERROR",
            message=lookup.error or "AcoustID lookup failed.",
        )

    # AcoustID can rank a remix/cover built on the same audio above the
    # original; when the top candidates are effectively tied, the file's
    # existing artist/title tags break the tie.
    artist_tag, title_tag = read_artist_title(full_path)
    best, ambiguous, tag_resolved = resolve_best_match(
        lookup.recordings, artist_tag, title_tag
    )
    if best is None or not best.recording_id:
        return FingerprintFileResult(
            file_path=full_path,
            filename=job.filename,
            duration=fingerprint.duration,
            fingerprint=fingerprint.fingerprint,
            status="NO MATCH",
            message="No candidate above the score threshold.",
        )

    title = f"{best.title}" + (f" — {best.artist}" if best.artist else "")
    match_text = title or best.recording_id
    message = f"{match_text} (score {best.score:.2f})"
    if tag_resolved:
        message += "; matched file tags"
    elif ambiguous:
        runner = lookup.recordings[1]
        runner_text = f"{runner.title}" + (
            f" — {runner.artist}" if runner.artist else ""
        )
        if runner_text:
            message += f"; ambiguous — also {runner_text} (score {runner.score:.2f})"
    result = FingerprintFileResult(
        file_path=full_path,
        filename=job.filename,
        duration=fingerprint.duration,
        fingerprint=fingerprint.fingerprint,
        status="MATCHED",
        message=message,
        acoustid_id=best.acoustid_id,
        recordings=lookup.recordings,
    )

    if not (job.params.write_tags and not job.params.is_dry_run):
        return result

    with use_batch(job.undo_batch):
        ok, msg = write_acoustid_tags(
            full_path, fingerprint.fingerprint, best.acoustid_id
        )

    if not ok:
        return FingerprintFileResult(
            file_path=full_path,
            filename=job.filename,
            duration=fingerprint.duration,
            fingerprint=fingerprint.fingerprint,
            status="TAG WRITE FAILED",
            message=f"{message} — {msg}",
            acoustid_id=best.acoustid_id,
            recordings=lookup.recordings,
        )

    return FingerprintFileResult(
        file_path=full_path,
        filename=job.filename,
        duration=fingerprint.duration,
        fingerprint=fingerprint.fingerprint,
        status="TAGGED",
        message=message,
        acoustid_id=best.acoustid_id,
        recordings=lookup.recordings,
        tag_written=True,
    )


class FingerprintProcessor(BaseFileProcessor):
    """File processor for fingerprinting and AcoustID identification."""

    def __init__(self) -> None:
        super().__init__(operation_type="fingerprint")


def _summarise_results(
    results: list[FingerprintFileResult],
) -> dict[str, int]:
    """Count result statuses for the completion summary."""
    counts = {
        "identified": 0,
        "no_match": 0,
        "tagged": 0,
        "lookup_skipped": 0,
        "errors": 0,
    }
    for result in results:
        if result.status == "ERROR":
            counts["errors"] += 1
        elif result.status == "TAG WRITE FAILED":
            counts["errors"] += 1
        elif result.status == "TAGGED":
            counts["tagged"] += 1
            counts["identified"] += 1
        elif result.status in {"MATCHED", "IDENTIFIED"}:
            counts["identified"] += 1
        elif result.status == "NO MATCH":
            counts["no_match"] += 1
        elif result.status == "LOOKUP SKIPPED":
            counts["lookup_skipped"] += 1
    return counts


@handle_audio_errors(reraise=False, context="fingerprint_run")
def run_fingerprinting(
    dir_path: str,
    api_key: str,
    params: FingerprintParams,
    slot_vars: list[Any],
    slot_queue: Queue[Any],
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
    on_slot_update: Callable[[int, str], None] | None = None,
) -> None:
    """Walk the directory tree and fingerprint every audio file.

    Args:
        dir_path:           Root directory to scan.
        api_key:            AcoustID API key (may be empty when lookup is
                            disabled).
        params:             Frozen runtime parameters.
        slot_vars:          Legacy tk.StringVar slot list; only used when
                            ``on_slot_update`` is not supplied.
        slot_queue:         Queue of available worker slot indices.
        on_progress:        Callback(processed, total, errors, display_text)
                            per file, where ``display_text`` is a one-line
                            status string for the live log list.
        on_complete:        Callback(**kwargs) after all files finish,
                            including ``results`` (list of
                            ``FingerprintFileResult``) and ``log_entries``.
        on_error:           Callback(message) on fatal errors.
        on_slot_update:     Optional callback(slot_idx, text) for live status.

    Returns:
        None.
    """
    fpcalc_path = params.fpcalc_path
    try:
        fpcalc_path = resolve_fpcalc(fpcalc_path or None)
    except FingerprintError as exc:
        logger.error("fpcalc not available: %s", exc, exc_info=True)
        on_error(user_message_for(exc))
        return

    if params.lookup_enabled and not api_key:
        on_error("Lookup is enabled but no AcoustID API key is configured.")
        return

    client: AcoustidClient | None = None
    if params.lookup_enabled:
        client = AcoustidClient(
            api_key,
            min_score=params.threshold,
            requests_per_second=params.requests_per_second,
        )

    processor = FingerprintProcessor()

    all_work: list[tuple[str, list[str]]] = []
    try:
        for root, _, _ in os.walk(dir_path):
            files = processor.discover_audio_files(root, SUPPORTED_EXTENSIONS)
            if files:
                all_work.append((root, files))
    except AudioSuiteError as exc:
        logger.error("Directory scan failed: %s", exc, exc_info=True)
        on_error(user_message_for(exc))
        return
    except (OSError, ValueError) as exc:
        mapped = map_to_audio_error(exc)
        logger.error("Directory scan failed: %s", mapped, exc_info=True)
        on_error(user_message_for(mapped))
        return

    total = sum(len(f) for _, f in all_work)
    if total == 0:
        on_error("No audio files found in the selected directory.")
        return

    lock = threading.Lock()
    processed = [0]
    errors = [0]
    results: list[FingerprintFileResult] = []

    _slot_update = on_slot_update
    if _slot_update is None and slot_vars:

        def _slot_update(idx: int, text: str) -> None:
            slot_vars[idx].set(text)

    def _on_file_progress(n_errors: int, display_text: str = "") -> None:
        if n_errors == 0:
            processed[0] += 1
        errors[0] += n_errors
        on_progress(
            processed=processed[0],
            total=total,
            errors=errors[0],
            display_text=display_text,
        )

    start = time.time()
    undo_batch = get_active_batch_id()

    jobs = [
        _FingerprintJob(
            filename=name,
            folder_path=folder_path,
            fpcalc_path=fpcalc_path,
            params=params,
            client=client,
            api_key=api_key,
            slot_idx=i % processor.max_workers,
            on_slot_update=_slot_update,
            slot_queue=slot_queue,
            lock=lock,
            on_progress=_on_file_progress,
            results=results,
            undo_batch=undo_batch,
            processor=processor,
        )
        for folder_path, audio_files in all_work
        for i, name in enumerate(audio_files)
    ]

    processor.process_batch(jobs, _fingerprint_worker, max_workers=DEFAULT_MAX_WORKERS)

    log_entries: list[str] = []
    for result in sorted(results, key=lambda r: r.file_path):
        if result.status == "ERROR":
            log_entries.append(f"[ERROR] {result.filename}\n    {result.message}\n")
        elif result.status == "LOOKUP SKIPPED":
            log_entries.append(f"[LOOKUP SKIPPED] {result.filename}\n")
        elif result.status in {"MATCHED", "TAGGED", "TAG WRITE FAILED"}:
            log_entries.append(
                f"[{result.status}] {result.filename}\n    {result.message}\n"
            )

    counts = _summarise_results(results)
    on_complete(
        total=total,
        processed=processed[0],
        skipped=counts["lookup_skipped"],
        errors=errors[0],
        duration_secs=time.time() - start,
        log_entries=log_entries,
        results=results,
        counts=counts,
    )


__all__ = [
    "FingerprintFileResult",
    "FingerprintParams",
    "FingerprintProcessor",
    "run_fingerprinting",
    "write_acoustid_tags",
    "AcoustidRecording",
]
