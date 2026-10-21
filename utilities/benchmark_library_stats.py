#!/usr/bin/env python3
"""benchmark_library_stats.py

Time the two plans ``LibraryCache`` chooses between for a scoped query.

Usage:
    python utilities/benchmark_library_stats.py
    python utilities/benchmark_library_stats.py --rows 50000 --scope 500 --runs 5

Why this exists
---------------
PLAN D97: ``get_cached_mtimes``, ``remove_orphans`` and ``clear_dir`` ran the
sequential ``INSTR(LOWER(path), …)`` predicate regardless of scope, so
``idx_files_path_fold`` served the multi-statement reports only.  The plan rule
is ``scoped * 2 < total``, measured rather than assumed (a sequential scan beats
the index at whole-library selectivity).

This script builds one synthetic cache, prints the plan the real
:meth:`LibraryCache.scope_plan_kind` chooses for the scope, and times both
predicates.  The statements are imported from ``library_stats.library_cache``,
so the benchmark measures the SQL the methods actually execute instead of a
hand-copied paraphrase.

The delete timing includes the commit, because a real ``clear_dir`` pays it.
Every delete runs on its own copy of the file, so one run cannot influence the
next.  Both plans are also checked for agreement: a faster query that returned
different rows would be a defect, not an optimisation.

Exit status: 0 when both plans agree, 1 when they do not, 2 on bad arguments.

Changed in 1.4.1: initial version, the D97 scope-plan benchmark.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import sqlite3
import statistics
import sys
import tempfile
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from library_stats.library_cache import (
    _SCOPE_RANGE_HIGH,
    _SCOPED_CLEAR_INDEXED,
    _SCOPED_CLEAR_SEQUENTIAL,
    _SCOPED_HASHES_INDEXED,
    _SCOPED_HASHES_SEQUENTIAL,
    _SCOPED_MTIMES_INDEXED,
    _SCOPED_MTIMES_SEQUENTIAL,
    LibraryCache,
    _path_fold,
)


def _build(db_path: Path, rows: int, scope: int) -> tuple[str, str]:
    """Create *db_path* with *rows* synthetic files, *scope* under one folder.

    The size difference is what makes the rule pick a plan: the scoped folder is
    a small slice of the whole cache, so it resolves to ``indexed``.

    Args:
        db_path: Cache file to create.
        rows: Total rows to write.
        scope: How many of them live in the scoped folder.

    Returns:
        ``(scope_dir, sibling_dir)`` as absolute strings.
    """
    root = db_path.parent / "library"
    scope_dir = root / "scope"
    sibling_dir = root / "bulk"
    cache = LibraryCache(db_path)
    try:
        with cache.batch():
            for index in range(scope):
                cache.upsert_file(
                    str(scope_dir / f"t{index}.mp3"),
                    mtime=float(index),
                    size=1024,
                    format_ext=".mp3",
                )
            for index in range(rows - scope):
                cache.upsert_file(
                    str(sibling_dir / f"d{index % 100:03d}" / f"t{index}.mp3"),
                    mtime=float(index),
                    size=1024,
                    format_ext=".mp3",
                )
        # Fold the WAL into the main file so a per-run copy sees every row.
        cache._connect().execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        cache.close()
    return str(scope_dir), str(sibling_dir)


def _prefixes(scope_dir: str) -> tuple[str, str]:
    """Return ``(sequential_prefix, folded_prefix)`` for *scope_dir*."""
    prefixed = os.path.normpath(scope_dir)
    if not prefixed.endswith(os.sep):
        prefixed += os.sep
    return prefixed, _path_fold(prefixed)


def _median_ms(
    conn: sqlite3.Connection,
    sql: str,
    params: Sequence[Any],
    runs: int,
) -> tuple[float, list[tuple[Any, ...]]]:
    """Return ``(median milliseconds, rows)`` for *sql* over *runs* samples."""
    samples: list[float] = []
    rows: list[tuple[Any, ...]] = []
    for _ in range(runs):
        started = time.perf_counter()
        rows = conn.execute(sql, params).fetchall()
        samples.append((time.perf_counter() - started) * 1000.0)
    return statistics.median(samples), rows


def _median_delete(
    db_path: Path,
    sql: str,
    params: Sequence[Any],
    runs: int,
) -> tuple[float, list[tuple[Any, ...]]]:
    """Time ``DELETE`` on a fresh copy per run, returning its remaining rows."""
    samples: list[float] = []
    remaining: list[tuple[Any, ...]] = []
    for _ in range(runs):
        with tempfile.TemporaryDirectory() as tmp:
            scratch = Path(tmp) / "cache.db"
            shutil.copyfile(db_path, scratch)
            conn = sqlite3.connect(str(scratch))
            try:
                started = time.perf_counter()
                conn.execute(sql, params)
                conn.commit()
                samples.append((time.perf_counter() - started) * 1000.0)
                remaining = conn.execute(
                    "SELECT path FROM files ORDER BY path"
                ).fetchall()
            finally:
                conn.close()
    return statistics.median(samples), remaining


def _speedup(sequential: float, indexed: float) -> str:
    """Return the indexed plan's speed-up against the sequential one."""
    if indexed <= 0:
        return "n/a"
    return f"{sequential / indexed:.1f}x"


def main(argv: Sequence[str] | None = None) -> int:
    """Build the synthetic cache, measure both plans, and compare their rows.

    Args:
        argv: Arguments to parse; defaults to ``sys.argv[1:]``.

    Returns:
        Process exit status (see the module docstring).
    """
    parser = argparse.ArgumentParser(
        prog="python utilities/benchmark_library_stats.py",
        description="Time the scoped LibraryCache predicates in both plans.",
    )
    parser.add_argument("--rows", type=int, default=200_000, help="total rows")
    parser.add_argument("--scope", type=int, default=2_000, help="rows in scope")
    parser.add_argument("--runs", type=int, default=3, help="samples per timing")
    args = parser.parse_args(argv)

    if args.rows < 1 or args.scope < 1 or args.runs < 1:
        print(
            "[ERROR] --rows, --scope and --runs must all be positive.",
            file=sys.stderr,
        )
        return 2
    if args.scope > args.rows:
        print("[ERROR] --scope cannot exceed --rows.", file=sys.stderr)
        return 2

    print(f"[START] synthetic cache: {args.rows} rows, scope {args.scope}")
    print(f"[INFO] host: {platform.platform()} / Python {platform.python_version()}")
    print(f"[INFO] sqlite: {sqlite3.sqlite_version}")

    with tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "cache.db"
        scope_dir, _sibling = _build(db_path, args.rows, args.scope)
        sequential_prefix, folded_prefix = _prefixes(scope_dir)
        indexed_params = [folded_prefix, folded_prefix + _SCOPE_RANGE_HIGH]
        sequential_params = [sequential_prefix]

        cache = LibraryCache(db_path)
        try:
            plan = cache.scope_plan_kind(scope_dir)
            conn = cache._connect()
            print(f"[INFO] plan chosen for the scope: {plan}")
            if plan != "indexed":
                print(
                    "[ERROR] the rule did not choose the indexed plan; "
                    "increase --rows or lower --scope.",
                    file=sys.stderr,
                )
                return 1

            mtimes_seq, rows_seq = _median_ms(
                conn, _SCOPED_MTIMES_SEQUENTIAL, sequential_params, args.runs
            )
            mtimes_idx, rows_idx = _median_ms(
                conn, _SCOPED_MTIMES_INDEXED, indexed_params, args.runs
            )
            hashes_seq, hash_rows_seq = _median_ms(
                conn, _SCOPED_HASHES_SEQUENTIAL, sequential_params, args.runs
            )
            hashes_idx, hash_rows_idx = _median_ms(
                conn, _SCOPED_HASHES_INDEXED, indexed_params, args.runs
            )
            # End-to-end through the public method: it also pays the two COUNT
            # queries that decide the plan, so this number is what a scan sees.
            started = time.perf_counter()
            for _ in range(args.runs):
                cache.scope_plan_kind(scope_dir)
            decision_ms = (time.perf_counter() - started) / args.runs * 1000.0
            started = time.perf_counter()
            for _ in range(args.runs):
                cache.get_cached_mtimes(scope_dir)
            end_to_end_ms = (time.perf_counter() - started) / args.runs * 1000.0

            def _three_reads(cold: bool) -> tuple[float, int]:
                """Time three scoped reads about one directory (PLAN P1).

                ``cold`` forgets the memo first, which is what every scan paid
                before it existed (two COUNTs per read); ``warm`` is a second
                scan of the same directory in one instance.
                """
                if cold:
                    cache.invalidate_scope_plans()
                counted: list[str] = []
                conn.set_trace_callback(counted.append)
                started_reads = time.perf_counter()
                for _ in range(3):
                    cache.get_cached_mtimes(scope_dir)
                elapsed = time.perf_counter() - started_reads
                conn.set_trace_callback(None)
                decisions = sum(
                    1 for line in counted if line.startswith("SELECT COUNT(*)")
                )
                return elapsed * 1000.0, decisions

            cold_scan_ms, cold_decisions = _three_reads(cold=True)
            warm_scan_ms, warm_decisions = _three_reads(cold=False)
        finally:
            cache.close()

        print(
            f"[INFO]   SELECT path, mtime: sequential {mtimes_seq:8.2f} ms | "
            f"indexed {mtimes_idx:6.2f} ms | {_speedup(mtimes_seq, mtimes_idx)}"
        )
        print(
            f"[INFO]   SELECT path_hash: sequential {hashes_seq:8.2f} ms | "
            f"indexed {hashes_idx:6.2f} ms | {_speedup(hashes_seq, hashes_idx)}"
        )
        print(f"[INFO]   scope_plan_kind (the decision itself): {decision_ms:6.2f} ms")
        print(
            f"[INFO]   get_cached_mtimes end-to-end (decision + read): "
            f"{end_to_end_ms:6.2f} ms"
        )
        print(
            f"[INFO]   three scoped reads: cold {cold_scan_ms:7.2f} ms "
            f"({cold_decisions} decision queries) | warm {warm_scan_ms:6.2f} ms "
            f"({warm_decisions}) | saved {cold_scan_ms - warm_scan_ms:5.2f} ms"
        )

        # Deletes mutate, so each plan runs on its own copy of the same file.
        delete_seq, remaining_seq = _median_delete(
            db_path, _SCOPED_CLEAR_SEQUENTIAL, sequential_params, args.runs
        )
        delete_idx, remaining_idx = _median_delete(
            db_path, _SCOPED_CLEAR_INDEXED, indexed_params, args.runs
        )
        print(
            f"[INFO]   DELETE files: sequential {delete_seq:8.2f} ms | "
            f"indexed {delete_idx:6.2f} ms | {_speedup(delete_seq, delete_idx)}"
        )

        agree = (
            dict(rows_seq) == dict(rows_idx)
            and set(hash_rows_seq) == set(hash_rows_idx)
            and remaining_seq == remaining_idx
        )
        print(
            f"[INFO] scoped rows: {len(rows_seq)} mtime / {len(hash_rows_seq)} hash; "
            f"{len(remaining_seq)} left after a clear"
        )

    if not agree:
        print(
            "[ERROR] the two plans disagreed; the faster one is unsafe.",
            file=sys.stderr,
        )
        return 1
    print("[OK] both plans returned identical rows and deleted the same scope.")
    return 0


if __name__ == "__main__":  # pragma: no cover - the CLI is exercised by hand
    raise SystemExit(main())
