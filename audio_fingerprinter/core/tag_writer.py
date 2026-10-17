"""Tool-level AcoustID and ISRC tag writing.

Thin delegation to ``audio_suite_shared.tag_helper_writer`` so the tool core
stays importable on minimal installs (mutagen is imported only inside the
shared helper) and errors are already normalised to an ``AudioTagError`` in the
shared layer.

Changed in 1.2.0: adds ``write_isrc_tags`` for the MusicBrainz ISRC retrieval
(PLAN_feature_expansion.md D29).
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from audio_suite_shared.exceptions import (
    AudioSuiteError,
    handle_audio_errors,
)
from audio_suite_shared.tag_helper_writer import write_acoustid as _write_acoustid
from audio_suite_shared.tag_helper_writer import write_isrc as _write_isrc

logger = logging.getLogger(__name__)


@handle_audio_errors(reraise=False, context="isrc_tag_write")
def write_isrc_tags(
    file_path: str,
    isrcs: Sequence[str],
) -> tuple[bool, str]:
    """Write the retrieved ISRCs to a file, returning a success flag.

    Args:
        file_path: Path to the audio file.
        isrcs: ISRCs retrieved from MusicBrainz.

    Returns:
        A ``(ok, message)`` tuple, mirroring :func:`write_acoustid_tags`: the
        message carries the written count on success and the error text on
        failure, so the per-file result can name what happened either way.
    """
    try:
        _write_isrc(file_path, isrcs)
    except AudioSuiteError as exc:
        logger.warning("ISRC tag write failed for %s: %s", file_path, exc)
        return False, str(exc)
    return True, f"ISRC tags written: {len(list(isrcs))}."


@handle_audio_errors(reraise=False, context="acoustid_tag_write")
def write_acoustid_tags(
    file_path: str,
    fingerprint: str,
    acoustid_id: str,
) -> tuple[bool, str]:
    """Write the AcoustID tags to a file, returning a success flag.

    Args:
        file_path: Path to the audio file.
        fingerprint: Chromaprint fingerprint string.
        acoustid_id: AcoustID match id.

    Returns:
        A ``(ok, message)`` tuple.  ``ok`` is False when the write fails
        (mutagen missing, unsupported container, read-only file); the
        message then carries the error text.
    """
    try:
        _write_acoustid(file_path, fingerprint, acoustid_id)
    except AudioSuiteError as exc:
        # The shared layer maps every audio failure to an AudioSuiteError
        # subclass — not always the AudioTagError subclass this used to
        # catch. A mapped base error then escaped to the decorator, which
        # returned None and broke the (ok, message) contract at the call
        # site. Catching the base keeps the tuple contract for every
        # failure the audio layer can report.
        logger.warning("AcoustID tag write failed for %s: %s", file_path, exc)
        return False, str(exc)
    return True, "AcoustID tags written."


__all__ = ["write_acoustid_tags", "write_isrc_tags"]
