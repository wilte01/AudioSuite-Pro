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
    apply_handshake_segment,
    print_tool_usage_error,
    was_launched_from_driver as was_launched_from_driver,
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
    apply_handshake_segment(argv[2:], args, accepted=ACCEPTED_HANDSHAKE)
    errors = validate_args(args)
    if errors:
        for error in errors:
            print_tool_usage_error("Tag Editor", error)
        raise SystemExit(1)
    return args
