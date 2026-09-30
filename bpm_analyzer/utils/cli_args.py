"""
cli_args.py
Parses sys.argv for BPM Analyzer and returns a plain dataclass.
No tkinter imports — pure argument extraction.
"""

from __future__ import annotations

import logging
import sys
from typing import Optional

from audio_suite_shared.cli_dataclasses import BPMArgs, validate_folder_path
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


def parse(argv: Optional[list[str]] = None) -> BPMArgs:
    """
    Parse command-line arguments for BPM Analyzer.

    Expected positional/flag layout (matches Master Driver handshake):
        argv[1]  – folder path
        argv[3]  – '--live' | '--dry'
        argv[4]  – '--start' | '--no-start'
        argv[5]  – '--end'   | '--no-end'
        argv[6+] – named pairs (--bpm-min N, --bpm-max N, --duration N,
                   --workers N, --parallel/--no-parallel worker flag) plus
                   display-only flags: --clear-logs/--no-clear-logs,
                   --parallel-run/--no-parallel-run

    Args:
        argv: Argument list to parse. Defaults to sys.argv when None.

    Returns:
        Populated BPMArgs dataclass.

    Raises:
        SystemExit: If the folder path is provided but does not exist.
    """
    if argv is None:
        argv = sys.argv

    args = BPMArgs()
    if len(argv) < 2:
        return args

    args.folder_path = argv[1]

    read_positional_handshake(argv, args, mode_idx=3, start_idx=4, end_idx=5)

    # Named option pairs from position 6 onwards.
    i = 6
    while i < len(argv):
        token = argv[i]
        if token in (
            "--bpm-min",
            "--bpm-max",
            "--duration",
            "--workers",
        ) and i + 1 < len(argv):
            raw_value = argv[i + 1]
            try:
                value: int = int(raw_value)
                if token == "--bpm-min":
                    args.bpm_min = value
                elif token == "--bpm-max":
                    args.bpm_max = value
                elif token == "--duration":
                    args.duration = value
                elif token == "--workers":
                    args.max_workers = value
            except ValueError:
                logger.warning(
                    "cli_args: invalid integer value '%s' for flag '%s' - ignored",
                    raw_value,
                    token,
                )
            i += 2
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
            print_tool_usage_error("BPM Analyzer", error)
        raise SystemExit(1)

    logger.debug("cli_args parsed: %s", args)
    return args
