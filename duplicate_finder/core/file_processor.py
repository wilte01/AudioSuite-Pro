# Changed in 2.6.0: exact-duplicate mode (F-E9) — hashed grouping beside the
# fingerprint grouping, and a report that labels which question grouped a set.
# Changed in 2.6.0: an exact member is labelled from its own digest against the
# keeper, so a byte copy beside a retagged one keeps its stronger claim (D-22).
# Changed in 2.4.0: duplicate dispositions and ASX stubs.
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

   ``ScanSettings.exact_mode`` adds the narrower question: ``only`` skips
   fingerprinting entirely and groups files whose bytes (or decoded samples)
   are identical, ``also`` does both in one pass and reports the two kinds
   separately.  The report labels a byte-identical set ``[EXACT]`` and a set
   that only matches after decoding ``[EXACT PCM]``, so a reader can see which
   claim was made.
4. In a **live** run, apply the configured disposition to every non-keeper:
   move it into the quarantine folder and record the move (the default), move
   it to the operating system's Recycle Bin, or write a verified ASX stub
   beside it and then move it to the Recycle Bin.  A dry run applies nothing.

The keeper is never opened for writing: the only file operation a live run
performs on it is a read.  That is why a live run leaves the kept copy
byte-identical, which the tests assert by hashing it.  Delete and ASX-stub
never call ``unlink`` on audio; their only removal path is the Trash seam.

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import logging
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audio_suite_shared.asx_stub import (
    read_stub,
    snapshot_tags,
    stub_path_for,
    with_keeper,
    write_stub,
)
from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS
from audio_suite_shared.batch_undo import (
    get_active_batch_id,
    record_file_reorg_snapshot,
)
from audio_suite_shared.exceptions import map_to_audio_error, user_message_for

from .clustering import choose_keeper, cluster_records
from .disposition import Disposition, label_for, uses_trash
from .exact import KIND_BYTES, KIND_PCM, attach_hashes, build_exact_groups
from .fingerprint_cache import FingerprintCache
from .fingerprint_distance import bit_error_rate
from .fingerprinting import build_properties_record, build_record
from .models import (
    DuplicateGroup,
    DuplicateMember,
    FingerprintRecord,
    ScanOutcome,
    ScanSettings,
)
from .trash import TrashUnavailableError, move_to_trash
from .trash import available as trash_available
from .trash import ensure_available as ensure_trash_available

logger = logging.getLogger(__name__)

#: Status tokens the per-file report uses, **bracketed** so the literal a guide
#: quotes (``[CACHED]``) is the literal the code contains: the guide-claims lock
#: searches the source text for the bracketed token, and an f-string that adds
#: the brackets itself never matches.  Interpolate the constant directly.
STATUS_CACHED = "[CACHED]"
STATUS_FINGERPRINTED = "[FINGERPRINT]"
STATUS_EXACT = "[EXACT]"
STATUS_EXACT_PCM = "[EXACT PCM]"
STATUS_NO_FINGERPRINT = "[SKIP]"
STATUS_ERROR = "[ERROR]"
STATUS_KEEP = "[KEEP]"
STATUS_DUPLICATE = "[DUPLICATE]"
STATUS_MOVED = "[MOVED]"
STATUS_DELETED = "[DELETED]"
STATUS_STUBBED = "[STUBBED]"

#: How the report names each exact-matching choice, once, so the header and the
#: guide read the same words.
EXACT_MODE_LABELS: dict[str, str] = {
    "off": "Off (fingerprint only)",
    "only": "Only (byte and PCM hashes, no fingerprinting)",
    "also": "Also (fingerprint plus byte and PCM hashes)",
}

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
                # An exact-only run stores a properties row with no words; it
                # must not be trusted as a fingerprint, or the next ``also``
                # run would skip fpcalc and cluster nothing.
                if (
                    cached is not None
                    and cached.words
                    and cache.is_fresh(cached, stat.st_mtime, stat.st_size)
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
                # Changed in 2.4.1: BLE001 triage (WP-7 of
                # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
                except Exception as exc:  # noqa: BLE001 - a counted per-file outcome
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
        One keeper line followed by one line per duplicate.  A fingerprint
        group names the measured distance; an exact group names the equality
        that joined it, because there is no distance to report.

        An exact member's token is chosen from **its own** digest against the
        keeper's, never from the group's kind.  One component can hold a
        byte-for-byte copy beside a retagged one, and choosing the label per
        group printed the byte copy as "different bytes" — a claim the member's
        own hash contradicts (D-22).
    """
    lines = [f"{STATUS_KEEP} {group.keeper.path} | {group.keeper.label}\n"]
    for member in group.duplicates:
        if group.kind in (KIND_BYTES, KIND_PCM):
            same_bytes = bool(member.record.file_sha256) and (
                member.record.file_sha256 == group.keeper.file_sha256
            )
            if same_bytes:
                lines.append(
                    f"{STATUS_EXACT} {member.record.path} | byte-identical copy "
                    f"of keeper | {member.record.label}\n"
                )
            else:
                lines.append(
                    f"{STATUS_EXACT_PCM} {member.record.path} | same decoded PCM, "
                    f"different bytes | {member.record.label}\n"
                )
            continue
        lines.append(
            f"{STATUS_DUPLICATE} {member.record.path} | distance "
            f"{member.distance:.4f} from keeper | {member.record.label}\n"
        )
    return lines


def _hash_files(
    files: list[str],
    root: str,
    cache: FingerprintCache,
    on_progress: Callable[..., None],
    outcome: ScanOutcome,
) -> list[FingerprintRecord]:
    """Return a hashed record for every file, without fingerprinting any.

    This is the ``exact_mode="only"`` pass: fpcalc is never invoked, so a
    library the user only wants byte/PCM answers for is never fingerprinted.

    Args:
        files: Absolute paths from :func:`discover_files`.
        root: The scan root, which is the cache's scope.
        cache: The fingerprint cache to read from and write to.
        on_progress: Per-file progress callback.
        outcome: Mutable run counters and log lines.

    Returns:
        The records, in scan order, each carrying both digests when it could
        be hashed.
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
                    outcome.hash_errors += 1
                    outcome.log_entries.append(f"{STATUS_ERROR} {path} | {exc}\n")
                    processed += 1
                    on_progress(
                        processed=processed,
                        total=len(files),
                        skipped=outcome.missing_fingerprint,
                        errors=outcome.hash_errors,
                        display_text=f"{STATUS_ERROR} {os.path.basename(path)}",
                    )
                    continue

                cached = cached_records.get(os.path.normpath(path))
                if (
                    cached is not None
                    and cached.file_sha256
                    and cached.pcm_sha256
                    and cache.is_fresh(cached, stat.st_mtime, stat.st_size)
                ):
                    records.append(cached)
                    processed += 1
                    on_progress(
                        processed=processed,
                        total=len(files),
                        skipped=outcome.missing_fingerprint,
                        errors=outcome.hash_errors,
                        display_text=f"{STATUS_CACHED} {os.path.basename(path)}",
                    )
                    continue

                try:
                    record = attach_hashes(
                        build_properties_record(path, stat.st_mtime, stat.st_size)
                    )
                # Changed in 2.4.1: BLE001 triage (WP-7 of
                # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
                except Exception as exc:  # noqa: BLE001 - a counted per-file outcome
                    mapped = map_to_audio_error(exc)
                    reason = user_message_for(mapped)
                    outcome.hash_errors += 1
                    outcome.log_entries.append(f"{STATUS_ERROR} {path} | {reason}\n")
                    logger.warning("Could not hash %s: %s", path, reason)
                    processed += 1
                    on_progress(
                        processed=processed,
                        total=len(files),
                        skipped=outcome.missing_fingerprint,
                        errors=outcome.hash_errors,
                        display_text=f"{STATUS_ERROR} {os.path.basename(path)}",
                    )
                    continue

                cache.upsert(record)
                outcome.hashed += 1
                records.append(record)
                processed += 1
                on_progress(
                    processed=processed,
                    total=len(files),
                    skipped=outcome.missing_fingerprint,
                    errors=outcome.hash_errors,
                    display_text=f"{STATUS_EXACT} {os.path.basename(path)}",
                )
    finally:
        cache.remove_orphans(root, {os.path.normpath(path) for path in files})
    return records


def _add_hashes(
    records: list[FingerprintRecord],
    cache: FingerprintCache,
    outcome: ScanOutcome,
) -> list[FingerprintRecord]:
    """Return *records* with the exact-duplicate digests filled in.

    This is the ``exact_mode="also"`` pass: the fingerprints are already
    computed, so a cached row that predates the digest columns costs one decode
    and no fpcalc call.  A file that cannot be decoded keeps its fingerprint and
    is simply never exact-grouped; the failure is counted and reported.

    Args:
        records: Fingerprinted records, in scan order.
        cache: The cache whose rows gain the digests.
        outcome: Mutable run counters and log lines.

    Returns:
        The records, in the same order.
    """
    updated: list[FingerprintRecord] = []
    with cache.batch():
        for record in records:
            if record.file_sha256 and record.pcm_sha256:
                updated.append(record)
                continue
            try:
                hashed = attach_hashes(record)
            # Changed in 2.4.1: BLE001 triage (WP-7 of
            # PLAN_2026-11-03_2.4.1_stop_the_drift.md, D-31).
            except Exception as exc:  # noqa: BLE001 - a counted per-file outcome
                mapped = map_to_audio_error(exc)
                reason = user_message_for(mapped)
                outcome.hash_errors += 1
                outcome.log_entries.append(
                    f"{STATUS_ERROR} {record.path} | not hashed: {reason}\n"
                )
                logger.warning("Could not hash %s: %s", record.path, reason)
                updated.append(record)
                continue
            cache.upsert(hashed)
            outcome.hashed += 1
            updated.append(hashed)
    return updated


def _merge_exact_and_perceptual(
    perceptual: list[DuplicateGroup],
    exact: list[DuplicateGroup],
    settings: ScanSettings,
) -> list[DuplicateGroup]:
    """Return *perceptual* over only the files an exact group does not claim.

    In ``exact_mode="also"`` a byte-identical copy is also perceptually
    identical, so naming it in both sets would report the same file twice and
    count it twice in the summary.  The exact line is the stronger claim, so it
    keeps every file it names — **keeper and members alike**.

    Claiming only the exact *duplicates* is not enough: the perceptual group's
    keeper can itself be an exact duplicate, and the perceptual set's remaining
    member can be an exact group's *keeper*.  That file would then be printed as
    ``[KEEP]`` by one group and as a ``[DUPLICATE]`` by the other, and a live run
    would quarantine a file the report tells the reader to keep.  A file claimed
    by an exact group is therefore removed from the perceptual set wholesale;
    what is left is re-keepered from its own members and its distances are
    re-measured against that keeper, so a line never quotes a distance to a file
    it no longer compares against.

    Args:
        perceptual: Groups joined by fingerprint distance.
        exact: Groups joined by a digest.
        settings: The run's threshold and comparison bounds.

    Returns:
        The perceptual groups a reader has not already seen.
    """
    claimed = {group.keeper.path for group in exact}
    claimed.update(member.record.path for group in exact for member in group.duplicates)
    merged: list[DuplicateGroup] = []
    for group in perceptual:
        members = [group.keeper, *(member.record for member in group.duplicates)]
        remaining = [record for record in members if record.path not in claimed]
        if len(remaining) < 2:
            continue
        keeper = choose_keeper(remaining)
        duplicates = tuple(
            DuplicateMember(
                record=record,
                distance=bit_error_rate(
                    keeper.words,
                    record.words,
                    max_shift_words=settings.max_shift_words,
                    min_overlap_ratio=settings.min_overlap_ratio,
                ),
            )
            for record in sorted(remaining, key=lambda item: item.path)
            if record is not keeper
        )
        merged.append(
            DuplicateGroup(keeper=keeper, duplicates=duplicates, kind=group.kind)
        )
    return merged


def _verify_stub(stub_path: Path, keeper_path: str) -> None:
    """Re-read a written stub and prove its reference reaches the keeper.

    Args:
        stub_path: The stub just written beside the duplicate.
        keeper_path: The copy the stub must point at.

    Raises:
        ValueError: If the stub has no reference or it does not resolve to the
            keeper.  The caller leaves the duplicate in place.
    """
    metadata = read_stub(stub_path)
    if not metadata.reference:
        raise ValueError("the stub has no reference")
    href = Path(metadata.reference)
    resolved = href if href.is_absolute() else stub_path.parent / href
    if resolved.resolve() != Path(keeper_path).resolve():
        raise ValueError("the stub does not point at the kept file")


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

    disposition = active_settings.disposition
    if not is_dry_run and uses_trash(disposition) and not trash_available():
        install = ensure_trash_available()
        if not install.ok:
            logger.error(
                "Recycle Bin support could not be enabled: %s\n%s",
                install.message,
                install.detail,
            )
            error(
                "The Recycle Bin could not be prepared automatically, so no "
                "files were changed. Check your internet connection and try "
                "again."
            )
            return

    quarantine_dir = active_settings.quarantine_dir or default_quarantine_dir(dir_path)
    if disposition == Disposition.QUARANTINE.value:
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
        f"Disposition: {label_for(disposition)}\n",
    ]
    if disposition == Disposition.QUARANTINE.value:
        header.append(f"Quarantine: {quarantine_dir}\n")

    exact_mode = active_settings.exact_mode
    with FingerprintCache(cache_path) as cache:
        if exact_mode == "only":
            records = _hash_files(files, dir_path, cache, progress, outcome)
        else:
            records = _fingerprint_files(files, dir_path, cache, progress, outcome)
            if exact_mode == "also":
                records = _add_hashes(records, cache, outcome)

    header.append(f"Exact matching: {EXACT_MODE_LABELS[exact_mode]}\n")
    if exact_mode != "off":
        header.append(f"Hashes computed: {outcome.hashed} file(s)\n")
    header.append("=" * 60 + "\n")

    exact_groups = build_exact_groups(records) if exact_mode != "off" else []
    perceptual_groups = (
        [] if exact_mode == "only" else cluster_records(records, active_settings)
    )
    if exact_groups:
        perceptual_groups = _merge_exact_and_perceptual(
            perceptual_groups, exact_groups, active_settings
        )
    groups = sorted(
        exact_groups + perceptual_groups,
        key=lambda group: (-len(group.duplicates), group.keeper.path),
    )
    outcome.groups = groups
    outcome.duplicates = sum(len(group.duplicates) for group in groups)
    exact_duplicates = sum(len(group.duplicates) for group in exact_groups)

    action_errors = 0
    for group in groups:
        outcome.log_entries.extend(_group_lines(group))
        for member in group.duplicates:
            if is_dry_run:
                if disposition == Disposition.DELETE.value:
                    outcome.log_entries.append(
                        f"{STATUS_DELETED} {member.record.path} -> Recycle Bin "
                        "(dry run)\n"
                    )
                elif disposition == Disposition.ASX_STUB.value:
                    outcome.log_entries.append(
                        f"{STATUS_STUBBED} {member.record.path} -> "
                        f"{stub_path_for(member.record.path)} "
                        f"(keeper: {group.keeper.path}) (dry run)\n"
                    )
                continue

            path = member.record.path
            if disposition == Disposition.QUARANTINE.value:
                try:
                    destination = quarantine_file(path, quarantine_dir)
                except OSError as exc:
                    action_errors += 1
                    outcome.log_entries.append(
                        f"{STATUS_ERROR} {path} | move failed: {exc}\n"
                    )
                    continue
                outcome.quarantined += 1
                outcome.log_entries.append(f"{STATUS_MOVED} {path} -> {destination}\n")
                continue

            if disposition == Disposition.DELETE.value:
                try:
                    move_to_trash(path)
                except (OSError, TrashUnavailableError) as exc:
                    action_errors += 1
                    outcome.log_entries.append(
                        f"{STATUS_ERROR} {path} | Trash failed: {exc}\n"
                    )
                    continue
                outcome.deleted += 1
                outcome.log_entries.append(f"{STATUS_DELETED} {path} -> Recycle Bin\n")
                continue

            stub_path = stub_path_for(path)
            try:
                metadata = with_keeper(snapshot_tags(path), group.keeper.path)
                write_stub(stub_path, metadata)
                _verify_stub(stub_path, group.keeper.path)
            except Exception as exc:  # noqa: BLE001 - stub failure is logged per file
                stub_path.unlink(missing_ok=True)
                action_errors += 1
                outcome.log_entries.append(
                    f"{STATUS_ERROR} {path} | stub not written: {exc}\n"
                )
                continue
            try:
                move_to_trash(path)
            except (OSError, TrashUnavailableError) as exc:
                action_errors += 1
                outcome.log_entries.append(
                    f"{STATUS_ERROR} {path} | stub written but the duplicate "
                    f"was not removed: {exc}\n"
                )
                continue
            outcome.stubbed += 1
            outcome.log_entries.append(
                f"{STATUS_STUBBED} {path} -> {stub_path} "
                f"(keeper: {group.keeper.path})\n"
            )

    if not groups:
        outcome.log_entries.append("No duplicate recordings found.\n")

    duration = time.monotonic() - started
    logger.info(
        "Duplicate scan: %d files, %d groups, %d duplicates, %d quarantined, "
        "%d deleted, %d stubbed",
        len(files),
        len(groups),
        outcome.duplicates,
        outcome.quarantined,
        outcome.deleted,
        outcome.stubbed,
    )
    complete(
        header=header,
        total=len(files),
        processed=len(files),
        skipped=outcome.missing_fingerprint,
        errors=action_errors + outcome.hash_errors,
        duration_secs=duration,
        log_entries=outcome.log_entries,
        groups=len(groups),
        duplicates=outcome.duplicates,
        exact_groups=len(exact_groups),
        exact_duplicates=exact_duplicates,
        hashed=outcome.hashed,
        quarantined=outcome.quarantined,
        deleted=outcome.deleted,
        stubbed=outcome.stubbed,
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
