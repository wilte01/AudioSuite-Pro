"""utils/cli_args.py — launcher argument parsing for Channel Tools.

Master Driver handshake layout::

    argv[1]                    - music directory
    --operation <rule>         - mono_mean | mono_minus3db | dual_mono |
                                 invert_phase | ms_encode | ms_decode | width
    --width <percent>          - side gain for the width operation
    --source-channel <side>    - left | right, for dual mono
    --invert <target>          - left | right | both, for phase inversion
    named flags:               --live|--dry, --start|--no-start, --end|--no-end,
    display-only:              --clear-logs|--no-clear-logs,
                               --parallel-run|--no-parallel-run

Changed in 2.5.0: new module (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from audio_suite_shared import channel_ops
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
    "--operation": "operation",
    "--width": "width",
    "--source-channel": "source_channel",
    "--invert": "invert_target",
}


@dataclass
class ChannelToolsArgs(BaseCLIArgs):
    """Parsed Channel Tools launcher arguments."""

    operation: str = channel_ops.DEFAULT_OPERATION
    width: str = ""
    source_channel: str = "left"
    invert_target: str = "both"
    clear_logs: bool = False
    parallel_run: bool = False


def _width_percent(text: str) -> float:
    """Return *text* as a width percentage.

    Args:
        text: The ``--width`` value, or ``""`` for the default.

    Returns:
        The percentage, or the default when the flag was not given.

    Raises:
        SystemExit: With code 1 when the value is not a number.
    """
    if not text.strip():
        return channel_ops.DEFAULT_WIDTH_PERCENT
    try:
        return float(text)
    except ValueError:
        print_tool_usage_error(
            "Channel Tools", f"--width must be a number, got {text!r}"
        )
        raise SystemExit(1) from None


def parse(argv: list[str] | None = None) -> ChannelToolsArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`ChannelToolsArgs` instance.

    Raises:
        SystemExit: With code 1 when the folder, the operation or one of its
            parameters is invalid.
    """
    if argv is None:
        argv = sys.argv
    args = ChannelToolsArgs()
    if len(argv) < 2:
        return args
    args.apply_handshake(parse_driver_handshake(argv, _VALUE_OPTIONS))
    values, _ = scan_value_options(argv[1:], _VALUE_OPTIONS)
    apply_str_options(args, values, _VALUE_OPTIONS)

    try:
        channel_ops.validate_operation(
            args.operation,
            width_percent=_width_percent(args.width),
            source_channel=args.source_channel,
            invert_target=args.invert_target,
        )
    except Exception as exc:  # noqa: BLE001 - one usage line, then exit 1
        print_tool_usage_error(
            "Channel Tools", getattr(exc, "message", None) or str(exc)
        )
        raise SystemExit(1) from None

    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("Channel Tools", error)
        raise SystemExit(1)
    return args
