"""Tool-level AcoustID tag writing.

Thin delegation to ``audio_suite_shared.tag_helper_writer.write_acoustid`` so
the tool core stays importable on minimal installs (mutagen is imported only
inside the shared helper) and errors are already normalised to an
``AudioTagError`` in the shared layer.
"""

from __future__ import annotations

import logging

from audio_suite_shared.exceptions import (
    AudioSuiteError,
    handle_audio_errors,
)
from audio_suite_shared.tag_helper_writer import write_acoustid as _write_acoustid

logger = logging.getLogger(__name__)


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
