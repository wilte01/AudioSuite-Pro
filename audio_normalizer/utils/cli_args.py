"""
cli_args.py — CLI argument parser for Audio Normalizer.

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.
"""

import os
import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, validate_target_lufs

VALID_NORMALIZATION_MODES: tuple[str, ...] = ("normalise", "lossless")


@dataclass
class NormalizerArgs(BaseCLIArgs):
    """CLI arguments for Audio Normalizer."""

    target_lufs: float = -16.0
    tolerance: float = 0.5
    normalization_mode: str = "normalise"


def validate_args(args: NormalizerArgs) -> list[str]:
    """Validate CLI arguments and return list of errors.

    Args:
        args: Parsed NormalizerArgs to validate.

    Returns:
        List of human-readable error strings; empty when all args are valid.
    """
    errors: list[str] = []
    if args.folder_path:
        if not os.path.exists(args.folder_path):
            errors.append(f"Folder path does not exist: {args.folder_path}")
        elif not os.path.isdir(args.folder_path):
            errors.append(f"Path is not a directory: {args.folder_path}")
    errors.extend(validate_target_lufs(args.target_lufs))
    if args.tolerance < 0:
        errors.append(f"Tolerance must be positive, got: {args.tolerance}")
    if args.normalization_mode not in VALID_NORMALIZATION_MODES:
        errors.append(
            "normalization_mode must be one of "
            f"{', '.join(VALID_NORMALIZATION_MODES)}, "
            f"got: {args.normalization_mode}"
        )
    return errors


def parse(argv: list[str] | None = None) -> NormalizerArgs:
    """Parse command-line arguments into a NormalizerArgs instance.

    Args:
        argv: Argument list (defaults to sys.argv).

    Returns:
        Populated NormalizerArgs.

    Raises:
        SystemExit: If any argument fails validation.
    """
    if argv is None:
        argv = sys.argv
    args = NormalizerArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    i = 2
    while i < len(argv):
        arg = argv[i]
        if arg == "--live":
            args.live_mode = True
            i += 1
        elif arg == "--dry":
            args.live_mode = False
            i += 1
        elif arg == "--start":
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
        elif arg == "--tolerance" and i + 1 < len(argv):
            try:
                args.tolerance = float(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--mode" and i + 1 < len(argv):
            args.normalization_mode = argv[i + 1]
            i += 2
        elif arg.startswith("-") and arg not in ["--tolerance", "--mode"]:
            try:
                args.target_lufs = float(arg)
            except ValueError:
                pass
            i += 1
        else:
            i += 1
    errors = validate_args(args)
    if errors:
        for error in errors:
            print(f"Audio Normalizer: {error}", file=sys.stderr)
        raise SystemExit(1)
    return args
