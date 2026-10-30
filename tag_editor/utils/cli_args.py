"""cli_args.py — Launcher argument parsing for the Tag Editor.

The Master Driver's argv layout is the one every folder tool reads, so this
parser is the shared positional reader rather than its own token scan:

    argv[0]  - program name
    argv[1]  - music directory (scanned recursively)
    argv[2]  - '--live' | '--dry'
    argv[3]  - '--start' | '--no-start'
    argv[4]  - '--end'   | '--no-end'
    argv[5+] - display-only flags: --clear-logs/--no-clear-logs,
               --parallel-run/--no-parallel-run

The indices match the argument list the Master Driver's builder emits for this
utility tool (``[path, mode, start, end]``), the same prefix
``tag_field_updater`` reads.

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.

Changed in 2.2.1: reads the fixed positional slots through
``read_positional_handshake`` (maintenance item U5).  The old parser scanned
every token, so it accepted a layout the driver does not produce and would
have read a shifted argv as "no mode passed" instead of failing the way its
peers do.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, validate_folder_path
from audio_suite_shared.cli_helpers import (
    consume_handshake_token,
    print_tool_usage_error,
    read_positional_handshake,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)

logger = logging.getLogger(__name__)

#: The display-only pair the driver appends after the positional block.  The
#: mode / start / end flags live in fixed slots, so they are not tokens this
#: loop may see.
ACCEPTED_HANDSHAKE = frozenset(
    {
        "--clear-logs",
        "--no-clear-logs",
        "--parallel-run",
        "--no-parallel-run",
    }
)

#: The tokens the driver puts in the mode slot.  Its argv always carries one
#: (``arg_builder`` emits the mode flag for every tool), which is what lets a
#: launcher tell a handshake from any other argv it may be handed.
_DRIVER_MODE_TOKENS = frozenset({"--live", "--dry"})


@dataclass
class TagEditorArgs(BaseCLIArgs):
    """Parsed Tag Editor launcher arguments."""

    clear_logs: bool = False
    parallel_run: bool = False


def looks_like_driver_argv(argv: list[str] | None = None) -> bool:
    """Return whether *argv* carries the Master Driver's handshake layout.

    ``parse`` validates the folder it is handed and exits 1 when it is not a
    directory.  That is right for a handshake and wrong for any other argv the
    process may see — an interpreter's own switches under a test runner, for
    one — so the window applies the handshake only when the mode slot holds
    the flag the driver always passes.

    Args:
        argv: Full argument vector; defaults to ``sys.argv``.

    Returns:
        True when the argv has a driver-shaped mode slot.
    """
    if argv is None:
        argv = sys.argv
    return len(argv) > 2 and argv[2] in _DRIVER_MODE_TOKENS


def validate_args(args: TagEditorArgs) -> list[str]:
    """Validate launcher arguments.

    Args:
        args: Parsed launcher arguments.

    Returns:
        Human-readable validation errors; empty when valid.
    """
    errors = validate_folder_path(args.folder_path)
    if args.folder_path and not os.path.isdir(args.folder_path):
        errors.append(f"Path is not a directory: {args.folder_path}")
    return errors


def parse(argv: list[str] | None = None) -> TagEditorArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`TagEditorArgs` instance.

    Raises:
        SystemExit: With code 1 when the folder path is not a directory.
    """
    if argv is None:
        argv = sys.argv

    args = TagEditorArgs()
    if len(argv) < 2:
        return args

    args.folder_path = argv[1]

    read_positional_handshake(argv, args, mode_idx=2, start_idx=3, end_idx=4)

    # Display-only flags from position 5 onwards — the first index after every
    # positional slot, so the already-read ``--end`` is not re-visited.  The
    # loop stays tolerant of unknown tokens: a flag added by a newer driver
    # must not kill the window.
    i = 5
    while i < len(argv):
        consume_handshake_token(argv[i], args, accepted=ACCEPTED_HANDSHAKE)
        i += 1

    errors = validate_args(args)
    if errors:
        for error in errors:
            print_tool_usage_error("Tag Editor", error)
        raise SystemExit(1)

    logger.debug("cli_args parsed: %s", args)
    return args
