"""
file_processor.py
Parallel fingerprinting + AcoustID lookup + optional tag writing using
BaseFileProcessor.

Each file is a self-contained job: generate the Chromaprint via fpcalc,
optionally query AcoustID, optionally write the AcoustID tags.  Worker slot
release happens only in ``finally`` so the slot queue can never be
over-emptied.

Changed in 1.2.0: optional MusicBrainz enrichment — ISRC retrieval, release
facts, and the MusicBrainz near-tie break — plus the ``--write-isrc`` tag
write (PLAN_feature_expansion.md D28, D29, D31).  An enrichment failure never
changes a file's status: the file keeps the status its AcoustID outcome earned
and the failure is recorded in ``MBEnrichment.note``.

Also in 1.2.0: optional ISRC *submission* (``--submit-isrc``).  After the batch,
the ISRCs each file's own tags carry are offered to MusicBrainz for its matched
recording, minus the ones already registered.  A dry run renders the exact XML
payload instead of posting it, and no submission outcome ever changes a file's
status — the edit is supplementary and the files are already tagged.

Changed in 1.4.0: artist/title and album reads of one file share a single
handler load (PLAN D55).

Changed in 2.4.1: takes ``TagHandlerFactory`` from
``audio_suite_shared.tag_handler_factory``, the leaf module that owns the
handler table (WP-2).

Changed in 2.4.3: the message formatters (`_result_display`, `_match_message`,
`_MESSAGE_STATUSES`), the tag-write helpers (`_write_mbids_for`,
`_write_isrc_for`, `_release_facts_for`, `_commit_match_tags`) and the album
plus ISRC phases moved to `fingerprint_messages` / `fingerprint_tags` /
`fingerprint_phases`; every name is re-exported here
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
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
from audio_suite_shared.batch_undo import get_active_batch_id
from audio_suite_shared.constants import DEFAULT_MAX_WORKERS
from audio_suite_shared.exceptions import (
    AudioSuiteError,
    handle_audio_errors,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.file_processor_base import BaseFileProcessor
from audio_suite_shared.tag_handler_factory import TagHandlerFactory

from .acoustid_client import AcoustidClient, resolve_best_match
from .exceptions import FingerprintError
from .fingerprint_messages import _MESSAGE_STATUSES as _MESSAGE_STATUSES
from .fingerprint_messages import _match_message as _match_message
from .fingerprint_messages import _result_display as _result_display
from .fingerprint_phases import _apply_album_decision as _apply_album_decision
from .fingerprint_phases import _finalize_album_file as _finalize_album_file
from .fingerprint_phases import _run_album_phase as _run_album_phase
from .fingerprint_phases import _run_isrc_submission as _run_isrc_submission
from .fingerprint_phases import (
    collect_isrc_submissions as collect_isrc_submissions,
)
from .fingerprint_tags import _commit_match_tags as _commit_match_tags
from .fingerprint_tags import _release_facts_for as _release_facts_for
from .fingerprint_tags import _write_isrc_for as _write_isrc_for
from .fingerprint_tags import _write_mbids_for as _write_mbids_for
from .fingerprinter import generate_fingerprint, resolve_fpcalc
from .models import (
    AcoustidRecording,
    FingerprintFileResult,
    FingerprintParams,
    FingerprintStatus,
    MBEnrichment,
    status_text,
)
from .musicbrainz_client import (
    MBAuth,
    MusicBrainzClient,
    resolve_ambiguous_with_mb,
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
    mb_client: MusicBrainzClient | None = None


#: Statuses whose display line carries the detail message after the filename.


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


def _enrich_with_mb(
    params: FingerprintParams,
    mb_client: MusicBrainzClient,
    best: AcoustidRecording,
    ambiguous: bool,
    tag_resolved: bool,
    recordings: tuple[AcoustidRecording, ...],
    artist_tag: str,
    title_tag: str,
    album_tag: str,
    file_path: str,
) -> tuple[AcoustidRecording, MBEnrichment]:
    """Attach MusicBrainz facts to a matched candidate.

    Runs only when enrichment is enabled and a candidate was matched.  Two
    things happen, in one recording lookup where possible:

    1. an AcoustID near-tie the file's own tags could not settle is offered to
       MusicBrainz (``resolve_ambiguous_with_mb``), which may replace the
       rank-order pick;
    2. the chosen recording's ISRCs and its selected release's facts are
       retrieved for display, logging and the optional ISRC tag write.

    Args:
        params: Runtime parameters (the release region preference).
        mb_client: The run's MusicBrainz client (rate-limited, caching).
        best: The candidate chosen so far.
        ambiguous: Whether the AcoustID scores were a near-tie.
        tag_resolved: Whether the file's tags already settled that near-tie.
        recordings: The full candidate list (for the tie-break).
        artist_tag: The file's existing artist tag.
        title_tag: The file's existing title tag.
        album_tag: The file's existing album tag.
        file_path: Absolute path of the file.

    Returns:
        Tuple ``(candidate, enrichment)``.  The candidate is the MusicBrainz-
        resolved one when the tie was broken by facts and the rank-order pick
        otherwise; the enrichment always carries the failure reason in
        ``note`` when a lookup could not answer.
    """
    evidence = ""
    resolved = False
    if ambiguous and not tag_resolved:
        tie = resolve_ambiguous_with_mb(
            recordings,
            mb_client,
            album_tag=album_tag,
            title_tag=title_tag,
            artist_tag=artist_tag,
        )
        best = tie.recording
        resolved = tie.resolved
        evidence = tie.evidence

    result = mb_client.get_recording(best.recording_id)
    if not result.ok or result.value is None:
        return best, MBEnrichment(
            recording_id=best.recording_id,
            resolved_ambiguity=resolved,
            evidence=evidence,
            note=result.reason or f"MusicBrainz lookup {result.status}.",
        )

    recording = result.value
    return best, MBEnrichment(
        recording_id=best.recording_id,
        isrcs=recording.isrcs,
        release=_release_facts_for(params, mb_client, best, album_tag, file_path),
        resolved_ambiguity=resolved,
        evidence=evidence,
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
    try:
        handler = TagHandlerFactory.get_handler(full_path)
        artist_tag, title_tag = handler.read_artist_title()
    # Changed in 2.4.1: BLE001 triage (WP-7 of
    # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
    except Exception as exc:  # noqa: BLE001 - tie-break tags are optional evidence
        logger.debug("Could not read tags from %s: %s", full_path, exc)
        handler = None
        artist_tag, title_tag = "Unknown", "Unknown"
    best, ambiguous, tag_resolved = resolve_best_match(
        lookup.recordings, artist_tag, title_tag
    )

    enrichment: MBEnrichment | None = None
    if (
        best is not None
        and best.recording_id
        and job.params.musicbrainz
        and job.mb_client is not None
    ):
        _, album_tag = handler.read_artist_album() if handler is not None else ("", "")
        best, enrichment = _enrich_with_mb(
            job.params,
            job.mb_client,
            best,
            ambiguous,
            tag_resolved,
            lookup.recordings,
            artist_tag,
            title_tag,
            album_tag,
            full_path,
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
        recording_id=best.recording_id,
        isrcs=enrichment.isrcs if enrichment is not None else (),
        mb=enrichment,
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
    mb_auth: MBAuth | None = None,
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
        mb_auth:            Credentials for ``--submit-isrc``.  Never stored on
                            the params: a token is not part of a run's
                            description, so it cannot leak into a log or a
                            JSON dump from there.

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

    # One MusicBrainz client for the whole run: its per-entity cache is what
    # keeps an album to one recording request per unique recording plus one
    # release request, and its rate limiter is shared by every worker thread.
    mb_client: MusicBrainzClient | None = None
    if params.musicbrainz and params.lookup_enabled:
        mb_client = MusicBrainzClient()

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

    start = time.monotonic()
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
            mb_client=mb_client,
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

    isrc_payload: dict[str, Any] = {}
    if params.submit_isrc:
        isrc_payload, isrc_lines, isrc_display = _run_isrc_submission(
            results, params, mb_client, mb_auth
        )
        for line in isrc_lines:
            log_entries.append(f"{line}\n")
        on_progress(
            processed=processed[0],
            total=total,
            errors=errors[0],
            display_text=isrc_display,
        )

    counts = _summarise_results(results)
    completion: dict[str, Any] = {
        "total": total,
        "processed": processed[0],
        "skipped": counts["lookup_skipped"],
        "errors": errors[0],
        "duration_secs": time.monotonic() - start,
        "log_entries": log_entries,
        "results": results,
        "counts": counts,
    }
    if isrc_payload:
        completion["isrc_submission"] = isrc_payload
    on_complete(**completion)


__all__ = [
    "FingerprintFileResult",
    "FingerprintParams",
    "FingerprintProcessor",
    "run_fingerprinting",
    "write_acoustid_tags",
    "AcoustidRecording",
]
