"""cli_args.py — Launcher argument parsing for the Duplicate Finder.

The Master Driver's argv layout is the shared positional one every folder tool
reads, with this tool's two options appended after the positional block:

    argv[0]  - program name
    argv[1]  - music directory (scanned recursively)
    argv[2]  - '--live' | '--dry'
    argv[3]  - '--start' | '--no-start'
    argv[4]  - '--end'   | '--no-end'
    argv[5+] - '--threshold' <float>, '--quarantine-dir' <path>, and the
               display-only --clear-logs/--parallel-run pair

The slots match the argument list ``master_driver.runner.arg_builder`` emits for
this utility (``[path, mode, start, end, --threshold, value]``).  Reading fixed
slots rather than scanning tokens is what makes a shifted argv fail like its
peers instead of being silently read as "no mode passed".

Changed in 2.3.0: new duplicate-detection tool (backlog F-02): fingerprint distance,
clustering, cache and quarantine.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, validate_folder_path
from audio_suite_shared.cli_helpers import (
    consume_handshake_token,
    print_tool_usage_error,
    read_positional_handshake,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)

from ..core.models import DEFAULT_THRESHOLD

logger = logging.getLogger(__name__)

#: Display-only flags the driver appends after the option block.
ACCEPTED_HANDSHAKE = frozenset(
    {
        "--clear-logs",
        "--no-clear-logs",
        "--parallel-run",
        "--no-parallel-run",
    }
)

#: The tokens the driver puts in the mode slot; its argv always carries one,
#: which is what lets the window tell a handshake from any other argv.
_DRIVER_MODE_TOKENS = frozenset({"--live", "--dry"})


@dataclass
class DuplicateFinderArgs(BaseCLIArgs):
    """Parsed Duplicate Finder launcher arguments."""

    threshold: float = DEFAULT_THRESHOLD
    quarantine_dir: str = ""
    clear_logs: bool = False
    parallel_run: bool = False


def looks_like_driver_argv(argv: list[str] | None = None) -> bool:
    """Return whether *argv* carries the Master Driver's handshake layout.

    ``parse`` validates the folder it is handed and exits 1 when it is not a
    directory, which is right for a handshake and wrong for any other argv the
    process may see.

    Args:
        argv: Full argument vector; defaults to ``sys.argv``.

    Returns:
        True when the argv has a driver-shaped mode slot.
    """
    if argv is None:
        argv = sys.argv
    return len(argv) > 2 and argv[2] in _DRIVER_MODE_TOKENS


def _read_options(argv: list[str], args: DuplicateFinderArgs) -> None:
    """Read this tool's two options and the display pair from *argv*.

    Args:
        argv: Full argument vector.
        args: The object whose fields are written.
    """
    index = 5
    while index < len(argv):
        token = argv[index]
        if token in {"--threshold", "--quarantine-dir"} and index + 1 < len(argv):
            value = argv[index + 1]
            if token == "--threshold":
                try:
                    args.threshold = float(value)
                except ValueError:
                    logger.warning("Ignoring non-numeric --threshold %r", value)
            else:
                args.quarantine_dir = value
            index += 2
            continue
        consume_handshake_token(token, args, accepted=ACCEPTED_HANDSHAKE)
        index += 1


def parse(argv: list[str] | None = None) -> DuplicateFinderArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        The parsed arguments.

    Raises:
        SystemExit: With code 1 when the folder path is not a directory or the
            threshold is outside ``(0.0, 1.0]``.
    """
    if argv is None:
        argv = sys.argv

    args = DuplicateFinderArgs()
    if len(argv) < 2:
        return args

    args.folder_path = argv[1]
    read_positional_handshake(argv, args, mode_idx=2, start_idx=3, end_idx=4)
    _read_options(argv, args)

    errors = validate_folder_path(args.folder_path)
    if not 0.0 < args.threshold <= 1.0:
        errors.append(f"--threshold must be in (0.0, 1.0], got {args.threshold}")
    if errors:
        for error in errors:
            print_tool_usage_error("Duplicate Finder", error)
        raise SystemExit(1)

    logger.debug("cli_args parsed: %s", args)
    return args
