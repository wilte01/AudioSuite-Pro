"""cli_args.py — Launcher argument parsing for the Tag Editor.

Master Driver handshake layout (utility style):
    argv[1]            - root music directory (scanned recursively)
    named flags:       --live|--dry,
                       --start|--no-start,
                       --end|--no-end,
    display-only:      --clear-logs|--no-clear-logs,
                       --parallel-run|--no-parallel-run
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, validate_folder_path
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)


@dataclass
class TagEditorArgs(BaseCLIArgs):
    """Parsed Tag Editor launcher arguments."""

    clear_logs: bool = False
    parallel_run: bool = False


def validate_args(args: TagEditorArgs) -> list[str]:
    """Validate launcher arguments.

    Args:
        args: Parsed launcher arguments.

    Returns:
        Human-readable validation errors; empty when valid.
    """
    errors = validate_folder_path(args.folder_path)
    if args.folder_path and not os.path.isdir(args.folder_path):
        errors.append(f"Path is not a directory: {args.folder_path}")
    return errors


def parse(argv: list[str] | None = None) -> TagEditorArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`TagEditorArgs` instance.

    Raises:
        SystemExit: With code 1 when validation fails.
    """
    if argv is None:
        argv = sys.argv
    args = TagEditorArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    i = 2
    while i < len(argv):
        arg = argv[i]
        if arg in ("--start", "--no-start"):
            args.auto_start = arg == "--start"
            i += 1
        elif arg in ("--end", "--no-end"):
            args.auto_end = arg == "--end"
            i += 1
        elif arg in ("--dry", "--live"):
            args.live_mode = arg == "--live"
            i += 1
        elif arg in ("--clear-logs", "--no-clear-logs"):
            args.clear_logs = arg == "--clear-logs"
            i += 1
        elif arg in ("--parallel-run", "--no-parallel-run"):
            args.parallel_run = arg == "--parallel-run"
            i += 1
        else:
            i += 1
    errors = validate_args(args)
    if errors:
        for error in errors:
            print(f"Tag Editor: {error}", file=sys.stderr)
        raise SystemExit(1)
    return args
