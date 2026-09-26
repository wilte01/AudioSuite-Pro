"""processor.py — Freeform tag scanning and field editing for the Tag Editor."""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from pathlib import Path

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import active_batch
from audio_suite_shared.exceptions import (
    AudioDirectoryError,
    AudioSuiteError,
    AudioTagError,
    map_to_audio_error,
    user_message_for,
)
from audio_suite_shared.security.input_validator import InputValidator
from audio_suite_shared.tag_helper import (
    EDITABLE_FIELDS,
    read_editable_tags,
    write_editable_tag,
)

TOOL_NAME = "tag_editor"
MAX_TAG_VALUE_LENGTH = 4096
FIELD_LABELS: dict[str, str] = {
    "title": "Title",
    "artist": "Artist",
    "album": "Album",
    "album_artist": "Album Artist",
    "track": "Track",
    "year": "Year",
    "genre": "Genre",
    "comment": "Comment",
}
_TRACK_PATTERN = re.compile(r"([1-9][0-9]{0,3})(?:/([1-9][0-9]{0,3}))?")
_YEAR_PATTERN = re.compile(r"([12][0-9]{3})(?:-[0-9]{2}-[0-9]{2})?")


@dataclass
class TagRow:
    """One loaded audio file and its editable tag values."""

    path: Path
    values: dict[str, str | None]
    error: str | None = None


@dataclass(frozen=True)
class FieldEdit:
    """A requested write to one editable field of one audio file."""

    path: Path
    field: str
    value: str | None


@dataclass
class EditResult:
    """Outcome of applying one :class:`FieldEdit`."""

    path: Path
    field: str
    old_value: str | None
    new_value: str | None
    changed: bool
    written: bool
    error: str | None = None


@dataclass(frozen=True)
class EditStats:
    """Aggregate outcome of one Tag Editor apply run."""

    total: int = 0
    changed: int = 0
    unchanged: int = 0
    written: int = 0
    errors: int = 0


def normalize_field(field: str) -> str:
    """Return the canonical editable field name for *field*.

    Args:
        field: User- or caller-supplied field name.

    Returns:
        Canonical field name from ``EDITABLE_FIELDS``.

    Raises:
        AudioSuiteError: If the field is not editable.
    """
    display = field.strip().lower()
    canonical_by_label = {label.lower(): key for key, label in FIELD_LABELS.items()}
    canonical = canonical_by_label.get(display, display.replace(" ", "_"))
    if canonical not in EDITABLE_FIELDS:
        valid = ", ".join(EDITABLE_FIELDS)
        raise AudioTagError(f"Unsupported tag field: {field}. Valid fields: {valid}")
    return canonical


def validate_field_value(field: str, value: str | None) -> str | None:
    """Validate a field value without altering its content.

    Args:
        field: Canonical editable field name.
        value: String value to store, or ``None`` to clear the field.

    Returns:
        The validated value unchanged.

    Raises:
        AudioSuiteError: If the value is invalid for the field.
    """
    if value is None:
        return None
    if not InputValidator.validate_tag_value(value, MAX_TAG_VALUE_LENGTH):
        raise AudioTagError(
            "Tag values may contain at most 4096 characters and no control "
            "characters other than tab, newline, and carriage return."
        )
    if field == "track":
        if value == "":
            return value
        match = _TRACK_PATTERN.fullmatch(value)
        if match is None:
            raise AudioTagError("Track must be 'N' or 'N/M' using numbers 1-9999.")
        track = int(match.group(1))
        total = int(match.group(2)) if match.group(2) is not None else None
        if total is not None and total < track:
            raise AudioTagError("Track total must be greater than or equal to track.")
    elif field == "year":
        if value == "":
            return value
        if _YEAR_PATTERN.fullmatch(value) is None:
            raise AudioTagError("Year must be a four-digit year or ISO date.")
    return value


def summarize_results(results: Iterable[EditResult]) -> EditStats:
    """Summarise a sequence of edit results.

    Args:
        results: Edit results produced by :meth:`TagEditorProcessor.apply_edits`.

    Returns:
        Aggregate :class:`EditStats`.
    """
    total = changed = unchanged = written = errors = 0
    for result in results:
        total += 1
        if result.error is not None:
            errors += 1
        elif result.changed:
            changed += 1
            if result.written:
                written += 1
        else:
            unchanged += 1
    return EditStats(
        total=total,
        changed=changed,
        unchanged=unchanged,
        written=written,
        errors=errors,
    )


class TagEditorProcessor:
    """Scans supported audio files and applies validated field edits."""

    def scan_directory(
        self,
        directory: str | Path,
        progress_callback: Callable[[str, int], None] | None = None,
    ) -> list[TagRow]:
        """Recursively load editable tag fields for supported audio files.

        Args:
            directory: Root directory to scan.
            progress_callback: Optional callback receiving each filename and
                the number of rows loaded so far.

        Returns:
            One :class:`TagRow` per supported audio file, including rows
            whose tags could not be read (``error`` is set on those rows).

        Raises:
            AudioDirectoryError: If *directory* is not an existing directory.
        """
        root = Path(directory)
        if not root.is_dir():
            raise AudioDirectoryError(f"Not a directory: {root}")

        rows: list[TagRow] = []
        for current_root, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for filename in sorted(filenames):
                path = Path(current_root) / filename
                if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                    continue
                try:
                    values = read_editable_tags(str(path))
                    rows.append(TagRow(path=path, values=values))
                except AudioSuiteError as exc:
                    rows.append(
                        TagRow(path=path, values={}, error=user_message_for(exc))
                    )
                except Exception as exc:
                    mapped = map_to_audio_error(exc, context={"file": str(path)})
                    rows.append(
                        TagRow(path=path, values={}, error=user_message_for(mapped))
                    )
                if progress_callback is not None:
                    progress_callback(filename, len(rows))
        return rows

    def refresh_file(self, path: Path) -> TagRow:
        """Reload one file's editable values after a write.

        Args:
            path: Audio file path.

        Returns:
            Fresh :class:`TagRow` for the file.

        Raises:
            AudioSuiteError: If the file cannot be read.
        """
        values = read_editable_tags(str(path))
        return TagRow(path=path, values=values)

    def apply_edits(
        self,
        edits: Iterable[FieldEdit],
        *,
        dry_run: bool = False,
    ) -> list[EditResult]:
        """Apply one batch of field edits under a single undo batch.

        Values are validated before any file is written. Dry runs stop after
        the planned old/new comparison and never call the tag writer.

        Args:
            edits: Requested field edits.
            dry_run: When True, report planned changes without writing.

        Returns:
            One :class:`EditResult` per requested edit, in input order.
        """
        normalized: list[FieldEdit] = []
        for edit in edits:
            field = normalize_field(edit.field)
            value = validate_field_value(field, edit.value)
            normalized.append(replace(edit, field=field, value=value))

        results: list[EditResult] = []
        pending_writes: list[tuple[FieldEdit, EditResult]] = []
        for edit in normalized:
            try:
                old_values = read_editable_tags(str(edit.path))
                old_value = old_values.get(edit.field)
                changed = old_value != edit.value
                result = EditResult(
                    path=edit.path,
                    field=edit.field,
                    old_value=old_value,
                    new_value=edit.value,
                    changed=changed,
                    written=False,
                )
                if changed and not dry_run:
                    pending_writes.append((edit, result))
            except AudioSuiteError as exc:
                result = EditResult(
                    path=edit.path,
                    field=edit.field,
                    old_value=None,
                    new_value=edit.value,
                    changed=False,
                    written=False,
                    error=user_message_for(exc),
                )
            except Exception as exc:
                mapped = map_to_audio_error(exc, context={"file": str(edit.path)})
                result = EditResult(
                    path=edit.path,
                    field=edit.field,
                    old_value=None,
                    new_value=edit.value,
                    changed=False,
                    written=False,
                    error=user_message_for(mapped),
                )
            results.append(result)

        if pending_writes:
            with active_batch(TOOL_NAME, "tag_edit"):
                for edit, result in pending_writes:
                    try:
                        write_editable_tag(str(edit.path), edit.field, edit.value)
                        result.written = True
                    except AudioSuiteError as exc:
                        result.error = user_message_for(exc)
                    except Exception as exc:
                        mapped = map_to_audio_error(
                            exc, context={"file": str(edit.path)}
                        )
                        result.error = user_message_for(mapped)
        return results
