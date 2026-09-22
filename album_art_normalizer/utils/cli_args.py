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
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, validate_folder_path


@dataclass
class AlbumArtNormalizerArgs(BaseCLIArgs):
    """CLI arguments for Album Art Normalizer."""

    clear_logs: bool = False  # Display only — driver-owned orchestration flag
    parallel_run: bool = False  # Display only — driver-owned orchestration flag


def was_launched_from_driver(argv: list[str] | None = None) -> bool:
    """Detect whether this tool was started by the Master Driver.

    The Master Driver always passes a full handshake argument vector, so any
    argv beyond the program name indicates a driven launch.

    Args:
        argv: Argument vector to inspect; defaults to ``sys.argv``.

    Returns:
        True when extra arguments are present.
    """
    if argv is None:
        argv = sys.argv
    return len(argv) > 1


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

    i = 2
    while i < len(argv):
        arg = argv[i]
        if arg == "--start":
            args.auto_start = True
            i += 1
        elif arg == "--no-start":
            args.auto_start = False
            i += 1
        elif arg == "--end":
            args.auto_end = True
            i += 1
        elif arg == "--no-end":
            args.auto_end = False
            i += 1
        elif arg == "--dry":
            args.live_mode = False
            i += 1
        elif arg == "--live":
            args.live_mode = True
            i += 1
        elif arg == "--clear-logs":
            args.clear_logs = True
            i += 1
        elif arg == "--no-clear-logs":
            args.clear_logs = False
            i += 1
        elif arg == "--parallel-run":
            args.parallel_run = True
            i += 1
        elif arg == "--no-parallel-run":
            args.parallel_run = False
            i += 1
        else:
            i += 1

    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print(f"Album Art Normalizer: {error}", file=sys.stderr)
        raise SystemExit(1)

    return args
