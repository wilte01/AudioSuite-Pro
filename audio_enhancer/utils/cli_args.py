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
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass


@dataclass
class CliArgs:
    """CLI arguments for Audio Enhancer."""

    source: str = ""
    output: str = ""
    preset: str = "Moderate"
    auto_start: bool = False
    auto_end: bool = False


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
    parser.add_argument(
        "--auto-start",
        action="store_true",
        help="Begin processing automatically after launch.",
    )
    parser.add_argument(
        "--auto-end",
        action="store_true",
        help="Close the application automatically when processing completes.",
    )

    args = parser.parse_args()
    return CliArgs(
        source=args.source,
        output=args.output,
        preset=args.preset,
        auto_start=args.auto_start,
        auto_end=args.auto_end,
    )
