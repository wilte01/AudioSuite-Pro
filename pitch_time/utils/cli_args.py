"""cli_args.py — launcher argument parsing for the Pitch / Time tool.

Master Driver handshake layout::

    argv[1]                   - folder holding the files
    --rate <factor>           - tempo mode
    --semitones <number>      - pitch mode
    named flags:              --live|--dry, --start|--no-start, --end|--no-end,
    display-only:             --clear-logs|--no-clear-logs,
                              --parallel-run|--no-parallel-run

Changed in 2.7.0: new module (PLAN_2026-11-03_2.7.0_feature_wave_3.md F-S4).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, validate_folder_path
from audio_suite_shared.cli_helpers import (
    apply_str_options,
    parse_driver_handshake,
    print_tool_usage_error,
    scan_value_options,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)

ACCEPTED_HANDSHAKE = frozenset(
    {
        "--live",
        "--dry",
        "--start",
        "--no-start",
        "--end",
        "--no-end",
        "--clear-logs",
        "--no-clear-logs",
        "--parallel-run",
        "--no-parallel-run",
    }
)

#: Named options that consume the token following them.
_VALUE_OPTIONS: dict[str, str] = {
    "--rate": "rate",
    "--semitones": "semitones",
}


@dataclass
class PitchTimeArgs(BaseCLIArgs):
    """Parsed Pitch / Time launcher arguments."""

    rate: str = ""
    semitones: str = ""
    clear_logs: bool = False
    parallel_run: bool = False


def _number(flag: str, value: str) -> float:
    """Return a numeric option as a float, refusing a non-number.

    Args:
        flag: The option's spelling, for the message.
        value: Its value as parsed from the launcher, empty when unset.

    Returns:
        The value as a float.

    Raises:
        SystemExit: With code 1 when the value is not a finite number.
    """
    if not value:
        return 0.0
    try:
        number = float(value)
    except ValueError:
        number = float("nan")
    if number != number:  # NaN: the one value that is not equal to itself.
        print_tool_usage_error(
            "Pitch / Time", f"{flag} must be a number, got {value!r}"
        )
        raise SystemExit(1) from None
    return number


def parse(argv: list[str] | None = None) -> PitchTimeArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`PitchTimeArgs` instance.

    Raises:
        SystemExit: With code 1 when the folder path is invalid or a value is
            not a number.
    """
    if argv is None:
        argv = sys.argv
    args = PitchTimeArgs()
    if len(argv) < 2:
        return args
    args.apply_handshake(parse_driver_handshake(argv, _VALUE_OPTIONS))
    tail = argv[1:]
    values, _ = scan_value_options(tail, _VALUE_OPTIONS)
    apply_str_options(args, values, _VALUE_OPTIONS)
    if args.rate:
        _number("--rate", args.rate)
    if args.semitones:
        _number("--semitones", args.semitones)
    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("Pitch / Time", error)
        raise SystemExit(1)
    return args
