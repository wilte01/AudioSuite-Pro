r"""
undo.py — Command-line undo for Audio Suite batch operations.

Lists, inspects, and reverts the SQLite undo batches written by the suite
tools (BPM Analyzer, Tempo Analyzer, Mood Analysis Batch Tagger, Tag Field
Updater, File Reorganizer, ...).  A batch collects every file a single run
touched;
``undo`` restores the pre-run tags, puts back audio that a tool repaired in
place (Noise Reduction, Pop & Click Remover), or reverses file copies/moves.

Batches live in ``~/.audiosuite/undo_log.db`` unless ``--db`` is given.

Usage:
    python undo.py list [--limit 20] [--db PATH]
    python undo.py show BATCH_ID [--db PATH]
    python undo.py undo BATCH_ID [--db PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from audio_suite_shared.batch_undo import (
    BatchInfo,
    BatchUndoLog,
    RevertResult,
    list_recent_batches,
    revert_batch_by_id,
)


def _print_batches(batches: list[BatchInfo]) -> None:
    """Print recent undo batches, newest first.

    Args:
        batches: List of ``BatchInfo`` objects.
    """
    if not batches:
        print("  [INFO] No undo batches found.")
        return
    for b in batches:
        print(
            f"  [OK] {b.created_at}  {b.tool_name}/{b.operation_type}  "
            f"{b.record_count} record(s)  {b.batch_id}"
        )


def _batch_exists(db_path: Path | None, batch_id: str) -> bool:
    """Return True if a batch with *batch_id* exists in the undo log.

    Args:
        db_path: Path to the SQLite undo database.
        batch_id: Batch id to look up.

    Returns:
        True if the batch row exists.
    """
    with BatchUndoLog(db_path=db_path) as log:
        rows = log.list_batches(limit=10_000)
        return any(r.batch_id == batch_id for r in rows)


def _cmd_list(args: argparse.Namespace) -> int:
    """Handle the ``list`` subcommand."""
    try:
        batches = list_recent_batches(limit=args.limit, db_path=args.db)
    except Exception as exc:  # nosec B110 - reported to the user
        print(f"  [ERROR] Could not read undo log: {exc}", file=sys.stderr)
        return 1
    _print_batches(batches)
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    """Handle the ``show`` subcommand."""
    if not _batch_exists(args.db, args.batch_id):
        print(f"  [ERROR] Unknown batch: {args.batch_id}", file=sys.stderr)
        return 1
    try:
        with BatchUndoLog(db_path=args.db) as log:
            records = log.get_batch_records(args.batch_id)
    except Exception as exc:  # nosec B110 - reported to the user
        print(f"  [ERROR] Could not read undo log: {exc}", file=sys.stderr)
        return 1
    if not records:
        print(f"  [INFO] Batch {args.batch_id} has no records.")
        return 0
    for r in records:
        if r.file_action == "move":
            detail = f"move: {r.source_path} -> {r.dest_path}"
        elif r.file_action == "copy":
            detail = f"copy: {r.source_path} -> {r.dest_path}"
        elif r.file_action == "overwrite":
            detail = f"{r.operation} [audio-bytes]"
        else:
            snap = "snapshot" if r.has_snapshot else "no-snapshot"
            detail = f"{r.operation} [{snap}]"
        print(f"  [OK] #{r.record_id}  {detail}  {r.file_path}")
    return 0


def _print_revert_result(result: RevertResult) -> int:
    """Print the outcome of a revert; returns the process exit code.

    Args:
        result: Result of reverting a batch.

    Returns:
        0 on success (nothing failed), 1 when some records failed.
    """
    if result.errors:
        for err in result.errors:
            print(f"  [ERROR] {err}", file=sys.stderr)
    print(
        f"  [DONE] Batch {result.batch_id}: "
        f"{result.reverted} reverted, {result.failed} failed, "
        f"{result.skipped} skipped"
    )
    return 1 if result.failed else 0


def _cmd_undo(args: argparse.Namespace) -> int:
    """Handle the ``undo`` subcommand."""
    if not _batch_exists(args.db, args.batch_id):
        print(f"  [ERROR] Unknown batch: {args.batch_id}", file=sys.stderr)
        return 1
    print(f"  [INFO] Reverting batch {args.batch_id} ...")
    try:
        result = revert_batch_by_id(args.batch_id, db_path=args.db)
    except Exception as exc:  # nosec B110 - reported to the user
        print(f"  [ERROR] Revert failed: {exc}", file=sys.stderr)
        return 1
    return _print_revert_result(result)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "List, inspect, and revert Audio Suite undo batches "
            "(tag edits, in-place audio repairs, and file reorganizations)."
        ),
    )
    parser.add_argument(
        "--db",
        metavar="PATH",
        help=("Path to the undo log database (defaults to ~/.audiosuite/undo_log.db)."),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_list = sub.add_parser("list", help="List recent undo batches.")
    p_list.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of batches to show (default: 20).",
    )

    for name in ("show", "undo"):
        p = sub.add_parser(name, help=f"{name.capitalize()} an undo batch.")
        p.add_argument("batch_id", help="The batch id to act on.")

    for p in sub.choices.values():
        p.add_argument(
            "--db",
            metavar="PATH",
            # SUPPRESS keeps the subparser from writing its default over a
            # --db the top-level parser already consumed: `undo --db X show ID`
            # previously lost X because the subparser's default=None shadowed
            # it. With SUPPRESS the attribute is only set when the flag is
            # actually given after the subcommand.
            default=argparse.SUPPRESS,
            help="Path to the undo log database (overrides the --db above).",
        )

    args = parser.parse_args()

    if args.command == "list":
        sys.exit(_cmd_list(args))
    if args.command == "show":
        sys.exit(_cmd_show(args))
    if args.command == "undo":
        sys.exit(_cmd_undo(args))


if __name__ == "__main__":
    main()
