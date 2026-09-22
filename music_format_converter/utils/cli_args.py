"""
cli_args.py — CLI argument parser for Music Format Converter.

Positional + named-flag layout:
    argv[1]           - input folder path
    argv[2]           - output format (e.g. 'mp3', '.flac')
    --start           - auto-start processing
    --end/--no-end    - auto-end
    --dry / --live    - run mode
    --quality VALUE   - 'highest' | 'high' | 'medium' | 'low'
    --sample-rate VALUE - 'source' | '44100' | '48000' | ... | '192000'
    --bit-depth VALUE - 'auto' | '16' | '24' | '32' | 'float'
    --delete-originals
    --output-dir PATH
    --normalize-mp3            - losslessly adjust MP3 output to target LUFS
    --target-lufs VALUE        - target loudness (default -16.0)
    display-only flags: --clear-logs|--no-clear-logs,
                        --parallel-run|--no-parallel-run

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.
"""

import os
import sys
from dataclasses import dataclass
from typing import Optional

from audio_suite_shared.cli_dataclasses import BaseCLIArgs

from ..core.ffmpeg_params import BIT_DEPTH_PRESETS, SAMPLE_RATE_PRESETS


@dataclass
class ConverterArgs(BaseCLIArgs):
    """CLI arguments for Music Format Converter."""

    output_format: Optional[str] = None
    quality: Optional[str] = None
    sample_rate: Optional[str] = None
    bit_depth: Optional[str] = None
    delete_originals: bool = False
    output_dir: Optional[str] = None
    normalize_mp3: bool = False
    target_lufs: float = -16.0
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


def validate_args(args: ConverterArgs) -> list[str]:
    """Validate CLI arguments and return list of errors."""
    errors = []
    if args.folder_path:
        if not os.path.exists(args.folder_path):
            errors.append(f"Folder path does not exist: {args.folder_path}")
        elif not os.path.isdir(args.folder_path):
            errors.append(f"Path is not a directory: {args.folder_path}")
    if args.output_format:
        from music_format_converter.core.formats import ALL_FORMATS

        if args.output_format not in ALL_FORMATS:
            errors.append(
                f"Invalid output format: {args.output_format}. "
                f"Valid formats: {', '.join(ALL_FORMATS)}"
            )
    if args.quality and args.quality not in ("highest", "high", "medium", "low"):
        errors.append(f"Invalid quality: {args.quality}.")
    if args.sample_rate and args.sample_rate not in SAMPLE_RATE_PRESETS:
        errors.append(
            f"Invalid sample rate: {args.sample_rate}. "
            f"Valid: {', '.join(SAMPLE_RATE_PRESETS)}"
        )
    if args.bit_depth and args.bit_depth not in BIT_DEPTH_PRESETS:
        errors.append(
            f"Invalid bit depth: {args.bit_depth}. "
            f"Valid: {', '.join(BIT_DEPTH_PRESETS)}"
        )
    if args.output_dir:
        if not os.path.exists(args.output_dir):
            errors.append(f"Output directory does not exist: {args.output_dir}")
        elif not os.path.isdir(args.output_dir):
            errors.append(f"Output path is not a directory: {args.output_dir}")
    return errors


def parse(argv: list[str] | None = None) -> ConverterArgs:
    if argv is None:
        argv = sys.argv
    args = ConverterArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    i = 2
    if len(argv) > 2 and not argv[2].startswith("-"):
        # Positional output-format slot: only occupies argv[2] when it's
        # not itself a flag, so a flag in this position (e.g. no format
        # given) still reaches the flag-parsing loop below.
        fmt = argv[2].lower().replace(".", "")
        from music_format_converter.core.formats import ALL_FORMATS

        if fmt in ALL_FORMATS:
            args.output_format = fmt
        i = 3
    while i < len(argv):
        arg = argv[i]
        if arg == "--start":
            args.auto_start = True
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
        elif arg == "--quality" and i + 1 < len(argv):
            q = argv[i + 1].lower()
            if q in ("highest", "high", "medium", "low"):
                args.quality = q
            i += 2
        elif arg == "--sample-rate" and i + 1 < len(argv):
            sr = argv[i + 1].lower()
            if sr in SAMPLE_RATE_PRESETS:
                args.sample_rate = sr
            i += 2
        elif arg == "--bit-depth" and i + 1 < len(argv):
            bd = argv[i + 1].lower()
            if bd in BIT_DEPTH_PRESETS:
                args.bit_depth = bd
            i += 2
        elif arg == "--delete-originals":
            args.delete_originals = True
            i += 1
        elif arg == "--output-dir" and i + 1 < len(argv):
            args.output_dir = argv[i + 1]
            i += 2
        elif arg == "--normalize-mp3":
            args.normalize_mp3 = True
            i += 1
        elif arg == "--target-lufs" and i + 1 < len(argv):
            try:
                args.target_lufs = float(argv[i + 1])
            except ValueError:
                pass
            i += 2
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
            print(f"Music Format Converter: {error}", file=sys.stderr)
        raise SystemExit(1)
    return args
