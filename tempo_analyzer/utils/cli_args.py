"""
cli_args.py - CLI argument parser for Tempo Analyzer with validation.

Master Driver handshake layout:
    argv[1]  - folder path
    argv[3]  - '--live' | '--dry'
    argv[4]  - '--start' | '--no-start'
    argv[5]  - '--end'   | '--no-end'
    argv[6+] - named pairs: --scheme <SchemeName>
               display-only flags: --clear-logs|--no-clear-logs,
               --parallel-run|--no-parallel-run
"""

import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import (
    BaseCLIArgs,
    CLIValidationError,
    validate_folder_path,
    validate_tempo_scheme,
)
from audio_suite_shared.cli_helpers import (
    consume_handshake_token,
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


@dataclass
class TempoAnalyzerArgs(BaseCLIArgs):
    """CLI arguments for Tempo Analyzer."""

    scheme: str | None = None  # None = use saved config value
    clear_logs: bool = False  # Display only — driver-owned orchestration flag
    parallel_run: bool = False  # Display only — driver-owned orchestration flag


def validate_args(args: TempoAnalyzerArgs) -> list[str]:
    """
    Validate CLI arguments.

    Args:
        args: Parsed TempoAnalyzerArgs instance.

    Returns:
        List of human-readable error strings (empty if all valid).
    """
    errors: list[str] = []

    errors.extend(validate_folder_path(args.folder_path))

    if args.scheme:
        from tempo_analyzer.core.tempo_schemes import TEMPO_SCHEMES

        valid_schemes = list(TEMPO_SCHEMES.keys())
        errors.extend(validate_tempo_scheme(args.scheme, valid_schemes))

    return errors


def parse(argv: list[str] | None = None) -> TempoAnalyzerArgs:
    """
    Parse and validate CLI arguments.

    Args:
        argv: Argument list (defaults to sys.argv).

    Returns:
        Populated TempoAnalyzerArgs instance.

    Raises:
        CLIValidationError: If any argument fails validation.
    """
    if argv is None:
        argv = sys.argv

    args = TempoAnalyzerArgs()
    if len(argv) < 2:
        return args

    args.folder_path = argv[1]

    i = 2
    while i < len(argv):
        arg = argv[i]

        if consume_handshake_token(arg, args, accepted=ACCEPTED_HANDSHAKE) is True:
            i += 1
        elif arg == "--scheme" and i + 1 < len(argv):
            args.scheme = argv[i + 1]
            i += 2
        else:
            i += 1

    errors = validate_args(args)
    if errors:
        raise CLIValidationError("; ".join(errors))

    return args
