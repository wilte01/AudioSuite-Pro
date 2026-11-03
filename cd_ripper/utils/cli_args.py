"""cli_args.py — Launcher argument parsing for the CD Ripper.

Mirrors the Tag Editor launcher contract so the Master Driver's argv reaches
the GUI widgets.

Master Driver layout (no positional folder — CD Ripper has no directory arg):
    --output-dir <path>  - output directory for ripped files
    --format <name>      - output format (lowercase: flac, mp3, ogg, m4a, wav, opus)
    --tracks <list>      - comma-separated track numbers to rip (e.g. "1,3,5")
    --cue                - write a CUE sheet alongside ripped tracks
    named flags:         --live|--dry, --start|--no-start, --end|--no-end,
    display-only:        --clear-logs|--no-clear-logs,
                         --parallel-run|--no-parallel-run

BaseCLIArgs provides: folder_path (unused), live_mode, auto_start, auto_end.

Changed in 1.0.1: adds the driver argv parser
(``--output-dir``/``--format``/``--tracks``/``--cue``).

Changed in 2.4.1: reads the driver argv through the shared
``scan_value_options`` / ``parse_driver_handshake`` grammar instead of
its own scanner (WP-4, C-M8).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.cli_helpers import (
    apply_str_options,
    parse_driver_handshake,
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
    "--output-dir": "output_dir",
    "--format": "format",
    "--tracks": "tracks",
}

#: Lowercase format name → GUI display name.
FORMAT_DISPLAY: dict[str, str] = {
    "wav": "WAV",
    "mp3": "MP3",
    "flac": "FLAC",
    "ogg": "OGG",
    "m4a": "M4A",
    "opus": "Opus",
}


@dataclass
class CdRipperArgs(BaseCLIArgs):
    """Parsed CD Ripper launcher arguments."""

    output_dir: str = ""
    format: str = ""
    tracks: str = ""
    cue: bool = False
    clear_logs: bool = False
    parallel_run: bool = False


def parse_track_selection(raw: str) -> set[int]:
    """Parse a comma-separated track-number string into a set of ints.

    Invalid tokens are silently skipped.

    Args:
        raw: Comma-separated track numbers, e.g. ``"1,3,5"``.

    Returns:
        A set of valid track numbers; empty when *raw* is blank.
    """
    out: set[int] = set()
    for tok in raw.split(","):
        tok = tok.strip()
        if tok.isdigit():
            out.add(int(tok))
    return out


def parse(argv: list[str] | None = None) -> CdRipperArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`CdRipperArgs` instance.
    """
    if argv is None:
        argv = sys.argv
    args = CdRipperArgs()
    tail = argv[1:]
    args.cue = "--cue" in tail
    values, _ = scan_value_options(tail, _VALUE_OPTIONS)
    apply_str_options(args, values, _VALUE_OPTIONS)
    # CD Ripper's argv carries no positional path — its destination is
    # ``--output-dir`` — so the handshake supplies only the flags.
    args.apply_handshake(parse_driver_handshake(argv, _VALUE_OPTIONS))
    return args
