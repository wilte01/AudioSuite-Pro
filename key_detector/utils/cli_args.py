"""
cli_args.py — CLI argument parser for Key Detector.

Master Driver handshake layout:
    argv[1]  - folder path
    argv[3]  - '--live' | '--dry'
    argv[4]  - '--start' | '--no-start'
    argv[5]  - '--end' | '--no-end'
    argv[6+] - named pairs: --duration N, --workers N, --parallel|--no-parallel
               display-only flags: --clear-logs|--no-clear-logs,
               --parallel-run|--no-parallel-run

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.
"""

import os
import sys
from dataclasses import dataclass
from typing import Any

from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.cli_helpers import (
    consume_handshake_token,
    print_tool_usage_error,
    read_positional_handshake,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)


@dataclass
class KeyDetectorArgs(BaseCLIArgs):
    """CLI arguments for Key Detector."""

    analysis_duration: int = 90
    parallel_mode: bool = False
    max_workers: int = 4
    clear_logs: bool = False  # Display only — driver-owned orchestration flag
    parallel_run: bool = False  # Display only — driver-owned orchestration flag


# The named-pair tail accepted only the display-only pair (mode/start/end
# live in the fixed positional slots); mirror that token subset byte-exactly.
ACCEPTED_HANDSHAKE = frozenset(
    {
        "--clear-logs",
        "--no-clear-logs",
        "--parallel-run",
        "--no-parallel-run",
    }
)


def validate_args(args: KeyDetectorArgs) -> list[Any]:
    """Validate CLI arguments and return list of errors."""
    errors = []
    if args.folder_path:
        if not os.path.exists(args.folder_path):
            errors.append(f"Folder path does not exist: {args.folder_path}")
        elif not os.path.isdir(args.folder_path):
            errors.append(f"Path is not a directory: {args.folder_path}")
    if args.analysis_duration < 10 or args.analysis_duration > 600:
        errors.append(
            f"Analysis duration must be 10-600 seconds, got: {args.analysis_duration}"
        )
    return errors


def parse(argv: list[str] | None = None) -> KeyDetectorArgs:
    if argv is None:
        argv = sys.argv
    args = KeyDetectorArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    read_positional_handshake(argv, args, mode_idx=3, start_idx=4, end_idx=5)
    i = 6
    while i < len(argv):
        arg = argv[i]
        if arg == "--duration" and i + 1 < len(argv):
            try:
                args.analysis_duration = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--workers" and i + 1 < len(argv):
            try:
                args.max_workers = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--parallel":
            args.parallel_mode = True
            i += 1
        elif arg == "--no-parallel":
            args.parallel_mode = False
            i += 1
        elif consume_handshake_token(arg, args, accepted=ACCEPTED_HANDSHAKE) is True:
            i += 1
        else:
            i += 1
    errors = validate_args(args)
    if errors:
        for error in errors:
            print_tool_usage_error("Key Detector", error)
        raise SystemExit(1)
    return args
