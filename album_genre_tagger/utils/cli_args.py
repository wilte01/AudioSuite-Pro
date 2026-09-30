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
from audio_suite_shared.cli_helpers import (
    consume_handshake_token,
    print_tool_usage_error,
    read_positional_handshake,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)

logger = logging.getLogger(__name__)

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


@dataclass
class GenreTaggerArgs(BaseCLIArgs):
    """CLI arguments for Album Genre Tagger."""

    min_coverage: int = 50
    clear_logs: bool = False
    parallel_run: bool = False


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

    # Named-pair scan begins at argv[5] - the first index after all positional
    # slots - so that the already-parsed argv[4] (--end/--no-end) is not
    # re-visited.
    args = GenreTaggerArgs(folder_path=argv[1], min_coverage=50)
    read_positional_handshake(argv, args, mode_idx=2, start_idx=3, end_idx=4)
    i = 5
    while i < len(argv):
        arg = argv[i]
        if consume_handshake_token(arg, args, accepted=ACCEPTED_HANDSHAKE) is True:
            i += 1
        elif arg == "--coverage" and i + 1 < len(argv):
            try:
                args.min_coverage = int(argv[i + 1])
            except ValueError:
                logger.warning(
                    "Invalid --coverage value %r is not an integer; using default %d.",
                    argv[i + 1],
                    50,
                )
            i += 2
        else:
            i += 1

    errors = validate_args(args)
    if errors:
        for error in errors:
            print_tool_usage_error("Album Genre Tagger", error)
        raise SystemExit(1)
    return args
