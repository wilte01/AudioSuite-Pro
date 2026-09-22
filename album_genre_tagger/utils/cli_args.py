"""
cli_args.py — CLI argument parser for Album Genre Tagger.

Master Driver handshake layout:
    argv[1]  - folder path
    argv[2]  - '--live' | '--dry'
    argv[3]  - '--start' | '--no-start'
    argv[4]  - '--end' | '--no-end'
    argv[5+] - named pairs (--coverage N) and display-only flags
               (--clear-logs/--no-clear-logs, --parallel-run/--no-parallel-run)

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.
"""

import logging
import os
import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs

logger = logging.getLogger(__name__)


@dataclass
class GenreTaggerArgs(BaseCLIArgs):
    """CLI arguments for Album Genre Tagger."""

    min_coverage: int = 50
    clear_logs: bool = False
    parallel_run: bool = False


def was_launched_from_driver(argv: list[str] | None = None) -> bool:
    """
    Return True when this process was started by the Master Driver.

    The driver always launches tools with at least one CLI argument
    (the folder path); a standalone launch of the .pyw passes none.

    Args:
        argv: Argument vector to inspect; defaults to ``sys.argv``.

    Returns:
        True if any CLI arguments beyond the script name are present.
    """
    if argv is None:
        argv = sys.argv
    return len(argv) > 1


def validate_args(args: GenreTaggerArgs) -> list[str]:
    """Validate CLI arguments and return a list of error messages.

    Args:
        args: Parsed CLI arguments to validate.

    Returns:
        A list of human-readable error strings; empty when all values are valid.
    """
    errors: list[str] = []
    if args.folder_path:
        if not os.path.exists(args.folder_path):
            errors.append(f"Folder path does not exist: {args.folder_path}")
        elif not os.path.isdir(args.folder_path):
            errors.append(f"Path is not a directory: {args.folder_path}")
    if args.min_coverage < 0 or args.min_coverage > 100:
        errors.append(f"Coverage must be 0-100%, got: {args.min_coverage}")
    return errors


def parse(argv: list[str] | None = None) -> GenreTaggerArgs:
    """Parse command line arguments for the Album Genre Tagger.

    Reads the fixed positional layout sent by the Master Driver and any
    trailing named pairs, then validates the result.

    Args:
        argv: Argument vector to parse.  Defaults to ``sys.argv`` when ``None``.

    Returns:
        Populated :class:`GenreTaggerArgs` instance.

    Raises:
        SystemExit: If ``argv`` contains invalid or out-of-range values.
    """
    if argv is None:
        argv = sys.argv

    if len(argv) < 2:
        return GenreTaggerArgs()

    folder_path: str = argv[1]
    live_mode: bool = argv[2] == "--live" if len(argv) > 2 else False
    auto_start: bool = argv[3] == "--start" if len(argv) > 3 else False
    auto_end: bool = argv[4] == "--end" if len(argv) > 4 else False
    min_coverage: int = 50
    clear_logs: bool = False
    parallel_run: bool = False

    # Named-pair scan begins at argv[5] — the first index after all positional
    # slots — so that the already-parsed argv[4] (--end/--no-end) is not
    # re-visited.
    i = 5
    while i < len(argv):
        if argv[i] == "--coverage" and i + 1 < len(argv):
            try:
                min_coverage = int(argv[i + 1])
            except ValueError:
                logger.warning(
                    "Invalid --coverage value %r is not an integer; using default %d.",
                    argv[i + 1],
                    50,
                )
            i += 2
        elif argv[i] == "--clear-logs":
            clear_logs = True
            i += 1
        elif argv[i] == "--no-clear-logs":
            clear_logs = False
            i += 1
        elif argv[i] == "--parallel-run":
            parallel_run = True
            i += 1
        elif argv[i] == "--no-parallel-run":
            parallel_run = False
            i += 1
        else:
            i += 1

    args = GenreTaggerArgs(
        folder_path=folder_path,
        live_mode=live_mode,
        auto_start=auto_start,
        auto_end=auto_end,
        min_coverage=min_coverage,
        clear_logs=clear_logs,
        parallel_run=parallel_run,
    )
    errors = validate_args(args)
    if errors:
        for error in errors:
            print(f"Album Genre Tagger: {error}", file=sys.stderr)
        raise SystemExit(1)
    return args
