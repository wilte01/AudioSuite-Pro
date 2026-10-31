"""The duplicate scan: fingerprinter, reporter and quarantine mover.

One entry point, :func:`run_duplicate_scan`, drives the whole run and publishes
the shared callback contract: ``on_progress`` per file, one ``on_complete`` and
``on_error`` for a fatal problem.

What a run does
---------------
1. Walk the selected directory for supported audio files, skipping the
   quarantine folder so a second run cannot re-find what the first one moved.
2. Reuse a cached fingerprint when the file's ``(mtime, size)`` stamp still
   matches; otherwise fingerprint it with fpcalc.
3. Cluster the fingerprints at the configured bit-error threshold.
4. In a **live** run, move every non-keeper into the quarantine folder and
   record the move in the undo journal.  A dry run moves nothing.

Nothing is deleted, ever, and the keeper is never opened for writing: the only
file operation a live run performs on it is a read.  That is why a live run
leaves the kept copy byte-identical, which the tests assert by hashing it.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Callable
from typing import Any

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import (
    get_active_batch_id,
    record_file_reorg_snapshot,
)
from audio_suite_shared.exceptions import map_to_audio_error, user_message_for

from .clustering import cluster_records
from .fingerprint_cache import FingerprintCache
from .fingerprinting import build_record
from .models import (
    DuplicateGroup,
    FingerprintRecord,
    ScanOutcome,
    ScanSettings,
)

logger = logging.getLogger(__name__)

#: Status tokens the per-file report uses, **bracketed** so the literal a guide
#: quotes (``[CACHED]``) is the literal the code contains: the guide-claims lock
#: searches the source text for the bracketed token, and an f-string that adds
#: the brackets itself never matches.  Interpolate the constant directly.
STATUS_CACHED = "[CACHED]"
STATUS_FINGERPRINTED = "[FINGERPRINT]"
STATUS_NO_FINGERPRINT = "[SKIP]"
STATUS_ERROR = "[ERROR]"
STATUS_KEEP = "[KEEP]"
STATUS_DUPLICATE = "[DUPLICATE]"
STATUS_MOVED = "[MOVED]"

#: Undo operation type for a batch that moved files rather than edited tags.
UNDO_OPERATION = "file_reorg"

#: Name of the folder a live run creates under the scan root by default.
QUARANTINE_DIRNAME = "duplicate_quarantine"


def discover_files(dir_path: str, quarantine_dir: str = "") -> list[str]:
    """Return every supported audio file under *dir_path*, sorted.

    Args:
        dir_path: Directory to walk.
        quarantine_dir: A directory to skip entirely.  A second run must not
            treat the first run's quarantine as part of the library.

    Returns:
        Absolute file paths, sorted, with hidden directories skipped.
    """
    skip = os.path.normcase(os.path.abspath(quarantine_dir)) if quarantine_dir else ""
    supported = {extension.lower() for extension in SUPPORTED_EXTENSIONS}
    found: list[str] = []
    for root, dirnames, filenames in os.walk(dir_path):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if not name.startswith(".")
            and os.path.normcase(os.path.abspath(os.path.join(root, name))) != skip
        )
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() in supported:
                found.append(os.path.abspath(os.path.join(root, name)))
    return found


def default_quarantine_dir(dir_path: str) -> str:
    """Return the quarantine folder a live run uses when none was chosen.

    Args:
        dir_path: The scan root.

    Returns:
        ``<scan root>/duplicate_quarantine``.
    """
    return os.path.join(os.path.abspath(dir_path), QUARANTINE_DIRNAME)


def quarantine_file(path: str, quarantine_dir: str) -> str:
    """Move *path* into *quarantine_dir*, keeping its file name unique.

    The move is recorded in the active undo batch as a ``file_reorg``, so the
    suite's undo window can put it back.  A name already present in the
    quarantine folder gains a ``" (2)"``, ``" (3)"``… suffix before the
    extension rather than being overwritten — losing one of two same-named
    duplicates is exactly the outcome this tool must not produce.

    Args:
        path: The file to move.
        quarantine_dir: Destination folder; created when missing.

    Returns:
        The destination path.

    Raises:
        OSError: If the move fails; the caller counts it as an error.
    """
    os.makedirs(quarantine_dir, exist_ok=True)
    stem, extension = os.path.splitext(os.path.basename(path))
    destination = os.path.join(quarantine_dir, stem + extension)
    counter = 2
    while os.path.exists(destination):
        destination = os.path.join(quarantine_dir, f"{stem} ({counter}){extension}")
        counter += 1
    record_file_reorg_snapshot(path, destination, "move")
    shutil.move(path, destination)
    return destination


def _fingerprint_files(
    files: list[str],
    root: str,
    cache: FingerprintCache,
    on_progress: Callable[..., None],
    outcome: ScanOutcome,
) -> list[FingerprintRecord]:
    """Return a record for every file that could be fingerprinted.

    Args:
        files: Absolute paths from :func:`discover_files`.
        root: The scan root, which is the cache's scope.
        cache: The fingerprint cache to read from and write to.
        on_progress: Per-file progress callback.
        outcome: Mutable run counters and log lines.

    Returns:
        The records, in scan order.
    """
    cached_records = cache.load_under(root)
    records: list[FingerprintRecord] = []
    processed = 0
    try:
        with cache.batch():
            for path in files:
                try:
                    stat = os.stat(path)
                except OSError as exc:
                    outcome.missing_fingerprint += 1
                    outcome.log_entries.append(f"{STATUS_ERROR} {path} | {exc}\n")
                    processed += 1
                    on_progress(
                        processed=processed,
                        total=len(files),
                        skipped=outcome.missing_fingerprint,
                        errors=0,
                        display_text=f"{STATUS_ERROR} {os.path.basename(path)}",
                    )
                    continue

                cached = cached_records.get(os.path.normpath(path))
                if cached is not None and cache.is_fresh(
                    cached, stat.st_mtime, stat.st_size
                ):
                    records.append(cached)
                    processed += 1
                    on_progress(
                        processed=processed,
                        total=len(files),
                        skipped=outcome.missing_fingerprint,
                        errors=0,
                        display_text=f"{STATUS_CACHED} {os.path.basename(path)}",
                    )
                    continue

                try:
                    record = build_record(path, stat.st_mtime, stat.st_size)
                except Exception as exc:
                    mapped = map_to_audio_error(exc)
                    reason = user_message_for(mapped)
                    outcome.missing_fingerprint += 1
                    outcome.log_entries.append(
                        f"{STATUS_NO_FINGERPRINT} {path} | {reason}\n"
                    )
                    logger.warning("No fingerprint for %s: %s", path, reason)
                    processed += 1
                    on_progress(
                        processed=processed,
                        total=len(files),
                        skipped=outcome.missing_fingerprint,
                        errors=0,
                        display_text=(
                            f"{STATUS_NO_FINGERPRINT} {os.path.basename(path)}"
                        ),
                    )
                    continue

                cache.upsert(record)
                records.append(record)
                processed += 1
                on_progress(
                    processed=processed,
                    total=len(files),
                    skipped=outcome.missing_fingerprint,
                    errors=0,
                    display_text=f"{STATUS_FINGERPRINTED} {os.path.basename(path)}",
                )
    finally:
        # Rows whose file vanished are stale by definition; the sweep is what
        # keeps a moved/deleted library from leaving fingerprints behind.
        cache.remove_orphans(root, {os.path.normpath(path) for path in files})
    return records


def _group_lines(group: DuplicateGroup) -> list[str]:
    """Return the report lines for one duplicate group.

    Args:
        group: The group to render.

    Returns:
        One keeper line followed by one line per duplicate, each naming the
        measured distance so a reviewer can see why they were grouped.
    """
    lines = [f"{STATUS_KEEP} {group.keeper.path} | {group.keeper.label}\n"]
    for member in group.duplicates:
        lines.append(
            f"{STATUS_DUPLICATE} {member.record.path} | distance "
            f"{member.distance:.4f} from keeper | {member.record.label}\n"
        )
    return lines


def run_duplicate_scan(
    dir_path: str,
    is_dry_run: bool,
    settings: ScanSettings | None = None,
    *,
    cache_path: str | None = None,
    slot_vars: list[Any] | None = None,
    slot_queue: Any = None,
    on_progress: Callable[..., None] | None = None,
    on_complete: Callable[..., None] | None = None,
    on_error: Callable[[str], None] | None = None,
) -> None:
    """Scan *dir_path* for duplicate recordings and optionally quarantine them.

    Args:
        dir_path: Directory to scan.
        is_dry_run: When True nothing is moved; the report still lists every
            duplicate the run identified.
        settings: Threshold and comparison bounds.  Defaults to
            :class:`~duplicate_finder.core.models.ScanSettings`.
        cache_path: Where the fingerprint cache lives; ``None`` uses the
            canonical ``~/.audiosuite/duplicate_cache.db``.
        slot_vars: Accepted and ignored — the shared CLI runner passes a worker
            slot pool to every ``run_*`` function, and this scan is
            single-threaded (fpcalc is already fast, and its output order is
            what makes the report reproducible).
        slot_queue: Accepted and ignored, as *slot_vars*.
        on_progress: ``(processed, total, skipped, errors, display_text)``.
        on_complete: Called once with the shared counters plus ``groups``,
            ``duplicates`` and ``quarantined``.
        on_error: Called with a user-facing message when the run cannot start.

    Raises:
        Nothing: a per-file failure is counted, and a fatal one is reported
        through *on_error*.
    """
    del slot_vars, slot_queue
    active_settings = settings or ScanSettings()
    progress = on_progress or (lambda **_kwargs: None)
    complete = on_complete or (lambda **_kwargs: None)
    error = on_error or (lambda _message: None)

    if not os.path.isdir(dir_path):
        error(f"Not a directory: {dir_path}")
        return

    quarantine_dir = active_settings.quarantine_dir or default_quarantine_dir(dir_path)
    if not is_dry_run:
        try:
            os.makedirs(quarantine_dir, exist_ok=True)
        except OSError as exc:
            error(f"Cannot create the quarantine folder: {exc}")
            return
    if os.path.normcase(os.path.abspath(quarantine_dir)) == os.path.normcase(
        os.path.abspath(dir_path)
    ):
        error("The quarantine folder cannot be the folder being scanned.")
        return

    files = discover_files(dir_path, quarantine_dir)
    if not files:
        error("No supported audio files found in the selected directory.")
        return

    started = time.monotonic()
    outcome = ScanOutcome()
    header: list[str] = [
        "DUPLICATE REPORT\n",
        f"Mode: {'DRY RUN' if is_dry_run else 'LIVE UPDATE'}\n",
        f"Directory: {os.path.abspath(dir_path)}\n",
        f"Threshold: {active_settings.threshold:.2f} bit-error rate\n",
        f"Quarantine: {quarantine_dir}\n",
        "=" * 60 + "\n",
    ]

    with FingerprintCache(cache_path) as cache:
        records = _fingerprint_files(files, dir_path, cache, progress, outcome)

    groups = cluster_records(records, active_settings)
    outcome.groups = groups
    outcome.duplicates = sum(len(group.duplicates) for group in groups)

    quarantine_errors = 0
    for group in groups:
        outcome.log_entries.extend(_group_lines(group))
        for member in group.duplicates:
            if is_dry_run:
                continue
            try:
                destination = quarantine_file(member.record.path, quarantine_dir)
            except OSError as exc:
                quarantine_errors += 1
                outcome.log_entries.append(
                    f"{STATUS_ERROR} {member.record.path} | move failed: {exc}\n"
                )
                continue
            outcome.quarantined += 1
            outcome.log_entries.append(
                f"{STATUS_MOVED} {member.record.path} -> {destination}\n"
            )

    if not groups:
        outcome.log_entries.append("No duplicate recordings found.\n")

    duration = time.monotonic() - started
    logger.info(
        "Duplicate scan: %d files, %d groups, %d duplicates, %d quarantined",
        len(files),
        len(groups),
        outcome.duplicates,
        outcome.quarantined,
    )
    complete(
        header=header,
        total=len(files),
        processed=len(files),
        skipped=outcome.missing_fingerprint,
        errors=quarantine_errors,
        duration_secs=duration,
        log_entries=outcome.log_entries,
        groups=len(groups),
        duplicates=outcome.duplicates,
        quarantined=outcome.quarantined,
    )


def current_undo_batch() -> str | None:
    """Return the active undo batch id, if a caller opened one.

    The window and the CLI wrap a live run in ``active_batch(...)`` so the
    quarantine moves are reversible.  Exposed here so both call the one
    definition.

    Returns:
        The batch id, or ``None`` outside a batch.
    """
    return get_active_batch_id()
