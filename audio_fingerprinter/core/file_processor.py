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
from dataclasses import dataclass, replace
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
from audio_suite_shared.tag_helper_reader import read_artist_album, read_artist_title

from .acoustid_client import AcoustidClient, resolve_best_match
from .album_cluster import (
    AlbumFile,
    AlbumFileDecision,
    group_albums,
    resolve_album,
)
from .exceptions import FingerprintError
from .fingerprinter import generate_fingerprint, resolve_fpcalc
from .mbid_writer import select_mbid_tags, write_mbid_tags
from .models import (
    AcoustidRecording,
    Fingerprint,
    FingerprintFileResult,
    FingerprintParams,
    FingerprintStatus,
    status_text,
)
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


#: Statuses whose display line carries the detail message after the filename.
_MESSAGE_STATUSES: frozenset[FingerprintStatus] = frozenset(
    {
        FingerprintStatus.MATCHED,
        FingerprintStatus.TAGGED,
        FingerprintStatus.TAG_WRITE_FAILED,
        FingerprintStatus.ALBUM_AMBIGUOUS,
    }
)


def _result_display(result: FingerprintFileResult) -> str:
    """Build the one-line status text streamed to the Processing tab / CLI."""
    label = status_text(result.status)
    if result.status == FingerprintStatus.ERROR:
        return f"[{label}] {result.filename}: {result.message}"
    if result.status in _MESSAGE_STATUSES:
        return f"[{label}] {result.filename} — {result.message}"
    return f"[{label}] {result.filename}"


def _match_message(
    best: AcoustidRecording,
    ambiguous: bool,
    tag_resolved: bool,
    recordings: tuple[AcoustidRecording, ...],
) -> str:
    """Build the per-file match detail, surfacing ambiguity by convention.

    Near-ties that the file tags settled are marked "matched file tags";
    unresolved near-ties surface the runner-up candidate in the message.
    """
    title = f"{best.title}" + (f" — {best.artist}" if best.artist else "")
    message = f"{title or best.recording_id} (score {best.score:.2f})"
    if tag_resolved:
        message += "; matched file tags"
    elif ambiguous and len(recordings) > 1:
        runner = recordings[1]
        runner_text = f"{runner.title}" + (
            f" — {runner.artist}" if runner.artist else ""
        )
        if runner_text:
            message += f"; ambiguous — also {runner_text} (score {runner.score:.2f})"
    return message


def _fingerprint_worker(job: _FingerprintJob) -> None:
    """Acquire a slot, process one file, store the result, release the slot."""
    slot_idx = job.slot_queue.get()
    full_path = os.path.join(job.folder_path, job.filename)

    def _report(result: FingerprintFileResult) -> None:
        with job.lock:
            job.results.append(result)
        job.on_progress(
            n_errors=1 if result.status == FingerprintStatus.ERROR else 0,
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
                        status=FingerprintStatus.ERROR,
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
                status=FingerprintStatus.ERROR,
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
                status=FingerprintStatus.ERROR,
                message=user_message_for(mapped),
            )
        )
    finally:
        if job.on_slot_update:
            job.on_slot_update(slot_idx, "IDLE")
        job.slot_queue.put(slot_idx)


def _write_mbids_for(
    params: FingerprintParams,
    recording: AcoustidRecording,
    file_path: str,
) -> str:
    """Select and write the MusicBrainz identifiers, returning a note.

    A failed MBID write does not fail the file — the AcoustID tags are already
    committed and the identifiers are additive enrichment. The message says so
    rather than reporting the file as untagged.

    Args:
        params: Runtime parameters (the opt-in flag and region preference).
        recording: The matched AcoustID candidate.
        file_path: Absolute path of the file being tagged.

    Returns:
        A short note for the per-file result message, empty when there was
        nothing to write.
    """
    album_title = ""
    try:
        _, album_title = read_artist_album(file_path)
    except (OSError, AudioSuiteError):
        album_title = ""
    tags = select_mbid_tags(
        recording,
        album_title=album_title,
        file_path=file_path,
        region=params.mbid_region,
    )
    if not tags:
        return ""
    ok, msg = write_mbid_tags(file_path, tags)
    if not ok:
        logger.warning("MusicBrainz tag write failed for %s: %s", file_path, msg)
        return f"MBID write failed: {msg}"
    return msg


def _commit_match_tags(
    matched: FingerprintFileResult,
    recording: AcoustidRecording,
    params: FingerprintParams,
    undo_batch: str | None,
) -> FingerprintFileResult:
    """Write the AcoustID tags (and optional MBIDs) for one matched file.

    The single write path shared by per-file matching and album matching: both
    build a ``MATCHED`` result first, then hand it here so the undo batch
    scope, the MBID enrichment and the TAGGED / TAG WRITE FAILED outcomes are
    defined exactly once.

    Args:
        matched: The ``MATCHED`` result carrying the file's path,
            fingerprint, message and candidate list.
        recording: The matched AcoustID candidate.
        params: Runtime parameters, for the MBID opt-in and region preference.
        undo_batch: Active undo batch id for the tag snapshot.

    Returns:
        A copy of ``matched`` with status ``TAGGED`` on success (and
        ``tag_written`` set), or ``TAG WRITE FAILED`` with the writer's
        message appended when the AcoustID write fails.
    """
    message = matched.message
    with use_batch(undo_batch):
        ok, msg = write_acoustid_tags(
            matched.file_path, matched.fingerprint, recording.acoustid_id
        )
        if ok and params.write_mbids:
            mbids = _write_mbids_for(params, recording, matched.file_path)
            if mbids:
                message = f"{message} — {mbids}"

    if not ok:
        return replace(
            matched,
            status=FingerprintStatus.TAG_WRITE_FAILED,
            message=f"{message} — {msg}",
        )

    return replace(
        matched,
        status=FingerprintStatus.TAGGED,
        message=message,
        tag_written=True,
    )


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
            status=FingerprintStatus.LOOKUP_SKIPPED,
            message="Lookup disabled or no API key.",
        )

    client = job.client
    if client is None:
        return FingerprintFileResult(
            file_path=full_path,
            filename=job.filename,
            duration=fingerprint.duration,
            fingerprint=fingerprint.fingerprint,
            status=FingerprintStatus.LOOKUP_SKIPPED,
            message="Lookup disabled.",
        )

    if job.params.album_mode:
        # Album mode defers lookup and matching to the post-batch cluster
        # phase — clustering needs every folder's lookups in hand before
        # it can decide anything.
        return FingerprintFileResult(
            file_path=full_path,
            filename=job.filename,
            duration=fingerprint.duration,
            fingerprint=fingerprint.fingerprint,
            status=FingerprintStatus.ANALYSED,
            message="Fingerprint ready for album matching.",
        )

    lookup = client.lookup(fingerprint.fingerprint, int(fingerprint.duration))
    if lookup.status == "error":
        return FingerprintFileResult(
            file_path=full_path,
            filename=job.filename,
            duration=fingerprint.duration,
            fingerprint=fingerprint.fingerprint,
            status=FingerprintStatus.ERROR,
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
            status=FingerprintStatus.NO_MATCH,
            message="No candidate above the score threshold.",
        )

    matched = FingerprintFileResult(
        file_path=full_path,
        filename=job.filename,
        duration=fingerprint.duration,
        fingerprint=fingerprint.fingerprint,
        status=FingerprintStatus.MATCHED,
        message=_match_message(best, ambiguous, tag_resolved, lookup.recordings),
        acoustid_id=best.acoustid_id,
        recordings=lookup.recordings,
    )

    if not (job.params.write_tags and not job.params.is_dry_run):
        return matched

    return _commit_match_tags(matched, best, job.params, job.undo_batch)


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
        "album_ambiguous": 0,
        "errors": 0,
    }
    for result in results:
        if result.status in {
            FingerprintStatus.ERROR,
            FingerprintStatus.TAG_WRITE_FAILED,
        }:
            counts["errors"] += 1
        elif result.status == FingerprintStatus.TAGGED:
            counts["tagged"] += 1
            counts["identified"] += 1
        elif result.status == FingerprintStatus.MATCHED:
            counts["identified"] += 1
        elif result.status == FingerprintStatus.NO_MATCH:
            counts["no_match"] += 1
        elif result.status == FingerprintStatus.LOOKUP_SKIPPED:
            counts["lookup_skipped"] += 1
        elif result.status == FingerprintStatus.ALBUM_AMBIGUOUS:
            counts["album_ambiguous"] += 1
    return counts


def _finalize_album_file(
    result: FingerprintFileResult,
    best: AcoustidRecording | None,
    unmatched_status: FingerprintStatus,
    message: str,
    recordings: tuple[AcoustidRecording, ...],
    write_enabled: bool,
    undo_batch: str | None,
    params: FingerprintParams,
) -> FingerprintFileResult:
    """Apply one album decision to a file, writing tags when enabled.

    Args:
        result: The interim ``ANALYSED`` result for the file.
        best: The cluster-chosen candidate (``None`` leaves the file
            untagged with ``unmatched_status``).
        unmatched_status: Status for the ``best is None`` case
            (``FingerprintStatus.NO_MATCH`` or
            ``FingerprintStatus.ALBUM_AMBIGUOUS``).
        message: Final per-file status message.
        recordings: The file's full filtered candidate list.
        write_enabled: Whether tags should be written (live + enabled).
        undo_batch: Active undo batch id for the tag snapshot.
        params: Runtime parameters, for the MBID opt-in and region preference.

    Returns:
        The final ``FingerprintFileResult`` (MATCHED / TAGGED /
        TAG WRITE FAILED / NO MATCH / ALBUM AMBIGUOUS).
    """
    if best is None or not best.recording_id:
        return FingerprintFileResult(
            file_path=result.file_path,
            filename=result.filename,
            duration=result.duration,
            fingerprint=result.fingerprint,
            status=unmatched_status,
            message=message,
            recordings=recordings,
        )

    matched = FingerprintFileResult(
        file_path=result.file_path,
        filename=result.filename,
        duration=result.duration,
        fingerprint=result.fingerprint,
        status=FingerprintStatus.MATCHED,
        message=message,
        acoustid_id=best.acoustid_id,
        recordings=recordings,
    )

    if not write_enabled:
        return matched

    return _commit_match_tags(matched, best, params, undo_batch)


def _apply_album_decision(
    file: AlbumFile,
    decision: AlbumFileDecision,
) -> tuple[FingerprintStatus, AcoustidRecording | None, str]:
    """Map one album decision to a result status, candidate, and message.

    Args:
        file: The clustered file (its candidates feed the message).
        decision: The cluster's outcome for this file.

    Returns:
        Tuple ``(status, best, message)`` — *best* is ``None`` for the
        untagged outcomes (NO MATCH / ALBUM AMBIGUOUS).
    """
    if decision.outcome == "ambiguous":
        return (
            FingerprintStatus.ALBUM_AMBIGUOUS,
            None,
            f"album ambiguous — {decision.cluster_title}; left untagged",
        )
    if decision.outcome == "fallback" and decision.best is None:
        return (
            FingerprintStatus.NO_MATCH,
            None,
            "No candidate above the score threshold.",
        )
    if decision.best is None:
        # Defensive: cluster and surviving-fallback outcomes always
        # carry a candidate; log rather than silently mislabel the file.
        logger.warning(
            "Album decision %r for %s carried no candidate.",
            decision.outcome,
            file.file_path,
        )
        return (
            FingerprintStatus.NO_MATCH,
            None,
            "No candidate above the score threshold.",
        )
    if decision.outcome == "cluster":
        message = (
            f"{_match_message(decision.best, False, False, file.recordings)}"
            f"; album consensus {decision.cluster_title}"
        )
    else:
        message = _match_message(
            decision.best,
            decision.ambiguous,
            decision.tag_resolved,
            file.recordings,
        )
    return FingerprintStatus.MATCHED, decision.best, message


def _run_album_phase(
    results: list[FingerprintFileResult],
    client: AcoustidClient,
    params: FingerprintParams,
    undo_batch: str | None,
    processed: list[int],
    errors: list[int],
    on_progress: Callable[..., None],
    on_error: Callable[[str], None],
) -> tuple[bool, list[str]]:
    """Cluster the analysed files per folder and apply the decisions.

    Phase two of album match mode: the parallel batch produced
    ``ANALYSED`` results (fingerprint only); this phase looks every
    pending file up through ``lookup_many``, clusters each folder by
    MusicBrainz release group, and replaces the interim results with
    the final statuses (cluster matches, per-file fallbacks, album
    ambiguities).  Display lines stream through ``on_progress`` without
    touching the already-final processed count.

    Args:
        results: Shared results list; interim entries are replaced.
        client: The rate-limited AcoustID client.
        params: Runtime parameters (``album_min`` used here).
        undo_batch: Active undo batch id for tag snapshots.
        processed: Mutable single-element processed counter.
        errors: Mutable single-element error counter.
        on_progress: The run-level progress callback.
        on_error: Fatal-error callback.

    Returns:
        Tuple ``(ok, report_lines)``.  ``ok`` is False after a fatal
        lookup failure (``on_error`` has then already been called and
        the caller must abort); ``report_lines`` carries the per-album
        cluster summary for the run report.
    """
    pending = [r for r in results if r.status == FingerprintStatus.ANALYSED]
    if not pending:
        return True, []

    def _display(text: str) -> None:
        on_progress(
            processed=processed[0],
            total=len(results),
            errors=errors[0],
            display_text=text,
        )

    def _lookup_progress(done: int, count: int) -> None:
        _display(f"[ALBUM LOOKUP] {done}/{count} files")

    try:
        lookups = client.lookup_many(
            [
                Fingerprint(duration=r.duration, fingerprint=r.fingerprint)
                for r in pending
            ],
            on_progress=_lookup_progress,
        )
    except FingerprintError as exc:
        logger.error("Album-mode lookup failed: %s", exc, exc_info=True)
        on_error(user_message_for(exc))
        return False, []

    finals: dict[str, FingerprintFileResult] = {}
    entries: list[tuple[FingerprintFileResult, AlbumFile]] = []
    for result, lookup in zip(pending, lookups, strict=True):
        if lookup.status == "error":
            errors[0] += 1
            finals[result.file_path] = FingerprintFileResult(
                file_path=result.file_path,
                filename=result.filename,
                duration=result.duration,
                fingerprint=result.fingerprint,
                status=FingerprintStatus.ERROR,
                message=lookup.error or "AcoustID lookup failed.",
            )
            continue
        try:
            artist_tag, title_tag = read_artist_title(result.file_path)
            _, album_tag = read_artist_album(result.file_path)
        except (OSError, AudioSuiteError) as exc:
            logger.warning("Could not read tags from %s: %s", result.file_path, exc)
            artist_tag, title_tag, album_tag = "", "", ""
        entries.append(
            (
                result,
                AlbumFile(
                    file_path=result.file_path,
                    folder_path=os.path.dirname(result.file_path),
                    fingerprint=result.fingerprint,
                    duration=result.duration,
                    artist_tag=artist_tag,
                    title_tag=title_tag,
                    recordings=lookup.recordings,
                    album_tag=album_tag,
                ),
            )
        )

    write_enabled = params.write_tags and not params.is_dry_run
    report_lines: list[str] = []
    for folder_files in group_albums([entry[1] for entry in entries]).values():
        resolution = resolve_album(folder_files, params.album_min)
        report_lines.append(resolution.report_line)
        folder_by_path = {entry[1].file_path: entry for entry in entries}
        for file, decision in zip(folder_files, resolution.decisions, strict=True):
            interim = folder_by_path[file.file_path][0]
            status, best, message = _apply_album_decision(file, decision)
            finals[interim.file_path] = _finalize_album_file(
                interim,
                best,
                status,
                message,
                file.recordings,
                write_enabled,
                undo_batch,
                params,
            )

    for idx, result in enumerate(results):
        final = finals.get(result.file_path)
        if final is not None:
            results[idx] = final
            _display(_result_display(final))

    return True, report_lines


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
        )
        for folder_path, audio_files in all_work
        for i, name in enumerate(audio_files)
    ]

    processor.process_batch(jobs, _fingerprint_worker, max_workers=DEFAULT_MAX_WORKERS)

    report_lines: list[str] = []
    if params.album_mode and client is not None:
        ok, report_lines = _run_album_phase(
            results,
            client,
            params,
            undo_batch,
            processed,
            errors,
            on_progress,
            on_error,
        )
        if not ok:
            return

    log_entries: list[str] = []
    for line in report_lines:
        log_entries.append(f"{line}\n")
    for result in sorted(results, key=lambda r: r.file_path):
        if result.status == FingerprintStatus.ERROR:
            log_entries.append(
                f"[{status_text(result.status)}] {result.filename}\n"
                f"    {result.message}\n"
            )
        elif result.status == FingerprintStatus.LOOKUP_SKIPPED:
            log_entries.append(f"[{status_text(result.status)}] {result.filename}\n")
        elif result.status in {
            FingerprintStatus.MATCHED,
            FingerprintStatus.TAGGED,
            FingerprintStatus.TAG_WRITE_FAILED,
            FingerprintStatus.ALBUM_AMBIGUOUS,
        }:
            log_entries.append(
                f"[{status_text(result.status)}] {result.filename}\n"
                f"    {result.message}\n"
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
