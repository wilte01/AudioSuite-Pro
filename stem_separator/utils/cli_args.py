"""
cli_args.py
Command-line argument parsing for the Stem Separator GUI.

Uses ``parse_known_args()`` so that extra arguments injected by GUI launchers
or test harnesses are silently discarded.

Changed in 2.0.0: initial version (Sprint 6, Item 6.1).
"""

from __future__ import annotations

import argparse

from audio_suite_shared.cli_dataclasses import validate_folder_path
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)
from stem_separator.core.models import DEFAULT_MODEL, MODEL_CHOICES, STEM_NAMES


def _stems(value: str) -> tuple[str, ...]:
    """Split a comma-separated stem list, validating each name."""
    names = tuple(part.strip().lower() for part in value.split(",") if part.strip())
    unknown = [name for name in names if name not in STEM_NAMES]
    if unknown or not names:
        raise argparse.ArgumentTypeError(
            f"choose one or more of {', '.join(STEM_NAMES)}; got {value!r}"
        )
    return names


def parse() -> argparse.Namespace:
    """Parse and validate command-line arguments.

    Returns:
        A Namespace with attributes ``folder_path``, ``live_mode``,
        ``auto_start``, ``auto_end``, ``output_dir``, ``model``, ``stems``,
        ``mix``, ``device``, ``clear_logs`` and ``parallel_run``.

    Raises:
        SystemExit: A value or the folder path is invalid.
    """
    parser = argparse.ArgumentParser(
        description="Stem Separator — split tracks into vocals, drums, bass and other.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "folder_path",
        nargs="?",
        default=None,
        help="Path to the directory containing audio files.",
    )

    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--live",
        action="store_true",
        dest="live_mode",
        help="Live Update: write the separated stems to the output directory.",
    )
    mode_group.add_argument(
        "--dry",
        action="store_false",
        dest="live_mode",
        help="Dry Run: report the stems that would be written (default).",
    )
    parser.set_defaults(live_mode=False)

    parser.add_argument(
        "--start",
        action="store_true",
        dest="auto_start",
        default=False,
        help="Begin processing after the GUI launches.",
    )
    parser.add_argument(
        "--end",
        action="store_true",
        dest="auto_end",
        default=False,
        help="Close when processing completes.",
    )

    parser.add_argument(
        "--output-dir",
        dest="output_dir",
        default="",
        help="Directory the per-track stem folders are written into.",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        choices=list(MODEL_CHOICES),
        help=f"Demucs model. Default: {DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--stems",
        type=_stems,
        default=STEM_NAMES,
        metavar="LIST",
        help=f"Comma-separated stems to export. Default: {','.join(STEM_NAMES)}.",
    )
    parser.add_argument(
        "--mix",
        action="store_true",
        dest="mix",
        default=False,
        help="Also write mix.wav: the sum of the exported stems.",
    )
    parser.add_argument(
        "--device",
        default="auto",
        choices=["auto", "cpu", "cuda"],
        help="Compute device. Default: auto (CUDA when usable).",
    )

    # Master Driver handshake flags
    parser.add_argument(
        "--clear-logs",
        action="store_true",
        dest="clear_logs",
        default=False,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-clear-logs",
        action="store_false",
        dest="clear_logs",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--parallel-run",
        action="store_true",
        dest="parallel_run",
        default=False,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--no-parallel-run",
        action="store_false",
        dest="parallel_run",
        help=argparse.SUPPRESS,
    )

    args, _unknown = parser.parse_known_args()

    errors: list[str] = []
    if args.folder_path:
        errors.extend(validate_folder_path(args.folder_path))
    if errors:
        parser.error("\n".join(errors))

    return args
