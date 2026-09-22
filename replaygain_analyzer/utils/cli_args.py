"""
cli_args.py
CLI argument parser for ReplayGain Analyzer with validation.

Master Driver handshake layout (unique: argv[2] carries target LUFS):
    argv[1]  - folder path
    argv[2]  - target LUFS (float, e.g. -16.0)
    argv[3]  - '--live' | '--dry'
    argv[4]  - '--start' | '--no-start'
    argv[5]  - '--end'   | '--no-end'
    argv[6]  - '--clear-logs' | '--no-clear-logs'   (display only)
    argv[7]  - '--parallel-run' | '--no-parallel-run' (display only)

    Standalone-only flag (never sent by the driver):
    any argv position  - '--apply-gain' | '--no-apply-gain'
"""

import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import (
    BaseCLIArgs,
    validate_folder_path,
    validate_target_lufs,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)


@dataclass
class ReplayGainArgs(BaseCLIArgs):
    """CLI arguments specific to the ReplayGain Analyzer tool."""

    target_lufs: float = -16.0
    clear_logs: bool = False
    parallel_run: bool = False
    apply_lossless_gain: bool = False


def validate_args(args: ReplayGainArgs) -> list[str]:
    """
    Validate CLI arguments and return a list of error messages.

    Args:
        args: Parsed ReplayGainArgs dataclass instance.

    Returns:
        List of validation error strings; empty list if all valid.
    """
    errors: list[str] = []
    errors.extend(validate_folder_path(args.folder_path))
    errors.extend(validate_target_lufs(args.target_lufs))
    return errors


def parse(argv: list[str] | None = None) -> ReplayGainArgs:
    """
    Parse command-line arguments into a ReplayGainArgs dataclass.

    Args:
        argv: Argument vector (defaults to sys.argv when None).

    Returns:
        Populated ReplayGainArgs instance.

    Raises:
        SystemExit: If validation errors are found (exit code 1).
    """
    if argv is None:
        argv = sys.argv

    args = ReplayGainArgs()
    if len(argv) < 2:
        return args

    args.folder_path = argv[1]

    if len(argv) > 2:
        try:
            args.target_lufs = float(argv[2])
        except ValueError:
            pass

    if len(argv) > 3:
        args.live_mode = argv[3] == "--live"

    if len(argv) > 4:
        args.auto_start = argv[4] == "--start"

    if len(argv) > 5:
        args.auto_end = argv[5] == "--end"

    # Display-only driver orchestration state (controls stay inert).
    if len(argv) > 6:
        args.clear_logs = argv[6] == "--clear-logs"

    if len(argv) > 7:
        args.parallel_run = argv[7] == "--parallel-run"

    # Standalone-only flag: when the last occurrence of --apply-gain /
    # --no-apply-gain is --apply-gain, bake the track gain into MP3
    # files losslessly after tagging.
    for token in argv:
        if token == "--apply-gain":
            args.apply_lossless_gain = True
        elif token == "--no-apply-gain":
            args.apply_lossless_gain = False

    errors = validate_args(args)
    if errors:
        for error in errors:
            print(f"ReplayGain Analyzer: {error}", file=sys.stderr)
        raise SystemExit(1)

    return args
