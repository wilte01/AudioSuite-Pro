"""
cli_args.py — CLI argument parser for Genre Sync.

Master Driver handshake layout:
    argv[1]  - folder path
    argv[2]  - reserved placeholder ('0')
    argv[3]  - '--live' | '--dry'
    argv[4]  - '--start' | '--no-start'
    argv[5]  - '--end' | '--no-end'
    argv[6]  - '--clear-logs' | '--no-clear-logs'     (display only)
    argv[7]  - '--parallel-run' | '--no-parallel-run' (display only)

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.
"""

import os
import sys
from dataclasses import dataclass
from typing import Optional

from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.cli_helpers import (
    print_tool_usage_error,
    read_display_flag_slots,
    read_positional_handshake,
    was_launched_from_driver as was_launched_from_driver,
)


@dataclass
class GenreSyncArgs(BaseCLIArgs):
    """CLI arguments for Genre Sync (no tool-specific extras)."""

    clear_logs: bool = False
    parallel_run: bool = False


def validate_args(args: GenreSyncArgs) -> list[str]:
    """Validate CLI arguments and return list of errors."""
    errors: list[str] = []
    if args.folder_path:
        if not os.path.exists(args.folder_path):
            errors.append(f"Folder path does not exist: {args.folder_path}")
        elif not os.path.isdir(args.folder_path):
            errors.append(f"Path is not a directory: {args.folder_path}")
    return errors


def parse(argv: Optional[list[str]] = None) -> GenreSyncArgs:
    if argv is None:
        argv = sys.argv
    args = GenreSyncArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    read_positional_handshake(argv, args, mode_idx=3, start_idx=4, end_idx=5)

    # Display-only driver orchestration state (controls stay inert).
    read_display_flag_slots(argv, args, logs_idx=6, parallel_run_idx=7)

    errors = validate_args(args)
    if errors:
        for error in errors:
            print_tool_usage_error("Genre Sync", error)
        raise SystemExit(1)
    return args
