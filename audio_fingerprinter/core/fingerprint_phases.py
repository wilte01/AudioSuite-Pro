"""
fingerprint_phases.py - part of the fingerprinter's per-file pipeline (2.4.3).

WP-9 #4 moved these functions out of
``audio_fingerprinter/core/file_processor.py`` verbatim; that module still
re-exports every name, so existing importers are unaffected.

Changed in 2.4.3: split out of
``audio_fingerprinter.core.file_processor``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Sequence
from typing import Any

from audio_suite_shared.exceptions import (
    AudioSuiteError,
    user_message_for,
)
from audio_suite_shared.tag_handler_factory import TagHandlerFactory
from audio_suite_shared.tag_helper_reader import read_isrcs

from .acoustid_client import AcoustidClient
from .album_cluster import AlbumFile, AlbumFileDecision, group_albums, resolve_album
from .exceptions import FingerprintError
from .fingerprint_messages import _match_message, _result_display
from .fingerprint_tags import _commit_match_tags
from .models import (
    AcoustidRecording,
    Fingerprint,
    FingerprintFileResult,
    FingerprintParams,
    FingerprintStatus,
)
from .musicbrainz_client import (
    EDIT_REVIEW_DAYS,
    ISRCSubmission,
    MBAuth,
    MusicBrainzClient,
    build_isrc_submission_xml,
    isrc_error,
    normalize_isrc,
)

logger = logging.getLogger(f"audio_suite.{__name__}")


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
        recording_id=best.recording_id,
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
            album_handler = TagHandlerFactory.get_handler(result.file_path)
            artist_tag, title_tag = album_handler.read_artist_title()
            _, album_tag = album_handler.read_artist_album()
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


def collect_isrc_submissions(
    results: Sequence[FingerprintFileResult],
) -> tuple[tuple[ISRCSubmission, ...], tuple[str, ...]]:
    """Gather the ISRCs each file's own tags carry, ready to submit.

    The codes come from the *files*, not from MusicBrainz: sending back the
    codes the service already returned would be a guaranteed no-op.  That makes
    this the path for ISRCs a CD rip recorded but MusicBrainz has never seen.

    Codes already registered for the recording (``result.isrcs``, retrieved by
    the enrichment) and codes another file in the batch already contributed are
    dropped here, so the payload only contains work MusicBrainz can act on.

    Args:
        results: Finished per-file results for the run.

    Returns:
        Tuple ``(submissions, notes)``.  ``submissions`` holds one entry per
        recording with at least one new ISRC; ``notes`` are report lines for
        the log (invalid codes, unreadable tags, files with nothing new), which
        are reported rather than silently dropped.
    """
    per_recording: dict[str, list[str]] = {}
    notes: list[str] = []

    for result in sorted(results, key=lambda r: r.file_path):
        try:
            tagged = read_isrcs(result.file_path)
        except (OSError, AudioSuiteError) as exc:
            notes.append(
                f"[ISRC SKIPPED] {result.filename}: could not read its ISRCs ({exc})"
            )
            continue
        if not tagged:
            continue
        if not result.recording_id:
            notes.append(
                f"[ISRC SKIPPED] {result.filename}: {len(tagged)} ISRC(s) found, "
                "but the file matched no MusicBrainz recording to attach them to"
            )
            continue

        recording_id = result.recording_id.strip().lower()
        registered = {normalize_isrc(value) for value in result.isrcs}
        bucket = per_recording.setdefault(recording_id, [])
        known = 0
        added = 0
        for value in tagged:
            problem = isrc_error(value)
            if problem:
                notes.append(f"[ISRC SKIPPED] {result.filename}: {problem}")
                continue
            code = normalize_isrc(value)
            if code in registered or code in bucket:
                known += 1
                continue
            bucket.append(code)
            added += 1
        if known and not added:
            notes.append(
                f"[ISRC] {result.filename}: nothing new to submit — its "
                f"{known} ISRC(s) are already registered on {recording_id}"
            )

    submissions = tuple(
        ISRCSubmission(recording_id=recording_id, isrcs=tuple(sorted(codes)))
        for recording_id, codes in sorted(per_recording.items())
        if codes
    )
    return submissions, tuple(notes)


def _run_isrc_submission(
    results: Sequence[FingerprintFileResult],
    params: FingerprintParams,
    mb_client: MusicBrainzClient | None,
    auth: MBAuth | None,
) -> tuple[dict[str, Any], list[str], str]:
    """Preview or perform the run's one ISRC submission.

    A dry run renders the payload and stops: the XML it logs is exactly the
    body a live run posts, because both come from
    :func:`build_isrc_submission_xml` over the same submissions.  A live run
    needs a usable token; without one nothing is sent and the reason is
    reported, never swallowed.

    Args:
        results: Finished per-file results.
        params: Runtime parameters (``is_dry_run`` decides preview vs post).
        mb_client: The run's MusicBrainz client, or None when enrichment is off.
        auth: Credentials for the submission, when the caller resolved any.

    Returns:
        Tuple ``(payload, log_lines, display_line)``.  ``payload`` is the
        machine-readable record surfaced in the CLI JSON, including the XML.
    """
    submissions, notes = collect_isrc_submissions(results)
    lines = list(notes)
    recordings = len(submissions)
    isrcs = sum(len(submission.isrcs) for submission in submissions)
    xml = build_isrc_submission_xml(submissions)
    payload: dict[str, Any] = {
        "mode": "preview" if params.is_dry_run else "live",
        "status": "nothing to submit",
        "recordings": recordings,
        "isrcs": isrcs,
        "url": "",
        "reason": "",
        "xml": xml,
        "notes": list(notes),
    }

    if not xml:
        lines.append(
            "[ISRC] Nothing to submit: no file carried an ISRC that "
            "MusicBrainz does not already have."
        )
        return payload, lines, "[ISRC] Nothing new to submit."

    if params.is_dry_run:
        payload["status"] = "preview"
        lines.append(
            f"[ISRC PREVIEW] Dry run — would POST {isrcs} ISRC(s) for "
            f"{recordings} recording(s) to MusicBrainz. Exact payload:"
        )
        lines.append(xml.rstrip("\n"))
        return (
            payload,
            lines,
            f"[ISRC PREVIEW] {isrcs} ISRC(s) for {recordings} recording(s) — "
            "not submitted (dry run)",
        )

    if mb_client is None:
        payload["status"] = "not attempted"
        payload["reason"] = "MusicBrainz lookup is off, so no recording was met."
        lines.append(f"[ISRC NOT SUBMITTED] {payload['reason']}")
        return payload, lines, "[ISRC] Not submitted — MusicBrainz lookup is off."

    result = mb_client.submit_isrcs(submissions, auth or MBAuth())
    payload.update(
        status=result.status,
        recordings=result.recordings or recordings,
        isrcs=result.isrcs or isrcs,
        url=result.url,
        reason=result.reason,
    )
    if result.ok:
        lines.append(
            f"[ISRC SUBMITTED] {result.isrcs} ISRC(s) for {result.recordings} "
            f"recording(s): the edit is pending review — MusicBrainz keeps new "
            f"edits open for {EDIT_REVIEW_DAYS} days."
        )
        return (
            payload,
            lines,
            f"[ISRC SUBMITTED] {result.isrcs} ISRC(s) for "
            f"{result.recordings} recording(s) — pending edit",
        )

    lines.append(
        f"[ISRC {result.status.upper()}] {result.isrcs} ISRC(s) for "
        f"{result.recordings} recording(s) were not submitted: {result.reason}"
    )
    return payload, lines, f"[ISRC {result.status.upper()}] {result.reason}"
