"""
cli_args.py
Command-line argument parsing for Noise Reduction.

Uses parse_known_args() so that extra arguments injected by GUI
launchers or test harnesses are silently discarded.
"""

from __future__ import annotations

import argparse

from audio_suite_shared.cli_dataclasses import validate_folder_path
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)


def parse() -> argparse.Namespace:
    """Parse and validate command-line arguments.

    Returns a Namespace with attributes:
        folder_path      : str | None
        live_mode        : bool
        auto_start       : bool
        auto_end         : bool
        reduce_hum       : bool
        hum_frequency    : int
        hum_harmonics    : int
        hum_quality      : float
        reduce_broadband : bool
        noise_start_ms   : int
        noise_end_ms     : int
        gate_threshold_db: float
        clear_logs       : bool
        parallel_run     : bool
    """
    parser = argparse.ArgumentParser(
        description="Noise Reduction — remove hum and broadband noise from audio.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "folder_path",
        nargs="?",
        default=None,
        help="Path to the directory containing audio files.",
    )

    # Execution mode
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--live",
        action="store_true",
        dest="live_mode",
        help="Live Update: write reduced files back to disk.",
    )
    mode_group.add_argument(
        "--dry",
        action="store_false",
        dest="live_mode",
        help="Dry Run: analyse only (default).",
    )
    parser.set_defaults(live_mode=False)

    # Automation
    parser.add_argument(
        "--start",
        action="store_true",
        dest="auto_start",
        default=False,
        help="Begin processing after GUI launches.",
    )
    parser.add_argument(
        "--end",
        action="store_true",
        dest="auto_end",
        default=False,
        help="Close when processing completes.",
    )

    # Hum removal
    parser.add_argument(
        "--reduce-hum",
        action="store_true",
        dest="reduce_hum",
        default=False,
        help="Enable hum removal.",
    )
    parser.add_argument(
        "--hum-frequency",
        type=int,
        default=60,
        choices=[50, 60],
        help="Mains frequency (50 or 60 Hz). Default: 60.",
    )
    parser.add_argument(
        "--hum-harmonics",
        type=int,
        default=8,
        metavar="N",
        help="Number of harmonics to filter (1-20). Default: 8.",
    )
    parser.add_argument(
        "--hum-quality",
        type=float,
        default=30.0,
        metavar="Q",
        help="Q factor for notch filters (1.0-100.0). Default: 30.0.",
    )

    # Broadband noise
    parser.add_argument(
        "--reduce-broadband",
        action="store_true",
        dest="reduce_broadband",
        default=False,
        help="Enable broadband noise reduction.",
    )
    parser.add_argument(
        "--noise-start",
        type=int,
        default=0,
        dest="noise_start_ms",
        metavar="MS",
        help="Noise profile start (ms). Default: 0.",
    )
    parser.add_argument(
        "--noise-end",
        type=int,
        default=500,
        dest="noise_end_ms",
        metavar="MS",
        help="Noise profile end (ms). Default: 500.",
    )
    parser.add_argument(
        "--gate-threshold",
        type=float,
        default=3.0,
        dest="gate_threshold_db",
        metavar="DB",
        help="Gate threshold above noise floor (dB). Default: 3.0.",
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

    args, unknown = parser.parse_known_args()

    errors: list[str] = []
    if args.folder_path:
        errors.extend(validate_folder_path(args.folder_path))
    if args.hum_harmonics < 1 or args.hum_harmonics > 20:
        errors.append("--hum-harmonics must be 1-20")
    if not (1.0 <= args.hum_quality <= 100.0):
        errors.append("--hum-quality must be 1.0-100.0")

    if errors:
        parser.error("\n".join(errors))

    return args
