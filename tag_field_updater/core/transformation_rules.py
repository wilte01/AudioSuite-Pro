"""
transformation_rules.py — the slash rule, applied through the shared field engine.

This module used to hold eight near-identical ``process_*_file`` functions, one
per container family, each opening its own mutagen object, walking its own key
list and calling ``save()`` itself.  They were the second copy of the mapping
``audio_suite_shared.tag_field_engine`` now owns: five formats × five keys,
written out by hand, plus the WAV/AIFF and DSF duplicates of the MP3 rule.
:func:`process_file` replaces all eight.  The engine resolves the container keys
and performs the write; this module keeps only what belongs to *this tool* —
which canonical fields the slash rule touches, and what a skip or a failure is
reported as.

A file is a skip when it has no ID3 tag container at all (the old
``_SkipFile("no ID3 tags found")`` path) and an unchanged file when its
container exists but carries none of the five fields, or carries them without a
bare slash.  Both outcomes are the ones the per-format rules reported, so a
scan's counts do not move.

Every write is gated on ``dry_run`` at the write site (the engine), and the undo
snapshot is recorded by the engine once per file: a dry run persists nothing and
records nothing, so its bytes and mtime are untouched.

Changed in 2.4.2: the eight rules become one engine-driven rule; the mutagen
imports and per-format branches are gone (plan WP-6, C-M2).
"""

import logging
from pathlib import Path

from audio_suite_shared.exceptions import map_to_audio_error, user_message_for
from audio_suite_shared.tag_field_engine import (
    ID3,
    TagFieldEngine,
    needs_slash_genre_split,
)

from .mapping_engine import SLASH_FIELDS, ProcessingResult

logger = logging.getLogger(__name__)


class _SkipFile(Exception):
    """Internal signal: file should be counted as skipped upstream.

    Raised for conditions such as "no ID3 tags found".  The calling delegate
    catches this to increment ``skipped_files`` and return an empty result.
    """

    def __init__(self, reason: str = "") -> None:
        """Store the human-readable reason the file was skipped.

        Args:
            reason: Short phrase appended to the "Skipped <file>: " log line.
        """
        self.reason = reason
        super().__init__(reason)


def process_file(file_path: Path, dry_run: bool = False) -> ProcessingResult:
    """Rewrite bare slashes in this file's genre-style tags.

    Args:
        file_path: Path to the audio file.
        dry_run: When True, compute the rewrite and report it, but neither
            snapshot the undo log nor save the file.

    Returns:
        A :class:`ProcessingResult` naming the container keys that were
        rewritten, or that would be.

    Raises:
        _SkipFile: When an ID3-backed file carries no tag container, which the
            processor counts as a skip rather than an error.
    """
    result = ProcessingResult(file_path=file_path)

    try:
        engine = TagFieldEngine(file_path)
        if engine.convention == ID3 and not engine.has_tags():
            raise _SkipFile("no ID3 tags found")

        stored = engine.read_fields()
        pending: dict[str, str] = {}
        for name in SLASH_FIELDS:
            value = stored.get(name)
            if isinstance(value, str) and needs_slash_genre_split(value):
                # The engine applies the rule's own transform, so the raw
                # stored value is what it needs: passing an already-transformed
                # one would make the rule depend on the caller remembering it.
                pending[name] = value

        if not pending:
            logger.info("Skipped %s: no target tags found to update", file_path.name)
            return result

        write = engine.write_fields(pending, dry_run=dry_run)
        if not write.updated:
            logger.info("Skipped %s: no target tags found to update", file_path.name)
            return result

        result = ProcessingResult(
            file_path=file_path,
            updated=True,
            tags_updated=write.keys or write.changed,
        )

    except _SkipFile:
        raise
    except Exception as exc:
        mapped = map_to_audio_error(
            exc,
            context={
                "file": str(file_path),
                "format": file_path.suffix.lower().lstrip("."),
            },
        )
        logger.error(
            "[%s] Tag processing error for %s: %s",
            type(mapped).__name__,
            file_path.name,
            mapped,
            exc_info=True,
        )
        result = ProcessingResult(file_path=file_path, error=user_message_for(mapped))

    return result
