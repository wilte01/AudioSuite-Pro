"""cli_args.py — Launcher argument parsing for the Restoration (declip) tool.

The Master Driver appends this tool's two options after the shared positional
block, so the parser reads the fixed slots and then the option pairs:

    argv[0]  - program name
    argv[1]  - music directory
    argv[2]  - '--live' | '--dry'
    argv[3]  - '--start' | '--no-start'
    argv[4]  - '--end'   | '--no-end'
    argv[5+] - '--threshold' <float>, '--max-run-ms' <int>, and the display-only
               --clear-logs/--parallel-run pair

The option spellings are the click command's own (``restoration/cli.py``), so a
user reading ``audiosuite declip --help`` sees the same names the driver emits.

Changed in 2.3.0: new declip tool (backlog F-08a): peak reconstruction over the shared
in-place workflow.
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

from ..core.declipper import DEFAULT_MAX_RUN_MS, DEFAULT_THRESHOLD

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

_DRIVER_MODE_TOKENS = frozenset({"--live", "--dry"})


@dataclass
class RestorationArgs(BaseCLIArgs):
    """Parsed Restoration launcher arguments."""

    threshold: float = DEFAULT_THRESHOLD
    run_ms: int = DEFAULT_MAX_RUN_MS
    clear_logs: bool = False
    parallel_run: bool = False


def looks_like_driver_argv(argv: list[str] | None = None) -> bool:
    """Return whether *argv* carries the Master Driver's handshake layout.

    Args:
        argv: Full argument vector; defaults to ``sys.argv``.

    Returns:
        True when the argv has a driver-shaped mode slot.
    """
    if argv is None:
        argv = sys.argv
    return len(argv) > 2 and argv[2] in _DRIVER_MODE_TOKENS


def _read_options(argv: list[str], args: RestorationArgs) -> None:
    """Read this tool's options and the display pair from *argv*.

    Args:
        argv: Full argument vector.
        args: The object whose fields are written.
    """
    index = 5
    while index < len(argv):
        token = argv[index]
        if token in {"--threshold", "--max-run-ms"} and index + 1 < len(argv):
            value = argv[index + 1]
            try:
                if token == "--threshold":
                    args.threshold = float(value)
                else:
                    args.run_ms = int(float(value))
            except ValueError:
                logger.warning("Ignoring non-numeric %s %r", token, value)
            index += 2
            continue
        consume_handshake_token(token, args, accepted=ACCEPTED_HANDSHAKE)
        index += 1


def parse(argv: list[str] | None = None) -> RestorationArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        The parsed arguments.

    Raises:
        SystemExit: With code 1 when the folder path is not a directory, the
            threshold is outside ``(0.0, 1.0]``, or the run width is below 1 ms.
    """
    if argv is None:
        argv = sys.argv

    args = RestorationArgs()
    if len(argv) < 2:
        return args

    args.folder_path = argv[1]
    read_positional_handshake(argv, args, mode_idx=2, start_idx=3, end_idx=4)
    _read_options(argv, args)

    errors = validate_folder_path(args.folder_path)
    if not 0.0 < args.threshold <= 1.0:
        errors.append(f"--threshold must be in (0.0, 1.0], got {args.threshold}")
    if args.run_ms < 1:
        errors.append(f"--max-run-ms must be >= 1, got {args.run_ms}")
    if errors:
        for error in errors:
            print_tool_usage_error("Restoration", error)
        raise SystemExit(1)

    logger.debug("cli_args parsed: %s", args)
    return args
