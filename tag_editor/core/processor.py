"""processor.py — Freeform tag scanning and field editing for the Tag Editor.

Changed in 2.2.1: the module owns the window's three shared callbacks
(``on_progress`` / ``on_complete`` / ``on_error``) through :func:`run_scan`
and :func:`run_apply`, the ``run_*`` shape every GUI tool's processor exposes
(maintenance item U5).  The window no longer reads the processor's return
values itself, so each run writes its report and drives the shared
progress/completion handlers exactly as its peers do.
"""

from __future__ import annotations

import logging
import os
import re
import string
import time
from collections.abc import Callable, Iterable, Iterator
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
from tag_field_updater.core.mapping_engine import update_value

logger = logging.getLogger(__name__)

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
BULK_OPERATION_LABELS: dict[str, str] = {
    "set_blank": "Set Blank",
    "clear_field": "Clear Field",
    "swap_fields": "Swap Fields",
    "case_convert": "Case Convert",
    "apply_txxx_rule": "Normalize Slashes (TXXX Rule)",
}
CASE_MODE_LABELS: dict[str, str] = {
    "title": "Title Case",
    "upper": "Upper Case",
    "lower": "Lower Case",
}
_TEXT_RULE_FIELDS = frozenset(
    {"title", "artist", "album", "album_artist", "genre", "comment"}
)
_TRACK_PATTERN = re.compile(r"([1-9][0-9]{0,3})(?:/([1-9][0-9]{0,3}))?")
_YEAR_PATTERN = re.compile(r"([12][0-9]{3})(?:-[0-9]{2}-[0-9]{2})?")


@dataclass(frozen=True)
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


def normalize_bulk_operation(operation: str) -> str:
    """Return the canonical bulk operation name.

    Args:
        operation: User- or caller-supplied operation name or label.

    Returns:
        Canonical bulk operation key.

    Raises:
        AudioSuiteError: If the operation is not supported.
    """
    display = operation.strip().lower()
    canonical_by_label = {
        label.lower(): key for key, label in BULK_OPERATION_LABELS.items()
    }
    canonical = canonical_by_label.get(display, display.replace(" ", "_"))
    if canonical not in BULK_OPERATION_LABELS:
        valid = ", ".join(BULK_OPERATION_LABELS)
        raise AudioTagError(
            f"Unsupported bulk operation: {operation}. Valid operations: {valid}"
        )
    return canonical


def normalize_case_mode(mode: str) -> str:
    """Return the canonical case-conversion mode.

    Args:
        mode: User- or caller-supplied mode name or label.

    Returns:
        Canonical case mode key.

    Raises:
        AudioSuiteError: If the mode is not supported.
    """
    display = mode.strip().lower()
    canonical_by_label = {label.lower(): key for key, label in CASE_MODE_LABELS.items()}
    canonical = canonical_by_label.get(display, display.replace(" ", "_"))
    if canonical not in CASE_MODE_LABELS:
        valid = ", ".join(CASE_MODE_LABELS)
        raise AudioTagError(f"Unsupported case mode: {mode}. Valid modes: {valid}")
    return canonical


def _convert_case(value: str, mode: str) -> str:
    """Convert *value* using the canonical case *mode*."""
    if mode == "upper":
        return value.upper()
    if mode == "lower":
        return value.lower()
    return string.capwords(value)


def build_bulk_edits(
    rows: Iterable[TagRow],
    operation: str,
    field: str,
    *,
    second_field: str | None = None,
    case_mode: str = "title",
) -> list[FieldEdit]:
    """Build validated field edits for a bulk operation.

    Args:
        rows: Loaded file rows containing current editable values.
        operation: Bulk operation name or display label.
        field: Primary editable field.
        second_field: Secondary field for swap operations.
        case_mode: Case mode used by case-conversion operations.

    Returns:
        Field edits in file order; rows that would not change are omitted.

    Raises:
        AudioSuiteError: If the operation, fields, or case mode are invalid.
    """
    bulk_operation = normalize_bulk_operation(operation)
    primary = normalize_field(field)
    secondary = normalize_field(second_field) if second_field else None
    mode = normalize_case_mode(case_mode)

    if bulk_operation == "swap_fields":
        if secondary is None:
            raise AudioTagError("Swap Fields requires a second field.")
        if secondary == primary:
            raise AudioTagError("Swap Fields requires two different fields.")
    elif bulk_operation == "apply_txxx_rule" and primary not in _TEXT_RULE_FIELDS:
        raise AudioTagError(
            "Normalize Slashes is available for text fields, not track or year."
        )

    edits: list[FieldEdit] = []
    for row in rows:
        if row.error is not None:
            continue
        current = row.values.get(primary)
        if bulk_operation == "set_blank":
            edits.append(FieldEdit(row.path, primary, ""))
        elif bulk_operation == "clear_field":
            edits.append(FieldEdit(row.path, primary, None))
        elif bulk_operation == "swap_fields" and secondary is not None:
            other = row.values.get(secondary)
            if current != other:
                edits.append(FieldEdit(row.path, primary, other))
                edits.append(FieldEdit(row.path, secondary, current))
        elif bulk_operation == "case_convert":
            if current:
                converted = _convert_case(current, mode)
                if converted != current:
                    edits.append(FieldEdit(row.path, primary, converted))
        elif bulk_operation == "apply_txxx_rule":
            if current is not None:
                normalized_value = update_value(current)
                if normalized_value != current:
                    edits.append(FieldEdit(row.path, primary, normalized_value))
    return edits


class TagEditorProcessor:
    """Scans supported audio files and applies validated field edits."""

    def __init__(self) -> None:
        """Create a processor whose scan can be stopped by the window."""
        self._stop_requested = False

    def stop(self) -> None:
        """Signal the current scan to stop after the file it is reading."""
        self._stop_requested = True

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
        notify: Callable[[Path, TagRow | None, int], None] | None = None
        if progress_callback is not None:
            report = progress_callback

            def _notify(path: Path, _row: TagRow | None, loaded: int) -> None:
                report(path.name, loaded)

            notify = _notify

        return self._scan(directory, on_progress=notify)

    def _scan(
        self,
        directory: str | Path,
        *,
        on_progress: Callable[[Path, TagRow | None, int], None] | None = None,
    ) -> list[TagRow]:
        """Walk *directory* and load one row per supported audio file.

        The single walk behind both :meth:`scan_directory` (whose callback
        reports only a filename and a count) and :func:`run_scan` (which also
        needs the unsupported files, so it can report them as skipped): the
        callback receives ``None`` for a file it walked past.

        Args:
            directory: Root directory to scan.
            on_progress: Called for every file visited, with the row it
                produced (``None`` when the extension is unsupported) and the
                number of audio rows loaded so far.

        Returns:
            One :class:`TagRow` per supported audio file, including rows whose
            tags could not be read (``error`` is set on those rows).  A stopped
            scan returns the rows it loaded before the stop was seen.

        Raises:
            AudioDirectoryError: If *directory* is not an existing directory.
        """
        root = Path(directory)
        if not root.is_dir():
            raise AudioDirectoryError(f"Not a directory: {root}")

        self._stop_requested = False
        rows: list[TagRow] = []
        for path in _visited_files(root):
            if self._stop_requested:
                logger.info("Scan stopped by user after %d file(s)", len(rows))
                break
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                if on_progress is not None:
                    on_progress(path, None, len(rows))
                continue
            row = self._load_row(path)
            rows.append(row)
            if on_progress is not None:
                on_progress(path, row, len(rows))
        return rows

    @staticmethod
    def _load_row(path: Path) -> TagRow:
        """Read one file's editable tags, mapping a failure onto the row.

        Args:
            path: Audio file to read.

        Returns:
            A :class:`TagRow`; ``error`` is set when the tags could not be read.
        """
        try:
            values = read_editable_tags(str(path))
            return TagRow(path=path, values=values)
        except AudioSuiteError as exc:
            return TagRow(path=path, values={}, error=user_message_for(exc))
        except Exception as exc:
            mapped = map_to_audio_error(exc, context={"file": str(path)})
            return TagRow(path=path, values={}, error=user_message_for(mapped))

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

    def apply_bulk(
        self,
        rows: Iterable[TagRow],
        operation: str,
        field: str,
        *,
        second_field: str | None = None,
        case_mode: str = "title",
        dry_run: bool = False,
    ) -> list[EditResult]:
        """Apply a bulk operation under one undo batch.

        Args:
            rows: Loaded file rows containing current editable values.
            operation: Bulk operation name or display label.
            field: Primary editable field.
            second_field: Secondary field for swap operations.
            case_mode: Case mode used by case-conversion operations.
            dry_run: When True, report planned changes without writing.

        Returns:
            Edit results for every field edit generated by the operation.
        """
        edits = build_bulk_edits(
            rows,
            operation,
            field,
            second_field=second_field,
            case_mode=case_mode,
        )
        return self.apply_edits(edits, dry_run=dry_run)

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


# ── Report lines ────────────────────────────────────────────────────────────


def _value_text(value: str | None) -> str:
    """Render a tag value for a report line.

    Args:
        value: Stored value, ``None`` for a removed field, ``""`` for a blank.

    Returns:
        A readable token: quoted text, ``(cleared)`` or ``(blank)``.
    """
    if value is None:
        return "(cleared)"
    if value == "":
        return "(blank)"
    return repr(value)


def scan_log_line(row: TagRow) -> str:
    """Return one report line for a file the load walk visited.

    Args:
        row: The row the walk produced for the file.

    Returns:
        An ``[ERROR]`` line for an unreadable file, otherwise a ``[READ]`` line
        naming the fields that are set.
    """
    if row.error is not None:
        return f"[ERROR]     {row.path.name}: {row.error}\n"
    set_fields = [
        f"{field}={_value_text(value)}" for field, value in row.values.items() if value
    ]
    detail = "; ".join(set_fields) if set_fields else "no editable tags set"
    return f"[READ]      {row.path.name} ({detail})\n"


def apply_log_line(result: EditResult, *, is_dry_run: bool) -> str:
    """Return one report line for a field edit an apply run attempted.

    Args:
        result: The outcome of one requested edit.
        is_dry_run: Whether the run was allowed to write.

    Returns:
        A ``[FAILED]``, ``[UNCHANGED]``, ``[WOULD WRITE]`` or ``[WRITTEN]``
        line describing old and new values.
    """
    if result.error is not None:
        return (
            f"[FAILED]    {result.path.name}: {result.field} -> "
            f"{_value_text(result.new_value)} ({result.error})\n"
        )
    if not result.changed:
        return (
            f"[UNCHANGED] {result.path.name}: {result.field} is already "
            f"{_value_text(result.old_value)}\n"
        )
    verb = "WOULD WRITE" if is_dry_run else "WRITTEN"
    return (
        f"[{verb}] {result.path.name}: {result.field} "
        f"{_value_text(result.old_value)} -> {_value_text(result.new_value)}\n"
    )


# ── Run entry points (the GUI's three callbacks) ────────────────────────────


def _visited_files(root: Path) -> Iterator[Path]:
    """Yield every file under *root*, sorted, in a stable recursion order.

    Args:
        root: Directory to walk.

    Yields:
        Each file path, with directory names and file names sorted so two runs
        over the same tree report the same order.
    """
    for current_root, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for filename in sorted(filenames):
            yield Path(current_root) / filename


def count_visited_files(directory: str | Path) -> int:
    """Count every file a load walk will visit, supported or not.

    The progress bar's denominator is the unit the walk counts (files
    visited), so an unsupported file is visible as a skip rather than absent.

    Args:
        directory: Root directory to count.

    Returns:
        The number of files under *directory*.
    """
    return sum(1 for _ in _visited_files(Path(directory)))


def run_scan(
    directory: str,
    *,
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
    processor: TagEditorProcessor | None = None,
) -> None:
    """Load *directory* into the grid, driving the shared GUI callbacks.

    This is the tool's load ``run_*`` entry point (AGENTS.md "GUI Callback
    Contract"): the processor owns the three payloads and the window's handlers
    mirror them.

    Args:
        directory: Root directory to walk.
        on_progress: Called after each file with ``processed``, ``total``,
            ``skipped``, ``errors`` and ``display_text``.
        on_complete: Called once at the end with ``total``, ``processed``,
            ``skipped``, ``errors``, ``duration_secs``, ``log_entries`` and
            ``rows`` (the loaded grid rows).
        on_error: Called with one user-facing message if the walk itself
            fails; per-file read failures are rows, not fatals.
        processor: The instance to scan with, so the window that shows a Stop
            button can signal the run it started.  A fresh processor is built
            when omitted.
    """
    engine = processor if processor is not None else TagEditorProcessor()
    total = count_visited_files(directory)
    started = time.monotonic()
    counts = {"processed": 0, "skipped": 0, "errors": 0}

    def _progress(path: Path, row: TagRow | None, _loaded: int) -> None:
        """Adapt the walk's per-file ping to the shared payload."""
        counts["processed"] += 1
        if row is None:
            counts["skipped"] += 1
            text = f"{path.name} (unsupported format)"
        elif row.error is not None:
            counts["errors"] += 1
            text = f"{path.name} (unreadable tags)"
        else:
            text = path.name
        on_progress(
            processed=counts["processed"],
            total=total,
            skipped=counts["skipped"],
            errors=counts["errors"],
            display_text=text,
        )

    try:
        rows = engine._scan(directory, on_progress=_progress)
    except Exception as exc:  # noqa: BLE001 - the UI reports, never raises
        mapped = map_to_audio_error(exc, context={"directory": directory})
        logger.error(
            "[%s] Scan failed for %s: %s",
            type(mapped).__name__,
            directory,
            mapped,
            exc_info=True,
        )
        on_error(user_message_for(mapped))
        return

    on_complete(
        total=total,
        processed=counts["processed"],
        skipped=counts["skipped"],
        errors=counts["errors"],
        duration_secs=time.monotonic() - started,
        log_entries=[scan_log_line(row) for row in rows],
        rows=rows,
    )


def run_apply(
    edits: Iterable[FieldEdit],
    *,
    is_dry_run: bool,
    on_progress: Callable[..., None],
    on_complete: Callable[..., None],
    on_error: Callable[[str], None],
    processor: TagEditorProcessor | None = None,
) -> None:
    """Apply one batch of field edits, driving the shared GUI callbacks.

    The whole batch goes through one :meth:`TagEditorProcessor.apply_edits`
    call, so it is one undo batch; the counts are reported per *file* (the unit
    the shared summary and progress bar use), while the report carries one line
    per edit.

    Args:
        edits: Requested field edits, in apply order.
        is_dry_run: Whether the run may write; a dry run reports the comparison
            only and creates no undo record.
        on_progress: Called once per file with ``processed``, ``total``,
            ``skipped`` (files with nothing to change), ``errors`` and
            ``display_text``.
        on_complete: Called once at the end with ``total``, ``processed``,
            ``skipped``, ``errors``, ``duration_secs``, ``log_entries``,
            ``results`` (one :class:`EditResult` per edit), ``changed`` and
            ``written``.
        on_error: Called with one user-facing message if the batch cannot be
            validated or applied; per-file failures are counted instead.
        processor: The instance to apply with.  A fresh processor is built when
            omitted.
    """
    engine = processor if processor is not None else TagEditorProcessor()
    batch = list(edits)
    started = time.monotonic()

    try:
        results = engine.apply_edits(batch, dry_run=is_dry_run)
    except Exception as exc:  # noqa: BLE001 - the UI reports, never raises
        mapped = map_to_audio_error(exc, context={"edits": len(batch)})
        logger.error(
            "[%s] Apply run failed after %d edit(s): %s",
            type(mapped).__name__,
            len(batch),
            mapped,
            exc_info=True,
        )
        on_error(user_message_for(mapped))
        return

    by_file: dict[Path, list[EditResult]] = {}
    for result in results:
        by_file.setdefault(result.path, []).append(result)

    total = len(by_file)
    processed = skipped = errors = 0
    for path, file_results in by_file.items():
        processed += 1
        if any(result.error is not None for result in file_results):
            errors += 1
        elif not any(result.changed for result in file_results):
            skipped += 1
        on_progress(
            processed=processed,
            total=total,
            skipped=skipped,
            errors=errors,
            display_text=_progress_text(path, file_results, is_dry_run=is_dry_run),
        )

    on_complete(
        total=total,
        processed=processed,
        skipped=skipped,
        errors=errors,
        duration_secs=time.monotonic() - started,
        log_entries=[
            apply_log_line(result, is_dry_run=is_dry_run) for result in results
        ],
        results=results,
        changed=sum(
            1 for file_results in by_file.values() if _file_changed(file_results)
        ),
        written=sum(1 for result in results if result.written),
    )


def _file_changed(results: list[EditResult]) -> bool:
    """Return whether any edit in one file's results changed a value."""
    return any(result.changed for result in results)


def _progress_text(path: Path, results: list[EditResult], *, is_dry_run: bool) -> str:
    """Return the Processing-tab line for one file's edits.

    Args:
        path: The file the results belong to.
        results: That file's edit outcomes.
        is_dry_run: Whether the run may write.

    Returns:
        A single line naming the first change and how many others followed.
    """
    failed = [result for result in results if result.error is not None]
    if failed:
        return f"{path.name}: {len(failed)} edit(s) failed"
    changes = [result for result in results if result.changed]
    if not changes:
        return f"{path.name}: unchanged"
    first = changes[0]
    verb = "would write" if is_dry_run else "wrote"
    extra = f" (+{len(changes) - 1} more)" if len(changes) > 1 else ""
    return f"{path.name}: {verb} {first.field} -> {_value_text(first.new_value)}{extra}"
