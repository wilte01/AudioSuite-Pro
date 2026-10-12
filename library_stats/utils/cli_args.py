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
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, validate_folder_path
from audio_suite_shared.cli_helpers import (
    apply_handshake_segment,
    print_tool_usage_error,
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


def _scan_value_options(tokens: list[str], args: LibraryStatsArgs) -> None:
    """Fill value options from *tokens*, skipping unknown tokens.

    Args:
        tokens: The argv tail after the positional directory path.
        args: The args instance mutated in place.
    """
    index = 0
    while index < len(tokens):
        attr = _VALUE_OPTIONS.get(tokens[index])
        if attr is not None and index + 1 < len(tokens):
            setattr(args, attr, tokens[index + 1])
            index += 2
            continue
        index += 1


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
    args.folder_path = argv[1]
    tail = argv[2:]
    args.incremental = "--incremental" in tail
    args.refresh = "--refresh" in tail
    _scan_value_options(tail, args)
    apply_handshake_segment(tail, args, accepted=ACCEPTED_HANDSHAKE)
    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("Library Statistics", error)
        raise SystemExit(1)
    return args
