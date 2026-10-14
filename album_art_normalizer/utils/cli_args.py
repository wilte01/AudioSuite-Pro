"""
cli_args.py — CLI argument parser for Album Art Normalizer.

Parses sys.argv using a manual flag-scan loop.
No tkinter imports — pure argument extraction.

Positional + named-flag layout:
    argv[1]            - folder music directory
    --dry / --live     - run mode
    --start/--no-start - auto-start normalization
    --end/--no-end     - close automatically when done
    display-only flags: --clear-logs|--no-clear-logs,
                        --parallel-run|--no-parallel-run

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.

Changed in 1.0.1: parses and exposes the driver's ``--size`` argument.
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
class AlbumArtNormalizerArgs(BaseCLIArgs):
    """CLI arguments for Album Art Normalizer."""

    size: str = ""  # --size <pixel-dim> from the Master Driver
    clear_logs: bool = False  # Display only — driver-owned orchestration flag
    parallel_run: bool = False  # Display only — driver-owned orchestration flag


def parse(argv: list[str] | None = None) -> AlbumArtNormalizerArgs:
    """Parse command line arguments for the Album Art Normalizer.

    Args:
        argv: Argument list to parse. Defaults to sys.argv when None.

    Returns:
        A populated and validated AlbumArtNormalizerArgs instance.

    Raises:
        SystemExit: If the folder path is provided but does not exist.
    """
    if argv is None:
        argv = sys.argv

    args = AlbumArtNormalizerArgs()
    if len(argv) < 2:
        return args

    args.folder_path = argv[1]

    # Scan for --size <value> before the handshake segment.
    tail = argv[2:]
    index = 0
    while index < len(tail):
        if tail[index] == "--size" and index + 1 < len(tail):
            args.size = tail[index + 1]
            index += 2
            continue
        index += 1

    apply_handshake_segment(tail, args, accepted=ACCEPTED_HANDSHAKE)

    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("Album Art Normalizer", error)
        raise SystemExit(1)

    return args
