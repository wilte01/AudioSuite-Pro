"""
cli_args.py — CLI argument parser for Mood Analysis Batch Tagger.

Master Driver handshake layout (utility style):
    argv[1]            - root music directory (scanned recursively)
    named flags:       --live|--dry,
                       --start|--no-start,
                       --end|--no-end,
                       --duration N,
                       --parallel|--no-parallel,
                       --workers N,
    display-only:      --clear-logs|--no-clear-logs,
                       --parallel-run|--no-parallel-run

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.

Changed in 1.4.0: ``max_workers`` defaults to ``default_max_workers()``.
"""

import os
import sys
from dataclasses import dataclass, field

from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.cli_helpers import (
    consume_handshake_token,
    print_tool_usage_error,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)
from audio_suite_shared.constants import default_max_workers

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
class MoodAnalysisBatchTaggerArgs(BaseCLIArgs):
    """CLI arguments for Mood Analysis Batch Tagger."""

    analysis_duration: int = 90
    parallel_mode: bool = False
    max_workers: int = field(default_factory=default_max_workers)
    clear_logs: bool = False  # Display only — driver-owned orchestration flag
    parallel_run: bool = False  # Display only — driver-owned orchestration flag


def validate_args(args: MoodAnalysisBatchTaggerArgs) -> list[str]:
    """Validate CLI arguments and return a list of error strings.

    Args:
        args: Parsed CLI arguments to validate.

    Returns:
        List of human-readable error strings; empty when valid.
    """
    errors: list[str] = []
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


def parse(argv: list[str] | None = None) -> MoodAnalysisBatchTaggerArgs:
    """Parse command line arguments for the Mood Analysis Batch Tagger.

    Args:
        argv: Argument vector to parse; defaults to ``sys.argv``.

    Returns:
        A :class:`MoodAnalysisBatchTaggerArgs` populated from *argv*.

    Raises:
        SystemExit: With code 1 when validation fails.
    """
    if argv is None:
        argv = sys.argv
    args = MoodAnalysisBatchTaggerArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    i = 2
    while i < len(argv):
        arg = argv[i]
        if consume_handshake_token(arg, args, accepted=ACCEPTED_HANDSHAKE) is True:
            i += 1
        elif arg in ("--parallel", "--no-parallel"):
            args.parallel_mode = arg == "--parallel"
            i += 1
        elif arg == "--duration" and i + 1 < len(argv):
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
        else:
            i += 1
    errors = validate_args(args)
    if errors:
        for error in errors:
            print_tool_usage_error("Mood Analysis Batch Tagger", error)
        raise SystemExit(1)
    return args
