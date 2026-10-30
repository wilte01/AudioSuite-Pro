"""filename_tags.py — Write parsed filename fields into a file's tags (F-01).

The second half of the filename source: take the fields
:mod:`tag_field_updater.core.filename_patterns` captured and put them where the
suite's other tools will read them.  The write goes through
``audio_suite_shared``\'s editable-field API, so undo recording, per-format
frame/atom/comment mapping and the "clear with None" contract are the shared
ones rather than a second implementation.

Two rules decide which fields actually change:

* **Only fill blanks** (the default) leaves a field that already carries a
  value alone.  A parsed filename is weaker evidence than an existing tag, so
  filling gaps is the default and overwriting is the explicit choice.
* **A value identical to the stored one is not rewritten**, so re-running a
  run over an already-correct library saves nothing and reports zero updates.

A dry run computes exactly the same decisions and writes nothing: no save, no
undo record, and therefore no changed bytes.

Changed in 2.2.0: new — the writer half of functional backlog F-01.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from audio_suite_shared.tag_helper import EDITABLE_FIELDS, TagHandlerFactory
from audio_suite_shared.tag_helper_writer import write_editable_tag

from .mapping_engine import transform_filename_value

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FilenameWriteOutcome:
    """What a filename write did (or, in a dry run, would do).

    Attributes:
        updated: Whether at least one field was written — or, for a dry run,
            would be.
        written: Fields that were written, or would be, in pattern order.
        skipped_existing: Fields left alone because they already had a value
            and the run was in "only fill blanks" mode.
        unchanged: Fields whose parsed value already equalled the stored one,
            so no write was needed.
    """

    updated: bool = False
    written: tuple[str, ...] = field(default_factory=tuple)
    skipped_existing: tuple[str, ...] = field(default_factory=tuple)
    unchanged: tuple[str, ...] = field(default_factory=tuple)


def apply_filename_fields(
    file_path: Path,
    fields: Mapping[str, str],
    *,
    only_fill_blanks: bool = True,
    dry_run: bool = False,
) -> FilenameWriteOutcome:
    """Write parsed *fields* into *file_path*'s tags.

    Args:
        file_path: Audio file to tag.
        fields: Field name → value, in the order the pattern named them.
        only_fill_blanks: Leave a field alone when it already has a value.
        dry_run: Compute the same outcome without saving anything.

    Returns:
        The outcome, which the caller reports per file.

    Raises:
        ValueError: If a field is not one the tag layer can write.
        Exception: Whatever the shared tag layer raises for an unreadable or
            unwritable file; the processor maps it to a per-file error.
    """
    unknown = [name for name in fields if name not in EDITABLE_FIELDS]
    if unknown:
        raise ValueError(
            f"cannot write field(s) {', '.join(sorted(unknown))} from a filename; "
            f"expected one of {', '.join(EDITABLE_FIELDS)}"
        )

    handler = TagHandlerFactory.get_handler(str(file_path))
    stored = handler.read_editable_tags()

    written: list[str] = []
    skipped: list[str] = []
    unchanged: list[str] = []

    for name, raw_value in fields.items():
        value = transform_filename_value(name, raw_value)
        if not value.strip():
            # A whitespace-only capture is not a value: writing it would put a
            # blank-looking tag on the file that no tool can tell from a real
            # one.
            continue
        current = stored.get(name)
        if only_fill_blanks and current:
            skipped.append(name)
            continue
        if current == value:
            unchanged.append(name)
            continue

        if dry_run:
            logger.info(
                "Dry run: %s would set %s = '%s' (was %r)",
                file_path.name,
                name,
                value,
                current,
            )
        else:
            # The shared writer snapshots the file's current tags into the
            # active undo batch and saves; a snapshot per field is recorded
            # once per file per batch, so this is one undo record, not five.
            write_editable_tag(str(file_path), name, value)
            logger.info(
                "Set %s = '%s' in %s (was %r)", name, value, file_path.name, current
            )
        written.append(name)

    return FilenameWriteOutcome(
        updated=bool(written),
        written=tuple(written),
        skipped_existing=tuple(skipped),
        unchanged=tuple(unchanged),
    )
