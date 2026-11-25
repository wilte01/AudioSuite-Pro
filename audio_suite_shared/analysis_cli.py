"""analysis_cli.py — the command line the per-file analysis tools share.

Key Detector and Mood Analyzer expose the same surface: a folder, the Master
Driver handshake in fixed positional slots, a sampled analysis window and a
parallel worker count.  Each carried its own copy of the handshake parser, the
argument record, the validation and the Click command — two modules that were
byte-identical apart from the dataclass name and the tool-name string, so a
change to the handshake or to the duration bounds had to be made twice.

This module owns that surface.  A tool keeps a module with its own name and
docstring, its argument record (a subclass, so a future tool-specific option
has somewhere to live) and a two-line ``parse`` wrapper; the behaviour is here.

Changed in 2.9.0: new module - the parser and command two analysis tools shared (B3).
Changed in 2.9.0: CLI output goes through ``cli_base._echo`` instead of
``click.echo``, whose Windows console writer rejects every write in a
PowerShell console; a ``--json`` document that cannot be written now
exits 1.
"""

from __future__ import annotations

import json as _json_mod
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

import click

from .batch_undo import active_batch
from .cli_base import (
    _echo,
    _opt_dir,
    _opt_dry_run,
    _opt_json,
    _opt_parallel,
    _opt_workers,
    _run_tool,
    cli,
    finish_run,
)
from .cli_dataclasses import BaseCLIArgs
from .cli_helpers import (
    consume_handshake_token,
    print_tool_usage_error,
    read_positional_handshake,
)
from .constants import DEFAULT_ANALYSIS_SECONDS, default_max_workers

__all__ = [
    "ACCEPTED_HANDSHAKE",
    "AnalysisCLIArgs",
    "analysis_command",
    "parse_analysis_args",
    "validate_analysis_args",
]

#: The shortest and longest sampled analysis window the tools accept, in
#: seconds.  A shorter window has too little audio to measure; a longer one
#: stops being the window the periodicity floor was calibrated on (D139).
MIN_DURATION_SECONDS = 10
MAX_DURATION_SECONDS = 600


@dataclass
class AnalysisCLIArgs(BaseCLIArgs):
    """Arguments for a tool that analyses a sampled window of each file."""

    analysis_duration: int = DEFAULT_ANALYSIS_SECONDS
    parallel_mode: bool = False
    max_workers: int = field(default_factory=default_max_workers)
    clear_logs: bool = False  # Display only — driver-owned orchestration flag
    parallel_run: bool = False  # Display only — driver-owned orchestration flag


#: The named-pair tail accepted only the display-only pair (mode/start/end live
#: in the fixed positional slots); mirror that token subset byte-exactly.
ACCEPTED_HANDSHAKE = frozenset(
    {
        "--clear-logs",
        "--no-clear-logs",
        "--parallel-run",
        "--no-parallel-run",
    }
)

_ArgsT = TypeVar("_ArgsT", bound=AnalysisCLIArgs)


def validate_analysis_args(args: AnalysisCLIArgs, tool_name: str) -> list[Any]:
    """Validate the shared analysis arguments and return a list of errors.

    Args:
        args: The parsed record.
        tool_name: How the tool is named in a usage error, e.g.
            ``"Key Detector"``.

    Returns:
        The validation errors; empty when the arguments are usable.
    """
    errors: list[Any] = []
    if args.folder_path:
        if not os.path.exists(args.folder_path):
            errors.append(f"Folder path does not exist: {args.folder_path}")
        elif not os.path.isdir(args.folder_path):
            errors.append(f"Path is not a directory: {args.folder_path}")
    if args.analysis_duration < MIN_DURATION_SECONDS:
        errors.append(
            f"Analysis duration must be {MIN_DURATION_SECONDS}-"
            f"{MAX_DURATION_SECONDS} seconds, got: {args.analysis_duration}"
        )
    elif args.analysis_duration > MAX_DURATION_SECONDS:
        errors.append(
            f"Analysis duration must be {MIN_DURATION_SECONDS}-"
            f"{MAX_DURATION_SECONDS} seconds, got: {args.analysis_duration}"
        )
    return errors


def parse_analysis_args(
    args_type: type[_ArgsT],
    tool_name: str,
    argv: list[str] | None = None,
) -> _ArgsT:
    """Parse the Master Driver handshake and the shared option tail.

    Args:
        args_type: The tool's argument record.
        tool_name: How the tool is named in a usage error.
        argv: The argument vector; defaults to ``sys.argv``.

    Returns:
        The populated record.

    Raises:
        SystemExit: A validation error was reported on stderr, which is how
            every tool's launcher already reports bad arguments.
    """
    if argv is None:
        argv = sys.argv
    args = args_type()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    read_positional_handshake(argv, args, mode_idx=3, start_idx=4, end_idx=5)
    i = 6
    while i < len(argv):
        arg = argv[i]
        if arg == "--duration" and i + 1 < len(argv):
            try:
                args.analysis_duration = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--workers" and i + 1 < len(argv):
            try:
                args.max_workers = int(argv[i + 1])
            except ValueError:
                pass
            i += 2
        elif arg == "--parallel":
            args.parallel_mode = True
            i += 1
        elif arg == "--no-parallel":
            args.parallel_mode = False
            i += 1
        elif consume_handshake_token(arg, args, accepted=ACCEPTED_HANDSHAKE) is True:
            i += 1
        else:
            i += 1
    errors = validate_analysis_args(args, tool_name)
    if errors:
        for error in errors:
            print_tool_usage_error(tool_name, error)
        raise SystemExit(1)
    return args


def analysis_command(
    *,
    name: str,
    tool_title: str,
    payload_tag: str,
    batch_tool: str,
    summary: str,
    processor: Callable[[], Callable[..., Any]],
) -> click.Command:
    """Build the Click command a per-file analysis tool exposes.

    Args:
        name: The command name on the shared ``audiosuite`` group.
        tool_title: How the run is titled in its output, e.g.
            ``"Key Detector"``.
        payload_tag: The ``tool`` field of the JSON payload.
        batch_tool: The undo batch's tool name.
        summary: The command's one-line help.
        processor: Returns the tool's ``run_analysis``.  A factory rather than
            the function itself, so the module registers its command without
            importing the analysis stack (librosa, numpy) at CLI import time.

    Returns:
        The registered command.
    """

    @cli.command(name=name, help=summary)
    @_opt_dir
    @_opt_dry_run
    @_opt_json
    @_opt_parallel
    @_opt_workers
    @click.option(
        "--duration",
        default=DEFAULT_ANALYSIS_SECONDS,
        type=int,
        help=f"Analysis duration in seconds (default {DEFAULT_ANALYSIS_SECONDS}).",
    )
    def command(
        directory: str,
        dry_run: bool,
        json: bool,
        duration: int,
        parallel: bool,
        workers: int,
    ) -> None:
        with active_batch(batch_tool, "tag_edit"):
            result = _run_tool(
                tool_title,
                processor(),
                dir_path=directory,
                is_dry_run=dry_run,
                analysis_duration=duration,
                parallel_mode=parallel,
                max_workers=workers,
            )
        if json:
            _echo(
                _json_mod.dumps(
                    result.to_payload(payload_tag, dry_run=dry_run), indent=2
                ),
                required=True,
            )
        else:
            _echo(
                f"  Summary: {result.processed} files, "
                f"{result.skipped} skipped, {result.errors} errors "
                f"in {result.duration_secs:.1f}s"
            )
        finish_run(result)

    return command
