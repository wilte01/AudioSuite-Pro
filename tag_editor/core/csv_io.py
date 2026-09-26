"""csv_io.py — CSV import and export for the freeform Tag Editor."""

from __future__ import annotations

import csv
import os
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.exceptions import (
    AudioDirectoryError,
    AudioSuiteError,
    AudioTagError,
    map_to_audio_error,
)
from tag_editor.core.processor import (
    FIELD_LABELS,
    FieldEdit,
    TagRow,
    normalize_field,
    validate_field_value,
)

FILE_COLUMN = "file"
FILE_COLUMN_ALIASES = frozenset({"file", "filename", "path"})
EXPORT_FIELDNAMES: tuple[str, ...] = (FILE_COLUMN, *FIELD_LABELS)


@dataclass(frozen=True)
class CsvImportPlan:
    """Validated field edits parsed from a CSV file.

    Attributes:
        edits: One entry per non-empty CSV cell that passed validation.
        row_errors: Human-readable reasons why rows or cells were skipped.
        ignored_columns: CSV headers that are not editable tag fields.
        row_count: Number of data rows read (excluding the header).
    """

    edits: list[FieldEdit] = field(default_factory=list)
    row_errors: list[str] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)
    row_count: int = 0


def _map_columns(
    headers: Iterable[str | None],
) -> tuple[str | None, list[tuple[str, str]], list[str]]:
    """Split CSV headers into the file column, field columns, and ignored names.

    Args:
        headers: Raw header cells from the CSV reader.

    Returns:
        Tuple of the file column header (or None), ``(header, field)`` pairs
        for editable columns, and headers that are neither.
    """
    file_column: str | None = None
    columns: list[tuple[str, str]] = []
    ignored: list[str] = []
    for header in headers:
        name = header.strip() if isinstance(header, str) else ""
        if not name:
            continue
        if file_column is None and name.lower() in FILE_COLUMN_ALIASES:
            file_column = name
            continue
        try:
            field_name = normalize_field(name)
        except AudioSuiteError:
            ignored.append(name)
            continue
        columns.append((name, field_name))
    return file_column, columns, ignored


def _contained_path(name: str, root: Path) -> Path | None:
    """Resolve a CSV file value and confirm it stays inside *root*.

    Containment is checked lexically after :func:`os.path.normpath` has
    collapsed ``..`` segments, because an unnormalised ``root / "../.."``
    still reports itself as relative to *root* and would defeat a naive
    ``is_relative_to`` test. Normalising rather than :meth:`Path.resolve`
    keeps the check symmetric with :func:`_display_path`, so a file the
    exporter wrote as a relative path always re-imports, including
    libraries that reach other volumes through a symlink or junction.

    Args:
        name: Raw file value from the CSV.
        root: Normalised library directory.

    Returns:
        The contained path, or None if *name* escapes *root* or is a
        drive-relative path whose meaning depends on a per-drive working
        directory.
    """
    candidate = Path(name)
    if candidate.drive and not candidate.is_absolute():
        return None
    joined = candidate if candidate.is_absolute() else root / candidate
    try:
        resolved = Path(os.path.normpath(joined))
    except (OSError, ValueError):
        return None
    return resolved if resolved.is_relative_to(root) else None


def _read_rows(
    reader: csv.DictReader[str],
    file_column: str,
    columns: list[tuple[str, str]],
    root: Path,
) -> tuple[list[FieldEdit], list[str], int]:
    """Convert CSV data rows into validated field edits.

    Empty cells are treated as "leave unchanged" so an exported grid can be
    edited in a spreadsheet without clearing every untouched tag on re-import.

    Args:
        reader: Reader positioned at the first data row.
        file_column: Header cell naming the file column.
        columns: ``(header, field)`` pairs for editable columns.
        root: Normalised library directory; file values must resolve inside it.

    Returns:
        Tuple of validated edits, per-row error messages, and row count.
    """
    edits: list[FieldEdit] = []
    row_errors: list[str] = []
    row_count = 0
    for row in reader:
        row_count += 1
        line = row_count + 1
        raw_file = row.get(file_column)
        name = raw_file.strip() if isinstance(raw_file, str) else ""
        if not name:
            row_errors.append(f"Row {line}: missing '{file_column}' value.")
            continue
        path = _contained_path(name, root)
        if path is None:
            row_errors.append(f"Row {line}: outside the library folder: {name}")
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            row_errors.append(f"Row {line}: unsupported audio type: {name}")
            continue
        if not path.is_file():
            row_errors.append(f"Row {line}: file not found: {name}")
            continue
        for header, field_name in columns:
            value = row.get(header)
            if not isinstance(value, str) or value == "":
                continue
            try:
                validated = validate_field_value(field_name, value)
            except AudioSuiteError as exc:
                row_errors.append(f"Row {line}: {FIELD_LABELS[field_name]} — {exc}")
                continue
            if validated is not None:
                edits.append(FieldEdit(path=path, field=field_name, value=validated))
    return edits, row_errors, row_count


def build_import_plan(csv_path: str | Path, root: str | Path) -> CsvImportPlan:
    """Parse a CSV of per-file field edits into validated field edits.

    The CSV needs a file column (``file``, ``filename``, or ``path``) and one
    column per editable field, named by field key (``album_artist``) or display
    label (``Album Artist``). File values may be absolute or relative to *root*,
    but every value must resolve to a file **inside** *root*: ``..`` traversal,
    foreign absolute paths, and drive-relative values are reported as row
    errors and skipped, so a pasted spreadsheet cannot retag files elsewhere on
    the machine. The same rule governs :func:`export_csv`, so an exported CSV
    always re-imports.

    Args:
        csv_path: CSV file to read.
        root: Library directory used to resolve and confine file values.

    Returns:
        Validated :class:`CsvImportPlan` with edits and per-row diagnostics.

    Raises:
        AudioDirectoryError: If *root* is not an existing directory.
        AudioSuiteError: If the CSV is unreadable, has no file column, or has
            no editable tag columns.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        raise AudioDirectoryError(f"Not a directory: {root_path}")
    try:
        root_path = Path(os.path.normpath(root_path))
    except (OSError, ValueError):
        raise AudioDirectoryError(f"Not a directory: {root_path}") from None

    csv_file = Path(csv_path)
    try:
        with open(csv_file, newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            file_column, columns, ignored = _map_columns(reader.fieldnames or [])
            if file_column is None:
                valid = ", ".join(sorted(FILE_COLUMN_ALIASES))
                raise AudioTagError(
                    f"CSV must contain a file column ({valid}). Found: {csv_file.name}"
                )
            if not columns:
                raise AudioTagError(
                    f"CSV contains no editable tag columns: {csv_file.name}"
                )
            edits, row_errors, row_count = _read_rows(
                reader, file_column, columns, root_path
            )
    except OSError as err:
        raise map_to_audio_error(err, context={"file": str(csv_file)}) from err

    return CsvImportPlan(
        edits=edits,
        row_errors=row_errors,
        ignored_columns=ignored,
        row_count=row_count,
    )


def _display_path(path: Path, root: Path | None) -> str:
    """Render *path* relative to *root* when possible, else absolute."""
    if root is not None and _contained_path(str(path), root) is not None:
        try:
            return Path(os.path.normpath(path)).relative_to(root).as_posix()
        except ValueError:
            return str(path)
    return str(path)


def export_csv(
    rows: Iterable[TagRow],
    output_path: str | Path,
    root: str | Path | None = None,
) -> int:
    """Write the editable grid to a CSV file (one row per file).

    The layout matches the Library Stats CSV exporter: a UTF-8 file with a
    header row and one record per audio file, using an empty cell for a tag
    that is not set. Re-importing the result never clears a tag, because empty
    cells are read as "leave unchanged"; cells that do carry a value re-assert
    the tag they already hold and are reported as unchanged, not written.

    Args:
        rows: Loaded grid rows to export.
        output_path: Destination CSV path.
        root: Optional library directory; file values inside it are written as
            relative paths so the CSV stays portable.

    Returns:
        Number of data rows written (rows carrying a read error are skipped).

    Raises:
        AudioSuiteError: If the destination cannot be written.
    """
    target = Path(output_path)
    root_path: Path | None = None
    if root is not None:
        try:
            root_path = Path(os.path.normpath(Path(root)))
        except (OSError, ValueError):
            root_path = None
    written = 0
    try:
        with open(target, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(EXPORT_FIELDNAMES))
            writer.writeheader()
            for row in rows:
                if row.error is not None:
                    continue
                record: dict[str, str] = {
                    FILE_COLUMN: _display_path(row.path, root_path)
                }
                for field_name in FIELD_LABELS:
                    value = row.values.get(field_name)
                    record[field_name] = value if value is not None else ""
                writer.writerow(record)
                written += 1
    except OSError as err:
        raise map_to_audio_error(err, context={"file": str(target)}) from err
    return written
