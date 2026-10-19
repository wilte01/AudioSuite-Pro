"""
cli_args.py — CLI argument parser for Silence Trimmer.

Master Driver handshake layout:
    argv[1]  - folder path
    argv[3]  - '--live' | '--dry'
    argv[4]  - '--start' | '--no-start'
    argv[5]  - '--end' | '--no-end'
    argv[6]  - silence threshold (int dB, e.g. -50)
    argv[7]  - '--fade' | '--no-fade'
    argv[8+] - named pairs: --fade-in <ms>  --fade-out <ms>

Display-only (master driver handshake, not used by tool):
    '--clear-logs' | '--no-clear-logs'
    '--parallel-run' | '--no-parallel-run'

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.

Changed in 1.4.0: ``max_workers`` defaults to ``default_max_workers()``.
"""

import os
import sys
from dataclasses import dataclass, field

from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.cli_helpers import (
    consume_handshake_token,
    print_tool_usage_error,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)
from audio_suite_shared.constants import default_max_workers

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
class SilenceTrimmerArgs(BaseCLIArgs):
    """CLI arguments for Silence Trimmer.

    Attributes:
        threshold: Silence detection threshold in dBFS.
        apply_fade: Whether to apply fade-in/fade-out after trimming.
        fade_in_ms: Fade-in duration in milliseconds, or None to use default.
        fade_out_ms: Fade-out duration in milliseconds, or None to use default.
        clear_logs: Display-only flag for master driver handshake.
        parallel_run: Display-only flag for master driver handshake.
    """

    threshold: int = -50
    apply_fade: bool = False
    fade_in_ms: int | None = None
    fade_out_ms: int | None = None
    parallel_mode: bool = False
    max_workers: int = field(default_factory=default_max_workers)
    clear_logs: bool = False
    parallel_run: bool = False


def validate_args(args: SilenceTrimmerArgs) -> list[str]:
    """Validate CLI arguments and return a list of error messages.

    Args:
        args: Parsed SilenceTrimmerArgs instance to validate.

    Returns:
        List of human-readable error strings; empty if all arguments are valid.
    """
    errors: list[str] = []
    if args.folder_path:
        if not os.path.exists(args.folder_path):
            errors.append(f"Folder path does not exist: {args.folder_path}")
        elif not os.path.isdir(args.folder_path):
            errors.append(f"Path is not a directory: {args.folder_path}")
    if args.threshold < -80 or args.threshold > -20:
        errors.append(f"Silence threshold must be -80 to -20 dB, got: {args.threshold}")
    if args.fade_in_ms is not None and (
        args.fade_in_ms < 100 or args.fade_in_ms > 3000
    ):
        errors.append(f"Fade-in must be 100-3000ms, got: {args.fade_in_ms}")
    if args.fade_out_ms is not None and (
        args.fade_out_ms < 100 or args.fade_out_ms > 5000
    ):
        errors.append(f"Fade-out must be 100-5000ms, got: {args.fade_out_ms}")
    return errors


def parse(argv: list[str] | None = None) -> SilenceTrimmerArgs:
    """Parse command-line arguments into a SilenceTrimmerArgs instance.

    Args:
        argv: Argument list to parse; defaults to sys.argv if None.

    Returns:
        Populated SilenceTrimmerArgs dataclass.

    Raises:
        SystemExit: If validation errors are detected.
    """
    if argv is None:
        argv = sys.argv
    args = SilenceTrimmerArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    i = 2
    while i < len(argv):
        arg = argv[i]
        if consume_handshake_token(arg, args, accepted=ACCEPTED_HANDSHAKE) is True:
            i += 1
        elif arg == "--fade":
            args.apply_fade = True
            i += 1
        elif arg == "--no-fade":
            args.apply_fade = False
            i += 1
        elif arg == "--fade-in" and i + 1 < len(argv):
            try:
                args.fade_in_ms = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--fade-out" and i + 1 < len(argv):
            try:
                args.fade_out_ms = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--workers" and i + 1 < len(argv):
            try:
                args.max_workers = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--parallel":
            args.parallel_mode = True
            i += 1
        elif arg == "--no-parallel":
            args.parallel_mode = False
            i += 1
        elif arg.startswith("-"):
            # Bare positional tokens (e.g. a lone "50" threshold with a
            # leading dash) and any other negative-looking value attempt
            # integer conversion; every handshake-token clash is consumed
            # above, so this branch only sees non-handshake tokens.
            try:
                args.threshold = int(arg)
            except ValueError:
                pass
            i += 1
        else:
            i += 1
    errors = validate_args(args)
    if errors:
        for error in errors:
            print_tool_usage_error("Silence Trimmer", error)
        raise SystemExit(1)
    return args
