"""
fingerprint_messages.py - part of the fingerprinter's per-file pipeline (2.4.3).

WP-9 #4 moved these functions out of
``audio_fingerprinter/core/file_processor.py`` verbatim; that module still
re-exports every name, so existing importers are unaffected.

Changed in 2.4.3: split out of
``audio_fingerprinter.core.file_processor``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import logging

from .models import (
    AcoustidRecording,
    FingerprintFileResult,
    FingerprintStatus,
    status_text,
)

logger = logging.getLogger(f"audio_suite.{__name__}")

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
