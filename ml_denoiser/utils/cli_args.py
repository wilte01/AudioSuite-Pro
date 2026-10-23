"""
cli_args.py
Command-line argument parsing for the ML Denoiser GUI.

Uses ``parse_known_args()`` so that extra arguments injected by GUI launchers
or test harnesses are silently discarded.

Changed in 2.0.0: initial version (Sprint 6, Item 6.2).
"""

from __future__ import annotations

import argparse

from audio_suite_shared.cli_dataclasses import validate_folder_path
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)


def _percent(value: str) -> float:
    """Parse the driver's ``--amount`` as a 1-100 integer percentage."""
    try:
        percent = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not a number: {value!r}") from exc
    if not (0.0 < percent <= 100.0):
        raise argparse.ArgumentTypeError(f"must be above 0 and at most 100: {value!r}")
    return percent


def parse() -> argparse.Namespace:
    """Parse and validate command-line arguments.

    Returns:
        A Namespace with attributes ``folder_path``, ``live_mode``,
        ``auto_start``, ``auto_end``, ``amount`` (a fraction, 0-1),
        ``clear_logs`` and ``parallel_run``.

    Raises:
        SystemExit: A value or the folder path is invalid.
    """
    parser = argparse.ArgumentParser(
        description="ML Denoiser — neural noise reduction with RNNoise.",
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
        help="Live Update: write denoised files back to disk.",
    )
    mode_group.add_argument(
        "--dry",
        action="store_false",
        dest="live_mode",
        help="Dry Run: measure only (default).",
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
        "--amount",
        type=_percent,
        default=100.0,
        metavar="PERCENT",
        help=(
            "How much of the model's output to keep, 1-100 %%. Lower values "
            "blend the source back in. Default: 100."
        ),
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

    # The GUI stores the amount as a percentage; the params take a fraction.
    args.amount = args.amount / 100.0
    return args
