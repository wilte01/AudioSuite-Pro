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

logger = logging.getLogger(__name__)


def was_launched_from_driver(argv: Optional[list[str]] = None) -> bool:
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

    if len(argv) > 3:
        args.live_mode = argv[3] == "--live"

    if len(argv) > 4:
        args.auto_start = argv[4] == "--start"

    if len(argv) > 5:
        args.auto_end = argv[5] == "--end"

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
                        "cli_args: invalid float value '%s' for flag '%s' — ignored",
                        raw_value,
                        token,
                    )
            elif token == "--workers":
                try:
                    args.max_workers = int(raw_value)
                except ValueError:
                    logger.warning(
                        "cli_args: invalid integer value '%s' for flag '%s' — ignored",
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
        elif token == "--clear-logs":
            args.clear_logs = True
            i += 1
        elif token == "--no-clear-logs":
            args.clear_logs = False
            i += 1
        elif token == "--parallel-run":
            args.parallel_run = True
            i += 1
        elif token == "--no-parallel-run":
            args.parallel_run = False
            i += 1
        else:
            i += 1

    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print(f"Lyrics Manager: {error}", file=sys.stderr)
        raise SystemExit(1)

    logger.debug("cli_args parsed: %s", args)
    return args
