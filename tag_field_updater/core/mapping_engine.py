"""
mapping_engine.py — Data types, constants, and value-transformation logic.

This module owns the pure data layer: result types, statistics accumulator, the
slash rule's field list, and the slash-replacement utility functions.  It has
zero knowledge of Mutagen or file I/O.

Changed in 2.2.0: ``ProcessingResult`` carries the filename parse (captured
fields, the pattern that matched, the fields left alone) and
``transform_filename_value`` routes a parsed value through the existing slash
rule for the genre field only (functional backlog F-01).

Changed in 2.4.2: ``TAG_MAPPINGS`` is gone.  It described the same three custom
genre fields and two standard ones per container, in a second copy of the keys
the tag handlers already knew, and the two copies were free to drift.  The keys
now live once, in ``audio_suite_shared.tag_field_engine.FIELD_RULES``, and this
module keeps only the tool's own statement of *which* canonical fields the slash
rule rewrites (``SLASH_FIELDS``); ``update_value`` / ``should_update_value``
delegate to that module so there is one slash rule in the suite (plan WP-6,
C-M2).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

from audio_suite_shared.tag_field_engine import (
    needs_slash_genre_split,
    split_slash_genre,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessingResult:
    """Immutable result of processing a single audio file.

    Attributes:
        file_path: Absolute path to the processed file.
        updated: True if one or more tags were rewritten.  In dry-run mode
            this reports the rewrite that *would* have been written back to
            disk — nothing is persisted, so it means "needs updating", not
            "already written".
        tags_updated: Names of tag keys that were modified.
        error: Human-readable error string if processing failed, else None.
        filename_fields: In filename mode, the field values parsed from the
            name, in the order the pattern named them.  Empty otherwise.
        filename_pattern: In filename mode, the pattern that matched, or an
            empty string when none did (the file is then a skip).
        skipped_fields: In filename mode, fields left alone because they
            already carried a value and the run only fills blanks.
    """

    file_path: Path
    updated: bool = False
    tags_updated: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None
    filename_fields: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    filename_pattern: str = ""
    skipped_fields: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class ProcessingStats:
    """Mutable accumulator for statistics across a processing run.

    Attributes:
        total_files: Audio files that matched a supported extension.
        processed_files: Files that were opened and inspected (includes errors).
        updated_files: Files where at least one tag was rewritten — files that
            *would* be rewritten when the run was a dry run.
        error_files: Files that raised an unhandled exception during processing.
        skipped_files: Files ignored due to unsupported extension or missing tags.
    """

    total_files: int = 0
    processed_files: int = 0
    updated_files: int = 0
    error_files: int = 0
    skipped_files: int = 0


# Supported audio extensions
SUPPORTED_EXTENSIONS: tuple[str, ...] = (
    ".mp3",
    ".flac",
    ".mp4",
    ".m4a",
    ".ogg",
    ".opus",
    ".wav",
    ".aiff",
    ".aif",
    ".wma",
)

#: Canonical fields the slash rule rewrites, in the order the per-format rules
#: walked them: the three suite genre fields, then the content group, then the
#: standard genre.  The per-container keys live in
#: ``audio_suite_shared.tag_field_engine``; naming a field here that the table
#: cannot place in a container fails in that table, not silently at run time.
#: ``.wma`` stays in ``SUPPORTED_EXTENSIONS`` so a scan reports the refusal the
#: format matrix gives it (``tag_writable = False``) rather than skipping the
#: file without a word.
SLASH_FIELDS: tuple[str, ...] = (
    "album_artist_genre",
    "album_genre",
    "artist_genre",
    "content_group",
    "genre",
)


#: Fields whose filename-parsed value goes through the engine's existing
#: slash rule.  Only ``genre`` is in the set: the rule exists to turn a genre
#: list (``Rock/Pop``) into the suite's ``Rock; Pop`` form.  Applying it to an
#: artist or title would rewrite ``AC/DC`` as ``AC; DC`` — a name mangled by a
#: fix for a different problem — so those fields carry the parsed text as-is.
_TRANSFORMED_FILENAME_FIELDS: frozenset[str] = frozenset({"genre"})


def transform_filename_value(field: str, value: str) -> str:
    """Apply the existing value-transformation rule to a filename-parsed value.

    Args:
        field: Canonical tag field name the value will be written to.
        value: The value parsed from the filename.

    Returns:
        The transformed value: the slash rule for the genre field, which is the
        field it was written for, and *value* unchanged for every other field.
    """
    if field in _TRANSFORMED_FILENAME_FIELDS:
        return split_slash_genre(value)
    return value


def should_update_value(value: str) -> bool:
    """Determine if a tag value contains a bare slash and requires updating.

    Args:
        value: The tag value string to inspect.

    Returns:
        True if ``value`` contains at least one ``'/'`` character.
    """
    return needs_slash_genre_split(value)


def update_value(value: str) -> str:
    """Transform a tag value by replacing bare slashes with ``'; '``.

    Segments separated by ``' / '`` (space-slash-space) are left intact;
    only bare ``'/'`` characters within each segment are replaced.

    Args:
        value: The original tag value string.

    Returns:
        The transformed string with bare ``'/'`` replaced by ``'; '``.
        Values containing no ``'/'`` are returned unchanged.
    """
    return split_slash_genre(value)
