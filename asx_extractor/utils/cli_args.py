"""
cli_args.py — CLI argument parser for ASX Playlist Extractor.

Accepted arguments: directory (positional), --mode, --start/--no-start,
--end/--no-end, display-only flags --clear-logs|--no-clear-logs,
--parallel-run|--no-parallel-run.
"""

import argparse
import os
import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)


@dataclass
class ASXExtractorArgs(BaseCLIArgs):
    """CLI arguments for ASX Playlist Extractor."""

    directory: str | None = None
    mode: str | None = None
    clear_logs: bool = False  # Display only — driver-owned orchestration flag
    parallel_run: bool = False  # Display only — driver-owned orchestration flag


def validate_args(args: ASXExtractorArgs) -> list[str]:
    """Validate CLI arguments and return a list of error strings.

    Args:
        args: Parsed ASX extractor arguments.

    Returns:
        A list of human-readable validation error messages.
        Empty if all arguments are valid.
    """
    errors: list[str] = []
    if args.directory:
        if not os.path.exists(args.directory):
            errors.append(f"Directory does not exist: {args.directory}")
        elif not os.path.isdir(args.directory):
            errors.append(f"Path is not a directory: {args.directory}")
    valid_modes = ["Dry Run (Simulated)", "Execute Extraction (Permanent)"]
    if args.mode and args.mode not in valid_modes:
        errors.append(
            f"Mode must be 'Dry Run (Simulated)' or "
            f"'Execute Extraction (Permanent)', "
            f"got: {args.mode}"
        )
    return errors


def parse(argv: list[str] | None = None) -> ASXExtractorArgs:
    """Parse command line arguments for the ASX Playlist Extractor.

    Args:
        argv: Argument list to parse. Defaults to sys.argv when None.

    Returns:
        A populated and validated ASXExtractorArgs instance.

    Raises:
        SystemExit: If validation fails.
    """
    parser = argparse.ArgumentParser(description="ASX Playlist Extractor")
    parser.add_argument(
        "--mode",
        default=None,
        choices=["Dry Run (Simulated)", "Execute Extraction (Permanent)"],
        help="Extraction mode.",
    )
    parser.add_argument(
        "--start",
        dest="auto_start",
        action="store_true",
        default=False,
        help="Begin extraction automatically on launch.",
    )
    parser.add_argument("--no-start", dest="auto_start", action="store_false")
    parser.add_argument(
        "--end",
        dest="auto_end",
        action="store_true",
        default=False,
        help="Close the window automatically after extraction completes.",
    )
    parser.add_argument("--no-end", dest="auto_end", action="store_false")
    parser.add_argument(
        "--clear-logs",
        dest="clear_logs",
        action="store_true",
        default=False,
        help="Display only: driver-owned log-clearing option.",
    )
    parser.add_argument("--no-clear-logs", dest="clear_logs", action="store_false")
    parser.add_argument(
        "--parallel-run",
        dest="parallel_run",
        action="store_true",
        default=False,
        help="Display only: driver-owned parallel-run option.",
    )
    parser.add_argument("--no-parallel-run", dest="parallel_run", action="store_false")
    parser.add_argument(
        "directory",
        nargs="?",
        default=None,
        help="Target directory containing ASX files.",
    )
    ns = parser.parse_args(argv)
    args = ASXExtractorArgs(
        directory=ns.directory,
        mode=ns.mode,
        auto_start=ns.auto_start,
        auto_end=ns.auto_end,
        clear_logs=ns.clear_logs,
        parallel_run=ns.parallel_run,
    )
    errors = validate_args(args)
    if errors:
        for error in errors:
            print(f"ASX Playlist Extractor: {error}", file=sys.stderr)
        raise SystemExit(1)
    return args
