"""
cli_args.py — CLI argument parser for Key Detector.

Master Driver handshake layout:
    argv[1]  - folder path
    argv[3]  - '--live' | '--dry'
    argv[4]  - '--start' | '--no-start'
    argv[5]  - '--end' | '--no-end'
    argv[6+] - named pairs: --duration N, --workers N, --parallel|--no-parallel
               display-only flags: --clear-logs|--no-clear-logs,
               --parallel-run|--no-parallel-run

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.

The handshake, the option tail and the validation are shared with Mood Analyzer
(``audio_suite_shared.analysis_cli``); this module names the tool and its
argument record, nothing more.

Changed in 1.4.0: ``max_workers`` defaults to ``default_max_workers()``.
Changed in 2.6.0: ``analysis_duration`` defaults to
``DEFAULT_ANALYSIS_SECONDS``, the window the GUI and the command line use
(D140).

Changed in 2.9.0: the parser and validation come from analysis_cli (B3).
"""

from dataclasses import dataclass
from typing import Any

from audio_suite_shared.analysis_cli import ACCEPTED_HANDSHAKE as ACCEPTED_HANDSHAKE
from audio_suite_shared.analysis_cli import (
    AnalysisCLIArgs,
    parse_analysis_args,
    validate_analysis_args,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)

_USAGE_LABEL = "Key Detector"


@dataclass
class KeyDetectorArgs(AnalysisCLIArgs):
    """CLI arguments for Key Detector."""


def validate_args(args: KeyDetectorArgs) -> list[Any]:
    """Validate CLI arguments and return list of errors."""
    return validate_analysis_args(args, _USAGE_LABEL)


def parse(argv: list[str] | None = None) -> KeyDetectorArgs:
    """Parse the Master Driver handshake and this tool's options."""
    return parse_analysis_args(KeyDetectorArgs, _USAGE_LABEL, argv)
