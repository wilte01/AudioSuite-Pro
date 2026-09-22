"""
cli_args.py
Command-line argument parsing for Pop & Click Remover.

Uses parse_known_args() so that any extra arguments injected by GUI
launchers or test harnesses are silently discarded rather than causing
an error.  Explicit validation of the folder path and numeric ranges is
applied after parsing so that helpful error messages are shown early,
before any audio processing begins.
"""

from __future__ import annotations

import argparse

from audio_suite_shared.cli_dataclasses import validate_folder_path
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)


def parse() -> argparse.Namespace:
    """
    Parse and validate command-line arguments.

    Returns a Namespace with attributes:
        folder_path : str | None
        live_mode   : bool   (True → Live Update, False → Dry Run)
        auto_start  : bool
        auto_end    : bool
        sensitivity : float  (0.01 – 0.40)
        width       : int    (>= 1, milliseconds)
        clear_logs  : bool   (display-only, Master Driver handshake)
        parallel_run: bool   (display-only, Master Driver handshake)
    """
    parser = argparse.ArgumentParser(
        description="Pop & Click Remover — remove clicks and pops from audio files.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  app.py /music/albums --live --start --end\n"
            "  app.py /music/albums --sensitivity 0.05 --width 3\n"
        ),
    )

    parser.add_argument(
        "folder_path",
        nargs="?",
        default=None,
        help="Path to the directory containing audio files to process.",
    )

    # Execution mode
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--live",
        action="store_true",
        dest="live_mode",
        help="Live Update mode: write repaired files back to disk.",
    )
    mode_group.add_argument(
        "--dry",
        action="store_false",
        dest="live_mode",
        help="Dry Run mode: detect clicks but do not modify files (default).",
    )
    parser.set_defaults(live_mode=False)

    # Automation flags
    parser.add_argument(
        "--start",
        action="store_true",
        dest="auto_start",
        default=False,
        help="Automatically begin processing after the GUI launches.",
    )
    parser.add_argument(
        "--end",
        action="store_true",
        dest="auto_end",
        default=False,
        help="Automatically close the application when processing completes.",
    )

    # DSP parameters
    parser.add_argument(
        "--sensitivity",
        type=float,
        default=0.31,
        metavar="FLOAT",
        help=(
            "Click detection sensitivity in the range (0.0, 0.40]. "
            "Lower values are more aggressive. Default: 0.31."
        ),
    )
    parser.add_argument(
        "--width",
        type=int,
        default=2,
        metavar="MS",
        help=(
            "Maximum click width to repair, in milliseconds (>= 1). "
            "Defects wider than this are left untouched. Default: 2."
        ),
    )

    # Master Driver display-only handshake flags
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

    # parse_known_args discards any extra args injected by GUI launchers
    args, unknown = parser.parse_known_args()

    # ── Post-parse validation ─────────────────────────────────────────────────
    errors: list[str] = []

    if args.folder_path:
        errors.extend(validate_folder_path(args.folder_path))
    if not (0.0 < args.sensitivity <= 0.40):
        errors.append(
            f"--sensitivity must be in the range (0.0, 0.40], got {args.sensitivity}"
        )
    if args.width < 1:
        errors.append(f"--width must be >= 1 ms, got {args.width}")

    if errors:
        parser.error("\n".join(errors))

    return args
