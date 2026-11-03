"""cli_args.py — Launcher argument parsing for the Library Statistics Dashboard.

Mirrors the Tag Editor launcher contract so the Master Driver's argv reaches
the GUI widgets.

Master Driver handshake layout:
    argv[1]              - music directory (scanned recursively)
    --incremental        - incremental scan using cache
    --refresh            - full re-scan rebuilding the cache
    --export-csv <path>  - export per-file metadata to CSV
    --export-json <path> - export StatsReport as JSON
    named flags:         --live|--dry, --start|--no-start, --end|--no-end,
    display-only:        --clear-logs|--no-clear-logs,
                         --parallel-run|--no-parallel-run

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.

Changed in 1.0.1: adds the driver argv parser.

Changed in 2.4.1: reads the driver argv through the shared
``scan_value_options`` / ``parse_driver_handshake`` grammar instead of
its own scanner (WP-4, C-M8).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, validate_folder_path
from audio_suite_shared.cli_helpers import (
    apply_str_options,
    parse_driver_handshake,
    print_tool_usage_error,
    scan_value_options,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)

ACCEPTED_HANDSHAKE = frozenset(
    {
        "--live",
        "--dry",
        "--start",
        "--no-start",
        "--end",
        "--no-end",
        "--clear-logs",
        "--no-clear-logs",
        "--parallel-run",
        "--no-parallel-run",
    }
)

#: Named options that consume the token following them.
_VALUE_OPTIONS: dict[str, str] = {
    "--export-csv": "export_csv",
    "--export-json": "export_json",
}


@dataclass
class LibraryStatsArgs(BaseCLIArgs):
    """Parsed Library Statistics launcher arguments."""

    incremental: bool = False
    refresh: bool = False
    export_csv: str = ""
    export_json: str = ""
    clear_logs: bool = False
    parallel_run: bool = False


def parse(argv: list[str] | None = None) -> LibraryStatsArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`LibraryStatsArgs` instance.

    Raises:
        SystemExit: With code 1 when the folder path does not exist.
    """
    if argv is None:
        argv = sys.argv
    args = LibraryStatsArgs()
    if len(argv) < 2:
        return args
    args.apply_handshake(parse_driver_handshake(argv, _VALUE_OPTIONS))
    tail = argv[1:]
    args.incremental = "--incremental" in tail
    args.refresh = "--refresh" in tail
    values, _ = scan_value_options(tail, _VALUE_OPTIONS)
    apply_str_options(args, values, _VALUE_OPTIONS)
    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("Library Statistics", error)
        raise SystemExit(1)
    return args
