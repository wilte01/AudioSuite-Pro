"""cli_args.py — Launcher argument parsing for the Tag-Based File Reorganizer.

Mirrors the Tag Editor launcher contract so the Master Driver's argv reaches
the GUI widgets.

Master Driver handshake layout:
    argv[1]                 - source music directory (scanned recursively)
    --output-dir <path>     - destination directory
    --action <copy|move>    - how matched files are placed
    --specific-pattern <p>  - pattern template for specific-artist albums
    --various-pattern <p>   - pattern template for various-artist albums
    named flags:            --live|--dry, --start|--no-start, --end|--no-end
    display-only:           --clear-logs|--no-clear-logs,
                            --parallel-run|--no-parallel-run

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, validate_folder_path
from audio_suite_shared.cli_helpers import (
    apply_handshake_segment,
    print_tool_usage_error,
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
    "--output-dir": "output_dir",
    "--action": "action",
    "--specific-pattern": "specific_pattern",
    "--various-pattern": "various_pattern",
}

_VALID_ACTIONS = frozenset({"copy", "move"})


@dataclass
class FileReorganizerArgs(BaseCLIArgs):
    """Parsed File Reorganizer launcher arguments."""

    output_dir: str = ""
    action: str = ""
    specific_pattern: str = ""
    various_pattern: str = ""
    clear_logs: bool = False
    parallel_run: bool = False


def _scan_value_options(tokens: list[str], args: FileReorganizerArgs) -> None:
    """Fill value options from *tokens*, skipping unknown tokens.

    Args:
        tokens: The argv tail after the positional source path.
        args: The args instance mutated in place.
    """
    index = 0
    while index < len(tokens):
        attr = _VALUE_OPTIONS.get(tokens[index])
        if attr is not None and index + 1 < len(tokens):
            setattr(args, attr, tokens[index + 1])
            index += 2
            continue
        index += 1


def validate_args(args: FileReorganizerArgs) -> list[str]:
    """Validate launcher arguments.

    Args:
        args: Parsed launcher arguments.

    Returns:
        Human-readable validation errors; empty when valid.
    """
    errors = validate_folder_path(args.folder_path)
    if args.action and args.action not in _VALID_ACTIONS:
        errors.append(f"Action must be 'copy' or 'move', got: {args.action}")
    return errors


def parse(argv: list[str] | None = None) -> FileReorganizerArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`FileReorganizerArgs` instance.

    Raises:
        SystemExit: With code 1 when validation fails.
    """
    if argv is None:
        argv = sys.argv
    args = FileReorganizerArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    tail = argv[2:]
    _scan_value_options(tail, args)
    apply_handshake_segment(tail, args, accepted=ACCEPTED_HANDSHAKE)
    errors = validate_args(args)
    if errors:
        for error in errors:
            print_tool_usage_error("File Reorganizer", error)
        raise SystemExit(1)
    return args
