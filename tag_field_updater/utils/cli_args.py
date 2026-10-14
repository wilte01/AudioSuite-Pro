"""cli_args.py — Launcher argument parsing for the Tag Field Updater.

Mirrors the Tag Editor launcher contract so the Master Driver's argv reaches
the GUI widgets.

Master Driver handshake layout:
    argv[1]            - music directory (scanned recursively)
    named flags:       --live|--dry, --start|--no-start, --end|--no-end,
    display-only:      --clear-logs|--no-clear-logs,
                       --parallel-run|--no-parallel-run

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.

Changed in 1.0.1: adds the driver argv parser.
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


@dataclass
class TagFieldUpdaterArgs(BaseCLIArgs):
    """Parsed Tag Field Updater launcher arguments."""

    clear_logs: bool = False
    parallel_run: bool = False


def parse(argv: list[str] | None = None) -> TagFieldUpdaterArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`TagFieldUpdaterArgs` instance.

    Raises:
        SystemExit: With code 1 when the folder path does not exist.
    """
    if argv is None:
        argv = sys.argv
    args = TagFieldUpdaterArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    apply_handshake_segment(argv[2:], args, accepted=ACCEPTED_HANDSHAKE)
    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("Tag Field Updater", error)
        raise SystemExit(1)
    return args
