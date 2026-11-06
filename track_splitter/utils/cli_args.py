"""cli_args.py — launcher argument parsing for the Track Splitter.

Master Driver handshake layout::

    argv[1]                - music directory (scanned recursively)
    --output-dir <path>    - folder the tracks are written to
    --min-silence <ms>     - shortest silent run treated as a gap
    --silence-db <db>      - level at or below which audio counts as silence
    --min-track <ms>       - shortest track kept
    --boundary <rule>      - midpoint | start | end
    --naming <pattern>     - output filename pattern
    --cue / --no-cue       - write a CUE sheet beside the outputs
    named flags:           --live|--dry, --start|--no-start, --end|--no-end,
    display-only:          --clear-logs|--no-clear-logs,
                           --parallel-run|--no-parallel-run

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E4).
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

from ..core.models import BOUNDARY_RULES, DEFAULT_BOUNDARY, DEFAULT_NAMING

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
        "--cue",
        "--no-cue",
    }
)

#: Named options that consume the token following them.
_VALUE_OPTIONS: dict[str, str] = {
    "--output-dir": "output_dir",
    "--min-silence": "min_silence",
    "--silence-db": "silence_db",
    "--min-track": "min_track",
    "--boundary": "boundary",
    "--naming": "naming",
}


@dataclass
class TrackSplitterArgs(BaseCLIArgs):
    """Parsed Track Splitter launcher arguments."""

    output_dir: str = ""
    min_silence: str = ""
    silence_db: str = ""
    min_track: str = ""
    boundary: str = DEFAULT_BOUNDARY
    naming: str = DEFAULT_NAMING
    cue: bool = True
    clear_logs: bool = False
    parallel_run: bool = False


def parse(argv: list[str] | None = None) -> TrackSplitterArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`TrackSplitterArgs` instance.

    Raises:
        SystemExit: With code 1 when the folder path or the boundary rule is
            invalid.
    """
    if argv is None:
        argv = sys.argv
    args = TrackSplitterArgs()
    if len(argv) < 2:
        return args
    args.apply_handshake(parse_driver_handshake(argv, _VALUE_OPTIONS))
    tail = argv[1:]
    args.cue = "--no-cue" not in tail
    values, _ = scan_value_options(tail, _VALUE_OPTIONS)
    apply_str_options(args, values, _VALUE_OPTIONS)
    if args.boundary not in BOUNDARY_RULES:
        expected = ", ".join(BOUNDARY_RULES)
        print_tool_usage_error(
            "Track Splitter",
            f"--boundary must be one of {expected}, got {args.boundary!r}",
        )
        raise SystemExit(1)
    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("Track Splitter", error)
        raise SystemExit(1)
    return args
