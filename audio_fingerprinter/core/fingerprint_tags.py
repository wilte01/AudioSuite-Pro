"""
fingerprint_tags.py - part of the fingerprinter's per-file pipeline (2.4.3).

WP-9 #4 moved these functions out of
``audio_fingerprinter/core/file_processor.py`` verbatim; that module still
re-exports every name, so existing importers are unaffected.

Changed in 2.4.3: split out of
``audio_fingerprinter.core.file_processor``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import logging
from dataclasses import replace

from audio_suite_shared.batch_undo import use_batch
from audio_suite_shared.exceptions import AudioSuiteError
from audio_suite_shared.tag_handler_factory import TagHandlerFactory

from .mbid_writer import select_mbid_tags, selected_release_id, write_mbid_tags
from .models import (
    AcoustidRecording,
    FingerprintFileResult,
    FingerprintParams,
    FingerprintStatus,
    MBReleaseFacts,
)
from .musicbrainz_client import MusicBrainzClient
from .tag_writer import write_acoustid_tags, write_isrc_tags

logger = logging.getLogger(f"audio_suite.{__name__}")


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
        _, album_title = TagHandlerFactory.get_handler(file_path).read_artist_album()
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


def _write_isrc_for(isrcs: tuple[str, ...], file_path: str) -> str:
    """Write the retrieved ISRCs, returning a note for the result message.

    A failed ISRC write does not fail the file, for the same reason a failed
    MBID write does not: the AcoustID tags are already committed and only the
    enrichment is missing.  The message says which, rather than reporting a
    tagged file as untagged.

    Args:
        isrcs: ISRCs retrieved from MusicBrainz (empty writes nothing).
        file_path: Absolute path of the file being tagged.

    Returns:
        A short note for the per-file result message, empty when there was
        nothing to write.
    """
    if not isrcs:
        return ""
    ok, msg = write_isrc_tags(file_path, isrcs)
    if not ok:
        logger.warning("ISRC tag write failed for %s: %s", file_path, msg)
        return f"ISRC write failed: {msg}"
    return msg


def _release_facts_for(
    params: FingerprintParams,
    mb_client: MusicBrainzClient,
    best: AcoustidRecording,
    album_title: str,
    file_path: str,
) -> MBReleaseFacts | None:
    """Fetch release-level facts for the release this file's tags select.

    The release id comes from :func:`selected_release_id`, i.e. the same
    D2-am1 selection the tag writer uses, so the facts shown and the album id
    written can never describe different editions.

    Returns:
        The release's facts, or None when no single release is selected or the
        lookup failed (release facts are enrichment, never a requirement).
    """
    release_id = selected_release_id(
        best, album_title=album_title, file_path=file_path, region=params.mbid_region
    )
    if not release_id:
        return None
    result = mb_client.get_release(release_id)
    if not result.ok or result.value is None:
        logger.debug(
            "MusicBrainz release %s unavailable: %s", release_id, result.reason
        )
        return None
    return result.value


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
    if matched.mb is not None and matched.mb.evidence:
        message = f"{message}; {matched.mb.evidence}"
    with use_batch(undo_batch):
        ok, msg = write_acoustid_tags(
            matched.file_path, matched.fingerprint, recording.acoustid_id
        )
        if ok and params.write_mbids:
            mbids = _write_mbids_for(params, recording, matched.file_path)
            if mbids:
                message = f"{message} — {mbids}"
        if ok and params.write_isrc and matched.isrcs:
            isrc_note = _write_isrc_for(matched.isrcs, matched.file_path)
            if isrc_note:
                message = f"{message} — {isrc_note}"

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
