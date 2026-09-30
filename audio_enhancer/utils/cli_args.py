"""
utils/cli_args.py
Command-line argument parser for Audio Enhancer.

Allows the application to be launched with pre-filled settings, which is
useful for integration with suite launchers or batch scripts.

Usage examples
--------------
    python main.py
    python main.py --source "D:/Music/Albums"
    python main.py --source "D:/Music" --preset aggressive --auto-start
    python main.py --source "D:/Music" --output "D:/Enhanced" --preset mild
    python main.py --source "D:/Music" --output "D:/Enhanced" --live
    python main.py --source "D:/Music" --dry --start --no-end

The Master Driver handshake uses ``--live``/``--dry`` (whether output is
written), ``--start``/``--no-start`` and ``--end``/``--no-end`` (auto
start/end), plus the display-only ``--clear-logs``/``--no-clear-logs`` and
``--parallel-run``/``--no-parallel-run`` flags.  The legacy ``--auto-start``
and ``--auto-end`` spellings remain supported for backward compatibility.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass(frozen=True)
class CliArgs:
    """CLI arguments for Audio Enhancer."""

    source: str = ""
    output: str = ""
    preset: str = "Moderate"
    auto_start: bool = False
    auto_end: bool = False
    live_mode: bool | None = None
    clear_logs: bool = False
    parallel_run: bool = False


_VALID_PRESETS: tuple[str, ...] = ("Mild", "Moderate", "Aggressive")


def _normalize_preset(value: str) -> str:
    """Normalize a user-supplied --preset value to its canonical case.

    Accepts any case (e.g. "moderate", "MODERATE", "Moderate") so the
    documented usage examples in this module's docstring and in
    main.py's docstring work as written. Returns the value unchanged
    (not title-cased) if it doesn't match a known preset case-insensitively,
    so argparse's own ``choices`` check still reports the original input
    in its error message.

    Args:
        value: The raw string passed after --preset on the command line.

    Returns:
        The canonically-cased preset name if a case-insensitive match is
        found, otherwise the original value unchanged.
    """
    for canonical in _VALID_PRESETS:
        if value.lower() == canonical.lower():
            return canonical
    return value


def parse() -> CliArgs:
    """Parse sys.argv and return a CliArgs instance."""
    parser = argparse.ArgumentParser(
        description=(
            "Audio Enhancer — improve dynamic range and clarity of music files."
        ),
        add_help=True,
    )
    parser.add_argument(
        "--source",
        default="",
        metavar="PATH",
        help="Audio file or folder to process.",
    )
    parser.add_argument(
        "--output",
        default="",
        metavar="PATH",
        help="Output folder (default: 'enhanced' subfolder next to source).",
    )
    parser.add_argument(
        "--preset",
        default="Moderate",
        type=_normalize_preset,
        choices=["Mild", "Moderate", "Aggressive"],
        help="Enhancement preset (default: Moderate). Case-insensitive.",
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--live",
        dest="live_mode",
        action="store_true",
        default=None,
        help="Write enhanced output (default when neither flag is passed).",
    )
    mode_group.add_argument(
        "--dry",
        dest="live_mode",
        action="store_false",
        default=None,
        help="Analyse only — compute gains but write no files.",
    )
    start_group = parser.add_mutually_exclusive_group()
    start_group.add_argument(
        "--auto-start",
        "--start",
        dest="auto_start",
        action="store_true",
        default=False,
        help="Begin processing automatically after launch.",
    )
    start_group.add_argument(
        "--no-start",
        dest="auto_start",
        action="store_false",
        default=False,
        help="Do not begin processing automatically after launch.",
    )
    end_group = parser.add_mutually_exclusive_group()
    end_group.add_argument(
        "--auto-end",
        "--end",
        dest="auto_end",
        action="store_true",
        default=False,
        help="Close the application automatically when processing completes.",
    )
    end_group.add_argument(
        "--no-end",
        dest="auto_end",
        action="store_false",
        default=False,
        help="Keep the application open when processing completes.",
    )
    parser.add_argument(
        "--clear-logs",
        action=argparse.BooleanOptionalAction,
        dest="clear_logs",
        default=False,
        help="Mirror of the driver's Clear Logs toggle (display only).",
    )
    parser.add_argument(
        "--parallel-run",
        action=argparse.BooleanOptionalAction,
        dest="parallel_run",
        default=False,
        help="Mirror of the driver's Parallel toggle (display only).",
    )

    args = parser.parse_args()
    return CliArgs(
        source=args.source,
        output=args.output,
        preset=args.preset,
        auto_start=args.auto_start,
        auto_end=args.auto_end,
        live_mode=args.live_mode,
        clear_logs=args.clear_logs,
        parallel_run=args.parallel_run,
    )
