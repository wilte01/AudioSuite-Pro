"""cli_args.py — launcher argument parsing for the Artwork Extractor.

Master Driver handshake layout::

    argv[1]                         - music directory (one level by default)
    --name <stem>                   - sidecar base name (default: cover)
    --force / --no-force            - replace an existing sidecar
    --recursive / --no-recursive    - also read sub-folders
    named flags:                    --live|--dry, --start|--no-start,
                                    --end|--no-end
    display-only:                   --clear-logs|--no-clear-logs,
                                    --parallel-run|--no-parallel-run

The folder, the mode and the auto-start/auto-end pair are read by the shared
grammar; the three job options are this tool's own, and the last spelling of a
pair wins so an argv that repeats one reads the way it is written.

Changed in 2.6.0: new module — the Artwork Extractor's driver handshake.
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
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

#: Default sidecar base name; its extension follows the image's own format.
DEFAULT_SIDECAR_NAME = "cover"

#: Named options that consume the token following them.
_VALUE_OPTIONS: dict[str, str] = {"--name": "sidecar_name"}

#: Pairs whose last spelling wins, as ``(on token, off token, default)``.
_FLAG_PAIRS: tuple[tuple[str, str, bool], ...] = (
    ("--force", "--no-force", False),
    ("--recursive", "--no-recursive", False),
)


@dataclass
class ArtworkArgs(BaseCLIArgs):
    """Parsed Artwork Extractor launcher arguments."""

    sidecar_name: str = DEFAULT_SIDECAR_NAME
    force: bool = False
    recursive: bool = False


def _last_flag(argv: Sequence[str], on: str, off: str, default: bool) -> bool:
    """Return which spelling of a boolean pair appears last in *argv*.

    Args:
        argv: The argument vector (or its tail) to scan.
        on: The token that turns the flag on.
        off: The token that turns it off.
        default: The value when neither token appears.

    Returns:
        ``True`` when *on* is the last of the two tokens, ``False`` when *off*
        is, and *default* when the vector holds neither.
    """
    value = default
    for token in argv:
        if token == on:
            value = True
        elif token == off:
            value = False
    return value


def _validate_sidecar_name(name: str) -> str | None:
    """Return the reason *name* cannot be a sidecar base name, or ``None``.

    A name carrying a path would write outside the album folder, and an empty
    name would produce a bare extension, so both are refused before a run
    starts rather than by the writer once files are already being read.

    Args:
        name: The requested sidecar base name.

    Returns:
        The user-facing reason, or ``None`` when the name is usable.
    """
    if not name:
        return "--name must not be empty"
    if name in {".", ".."} or "/" in name or "\\" in name:
        return f"--name must be a bare file name, got {name!r}"
    return None


def parse(argv: list[str] | None = None) -> ArtworkArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        An :class:`ArtworkArgs` instance.

    Raises:
        SystemExit: With code 1 when the folder path or the sidecar name is
            invalid.
    """
    if argv is None:
        argv = sys.argv
    args = ArtworkArgs()
    if len(argv) < 2:
        return args
    args.apply_handshake(parse_driver_handshake(argv, _VALUE_OPTIONS))
    tail = argv[1:]
    values, _ = scan_value_options(tail, _VALUE_OPTIONS)
    apply_str_options(args, values, _VALUE_OPTIONS)
    for on, off, default in _FLAG_PAIRS:
        attribute = on.removeprefix("--").replace("-", "_")
        setattr(args, attribute, _last_flag(tail, on, off, default))
    problem = _validate_sidecar_name(args.sidecar_name)
    if problem is not None:
        print_tool_usage_error("Artwork Extractor", problem)
        raise SystemExit(1)
    errors = validate_folder_path(args.folder_path)
    if errors:
        for error in errors:
            print_tool_usage_error("Artwork Extractor", error)
        raise SystemExit(1)
    return args
