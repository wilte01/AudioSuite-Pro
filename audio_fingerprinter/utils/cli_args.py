"""
cli_args.py — CLI argument parser for Audio Fingerprinter.

Positional + named-flag layout heeded by the Master Driver:
    argv[1]               - input folder path
    --lookup/--no-lookup  - enable AcoustID lookup
    --write-tags          - write matched tags after lookup
    --threshold VALUE     - minimum AcoustID match score (0.0-1.0)
    --max-length VALUE    - fpcalc analysis window in seconds
    --fpcalc PATH         - explicit fpcalc binary path
    --api-key KEY         - one-off API key for this run
    --dry / --live        - run mode
    --start               - auto-start processing
    --end/--no-end        - auto-end
    display-only flags: --clear-logs|--no-clear-logs,
                        --parallel-run|--no-parallel-run
"""

import os
import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)

from ..core.models import FingerprintParams


@dataclass
class FingerprintArgs(BaseCLIArgs):
    """CLI arguments for Audio Fingerprinter."""

    lookup_enabled: bool = True
    write_tags: bool = False
    threshold: float = 0.5
    max_length: int = 120
    fpcalc_path: str = ""
    api_key: str = ""
    clear_logs: bool = False  # Display only — driver-owned orchestration flag
    parallel_run: bool = False  # Display only — driver-owned orchestration flag

    def to_params(self) -> FingerprintParams:
        """Build immutable runtime params from these parsed args.

        Returns:
            A ``FingerprintParams`` instance mirroring this args object.
        """
        return FingerprintParams(
            lookup_enabled=self.lookup_enabled,
            write_tags=self.write_tags,
            is_dry_run=not self.live_mode,
            threshold=self.threshold,
            max_length=self.max_length,
            fpcalc_path=self.fpcalc_path,
        )


def validate_args(args: FingerprintArgs) -> list[str]:
    """Validate CLI arguments and return a list of errors."""
    errors: list[str] = []
    if args.folder_path:
        if not os.path.exists(args.folder_path):
            errors.append(f"Folder path does not exist: {args.folder_path}")
        elif not os.path.isdir(args.folder_path):
            errors.append(f"Path is not a directory: {args.folder_path}")
    if args.threshold < 0.0 or args.threshold > 1.0:
        errors.append("Threshold must be between 0.0 and 1.0.")
    if args.max_length < 1 or args.max_length > 600:
        errors.append("Max length must be between 1 and 600 seconds.")
    if args.fpcalc_path and not os.path.isfile(args.fpcalc_path):
        errors.append(f"fpcalc binary does not exist: {args.fpcalc_path}")
    return errors


def parse(argv: list[str] | None = None) -> FingerprintArgs:
    """Parse an argument vector into a ``FingerprintArgs``.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        Parsed arguments.

    Raises:
        SystemExit: With code 1 when validation fails, after printing each
            error to stderr prefixed with the tool name.
    """
    if argv is None:
        argv = sys.argv
    args = FingerprintArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    i = 2
    while i < len(argv):
        arg = argv[i]
        if arg == "--lookup":
            args.lookup_enabled = True
            i += 1
        elif arg == "--no-lookup":
            args.lookup_enabled = False
            i += 1
        elif arg == "--write-tags":
            args.write_tags = True
            i += 1
        elif arg == "--threshold" and i + 1 < len(argv):
            try:
                value = float(argv[i + 1])
                if 0.0 <= value <= 1.0:
                    args.threshold = value
            except ValueError:
                pass
            i += 2
        elif arg == "--max-length" and i + 1 < len(argv):
            try:
                value = int(argv[i + 1])
                if 1 <= value <= 600:
                    args.max_length = value
            except ValueError:
                pass
            i += 2
        elif arg == "--fpcalc" and i + 1 < len(argv):
            args.fpcalc_path = argv[i + 1]
            i += 2
        elif arg == "--api-key" and i + 1 < len(argv):
            args.api_key = argv[i + 1]
            i += 2
        elif arg == "--dry":
            args.live_mode = False
            i += 1
        elif arg == "--live":
            args.live_mode = True
            i += 1
        elif arg == "--start":
            args.auto_start = True
            i += 1
        elif arg == "--end":
            args.auto_end = True
            i += 1
        elif arg == "--no-end":
            args.auto_end = False
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

    errors = validate_args(args)
    if errors:
        for error in errors:
            print(f"Audio Fingerprinter: {error}", file=sys.stderr)
        raise SystemExit(1)
    return args
