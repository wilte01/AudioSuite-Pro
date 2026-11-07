"""cli_args.py — launcher argument parsing for the Audio Joiner.

Master Driver handshake layout::

    argv[1]                   - folder holding the segments (join order source)
    --order a,b,c             - segment names inside that folder, in join order
    --output <path>           - file the join is written to
    --gap-ms <ms>             - silence inserted at every boundary
    --crossfade-ms <ms>       - equal-power overlap at every boundary
    named flags:              --live|--dry, --start|--no-start, --end|--no-end,
                              --copy|--no-copy,
    display-only:             --clear-logs|--no-clear-logs,
                              --parallel-run|--no-parallel-run

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E5).
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
        "--copy",
        "--no-copy",
    }
)

#: Named options that consume the token following them.
_VALUE_OPTIONS: dict[str, str] = {
    "--order": "order",
    "--output": "output",
    "--gap-ms": "gap_ms",
    "--crossfade-ms": "crossfade_ms",
}


@dataclass
class AudioJoinerArgs(BaseCLIArgs):
    """Parsed Audio Joiner launcher arguments."""

    order: str = ""
    output: str = ""
    gap_ms: str = ""
    crossfade_ms: str = ""
    copy: bool = True
    clear_logs: bool = False
    parallel_run: bool = False


def _milliseconds(flag: str, value: str) -> int:
    """Return a millisecond option as an integer, refusing a negative one.

    Args:
        flag: The option's spelling, for the message.
        value: Its value as parsed from the launcher, empty when unset.

    Returns:
        The value in milliseconds, or 0 when the option was not given.

    Raises:
        SystemExit: With code 1 when the value is not a non-negative integer.
    """
    if not value:
        return 0
    try:
        milliseconds = int(value)
    except ValueError:
        milliseconds = -1
    if milliseconds < 0:
        print_tool_usage_error(
            "Audio Joiner", f"{flag} must be a millisecond count, got {value!r}"
        )
        raise SystemExit(1) from None
    return milliseconds


def parse(argv: list[str] | None = None) -> AudioJoinerArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        An :class:`AudioJoinerArgs` instance.

    Raises:
        SystemExit: With code 1 when the folder path is invalid, the order
            names nothing, or both a gap and a crossfade are asked for.
    """
    if argv is None:
        argv = sys.argv
    args = AudioJoinerArgs()
    if len(argv) < 2:
        return args
    args.apply_handshake(parse_driver_handshake(argv, _VALUE_OPTIONS))
    tail = argv[1:]
    args.copy = "--no-copy" not in tail
    values, _ = scan_value_options(tail, _VALUE_OPTIONS)
    apply_str_options(args, values, _VALUE_OPTIONS)
    # The driver always sends both options, with ``0`` for "unset", so the
    # mutual exclusion is decided on the numbers: comparing the raw strings
    # made ``--gap-ms 0 --crossfade-ms 0`` a refusal of every driver launch.
    gap_ms = _milliseconds("--gap-ms", args.gap_ms)
    crossfade_ms = _milliseconds("--crossfade-ms", args.crossfade_ms)
    if gap_ms and crossfade_ms:
        print_tool_usage_error(
            "Audio Joiner",
            "Set a gap or a crossfade, not both: they describe the same boundary",
        )
        raise SystemExit(1)
    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("Audio Joiner", error)
        raise SystemExit(1)
    return args
