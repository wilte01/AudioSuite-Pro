"""cli_args.py — Launcher argument parsing for the Spectral Viewer.

Mirrors the Library Statistics launcher contract so the Master Driver's argv
reaches the GUI widgets.

Master Driver handshake layout:
    argv[1]               - audio file *or* directory (scanned recursively)
    --output-dir <path>   - where exported PNGs go (default: beside the source)
    --n-fft <int>         - FFT window size in samples
    --db-range <float>    - colour floor in dB below the peak
    --cmap <name>         - matplotlib colour map
    named flags:          --live|--dry, --start|--no-start, --end|--no-end,
    display-only:         --clear-logs|--no-clear-logs,
                          --parallel-run|--no-parallel-run

``BaseCLIArgs.folder_path`` carries the path even when it names a single file;
it is the shared handshake's name and the viewer accepts both.

Changed in 1.3.0: initial version (PLAN_feature_expansion.md Item 3.1 / D42).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, CLIValidationError
from audio_suite_shared.cli_helpers import apply_handshake_segment
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)
from spectral_viewer.core.spectrogram import (
    DEFAULT_CMAP,
    DEFAULT_DB_RANGE,
    DEFAULT_N_FFT,
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

#: Named options that consume the token following them, with their coercion.
_VALUE_OPTIONS: tuple[tuple[str, str, type], ...] = (
    ("--output-dir", "output_dir", str),
    ("--n-fft", "n_fft", int),
    ("--db-range", "db_range", float),
    ("--cmap", "cmap", str),
)

#: Bounds the GUI enforces so an out-of-range driver value cannot reach the
#: FFT (a 4-sample window is not a spectrogram).
MIN_N_FFT = 256
MAX_N_FFT = 16384
MIN_DB_RANGE = 10.0
MAX_DB_RANGE = 140.0


@dataclass
class SpectralViewerArgs(BaseCLIArgs):
    """Parsed Spectral Viewer launcher arguments."""

    output_dir: str = ""
    n_fft: int = DEFAULT_N_FFT
    db_range: float = DEFAULT_DB_RANGE
    cmap: str = DEFAULT_CMAP
    clear_logs: bool = False
    parallel_run: bool = False


def validate_args(args: SpectralViewerArgs) -> list[str]:
    """Return every problem with *args* as a human-readable message.

    Args:
        args: Parsed arguments.

    Returns:
        Empty when the arguments are usable.
    """
    errors: list[str] = []
    if args.folder_path:
        target = Path(args.folder_path)
        if not target.exists():
            errors.append(f"Path does not exist: {args.folder_path}")
    if not MIN_N_FFT <= args.n_fft <= MAX_N_FFT:
        errors.append(
            f"FFT size must be between {MIN_N_FFT} and {MAX_N_FFT}, got {args.n_fft}"
        )
    if not MIN_DB_RANGE <= args.db_range <= MAX_DB_RANGE:
        errors.append(
            f"Dynamic range must be between {MIN_DB_RANGE:.0f} and "
            f"{MAX_DB_RANGE:.0f} dB, got {args.db_range}"
        )
    return errors


def _scan_value_options(tokens: list[str], args: SpectralViewerArgs) -> None:
    """Fill value options from *tokens*, skipping unknown tokens.

    Args:
        tokens: The argv tail after the positional path.
        args: The args instance mutated in place.

    Raises:
        CLIValidationError: If a named option's value cannot be coerced, or the
            option is given with no value at all.
    """
    index = 0
    by_flag = {flag: (attr, caster) for flag, attr, caster in _VALUE_OPTIONS}
    while index < len(tokens):
        option = by_flag.get(tokens[index])
        if option is None:
            index += 1
            continue
        attr, caster = option
        if index + 1 >= len(tokens):
            raise CLIValidationError(f"{tokens[index]} requires a value.")
        raw = tokens[index + 1]
        try:
            setattr(args, attr, caster(raw))
        except ValueError as exc:
            raise CLIValidationError(
                f"{tokens[index]} expects a {caster.__name__}, got {raw!r}."
            ) from exc
        index += 2


def parse(argv: list[str] | None = None) -> SpectralViewerArgs:
    """Parse launcher arguments passed by the Master Driver or a user.

    Args:
        argv: Argument vector; defaults to ``sys.argv``.

    Returns:
        A :class:`SpectralViewerArgs` instance.

    Raises:
        CLIValidationError: When a path or a numeric option is invalid.
    """
    if argv is None:
        argv = sys.argv
    args = SpectralViewerArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    tail = argv[2:]
    _scan_value_options(tail, args)
    apply_handshake_segment(tail, args, accepted=ACCEPTED_HANDSHAKE)
    errors = validate_args(args)
    if errors:
        raise CLIValidationError("; ".join(errors))
    return args
