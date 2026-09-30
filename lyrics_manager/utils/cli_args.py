"""
cli_args.py
Parses sys.argv for Lyrics Manager and returns a plain dataclass.
No tkinter imports — pure argument extraction.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from audio_suite_shared.cli_dataclasses import LyricsArgs, validate_folder_path
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


def parse(argv: Optional[list[str]] = None) -> LyricsArgs:
    """
    Parse command-line arguments for Lyrics Manager.

    Expected positional/flag layout (matches Master Driver handshake):
        argv[1]  – folder path
        argv[3]  – '--live' | '--dry'
        argv[4]  – '--start' | '--no-start'
        argv[5]  – '--end'   | '--no-end'
        argv[6+] – named pairs (--provider NAME, --request-timeout SECS,
                   --workers N), boolean flags (--skip-existing/
                   --no-skip-existing, --plain-fallback/--no-plain-fallback,
                   --parallel/--no-parallel) plus display-only flags:
                   --clear-logs/--no-clear-logs, --parallel-run/--no-parallel-run

    Args:
        argv: Argument list to parse. Defaults to sys.argv when None.

    Returns:
        Populated LyricsArgs dataclass.

    Raises:
        SystemExit: If the folder path is provided but does not exist.
    """
    if argv is None:
        argv = sys.argv

    args = LyricsArgs()
    if len(argv) < 2:
        return args

    args.folder_path = argv[1]

    read_positional_handshake(argv, args, mode_idx=3, start_idx=4, end_idx=5)

    # Named option pairs and flags from position 6 onwards.
    i = 6
    while i < len(argv):
        token = argv[i]
        if token in ("--provider", "--request-timeout", "--workers") and i + 1 < len(
            argv
        ):
            raw_value = argv[i + 1]
            if token == "--provider":
                args.provider = raw_value
            elif token == "--request-timeout":
                try:
                    args.request_timeout = float(raw_value)
                except ValueError:
                    logger.warning(
                        "cli_args: invalid float value '%s' for flag '%s' - ignored",
                        raw_value,
                        token,
                    )
            elif token == "--workers":
                try:
                    args.max_workers = int(raw_value)
                except ValueError:
                    logger.warning(
                        "cli_args: invalid integer value '%s' for flag '%s' - ignored",
                        raw_value,
                        token,
                    )
            i += 2
        elif token == "--skip-existing":
            args.skip_existing = True
            i += 1
        elif token == "--no-skip-existing":
            args.skip_existing = False
            i += 1
        elif token == "--plain-fallback":
            args.plain_fallback = True
            i += 1
        elif token == "--no-plain-fallback":
            args.plain_fallback = False
            i += 1
        elif token == "--parallel":
            args.parallel_mode = True
            i += 1
        elif token == "--no-parallel":
            args.parallel_mode = False
            i += 1
        elif consume_handshake_token(token, args, accepted=ACCEPTED_HANDSHAKE) is True:
            i += 1
        else:
            i += 1

    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("Lyrics Manager", error)
        raise SystemExit(1)

    logger.debug("cli_args parsed: %s", args)
    return args
