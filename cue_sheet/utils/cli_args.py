"""cli_args.py — launcher argument parsing for the CUE Sheet Generator.

Master Driver handshake layout::

    argv[1]                   - folder of track files (or one audio file)
    --output <path>           - sheet path (default: album.cue beside the source)
    --album-title <text>      - album title for the sheet
    --album-artist <text>     - album artist for the sheet
    named flags:              --live|--dry, --start|--no-start, --end|--no-end,
    display-only:             --clear-logs|--no-clear-logs,
                              --parallel-run|--no-parallel-run

Changed in 2.6.0: new module (PLAN_2026-11-03_2.6.0_feature_wave_2.md F-E8).
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
    "--output": "output",
    "--album-title": "album_title",
    "--album-artist": "album_artist",
}


@dataclass
class CueSheetArgs(BaseCLIArgs):
    """Parsed CUE Sheet Generator launcher arguments."""

    output: str = ""
    album_title: str = ""
    album_artist: str = ""
    clear_logs: bool = False
    parallel_run: bool = False


def parse(argv: list[str] | None = None) -> CueSheetArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`CueSheetArgs` instance.

    Raises:
        SystemExit: With code 1 when the folder path is invalid.
    """
    if argv is None:
        argv = sys.argv
    args = CueSheetArgs()
    if len(argv) < 2:
        return args
    args.apply_handshake(parse_driver_handshake(argv, _VALUE_OPTIONS))
    values, _ = scan_value_options(argv[1:], _VALUE_OPTIONS)
    apply_str_options(args, values, _VALUE_OPTIONS)
    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("CUE Sheet Generator", error)
        raise SystemExit(1)
    return args
