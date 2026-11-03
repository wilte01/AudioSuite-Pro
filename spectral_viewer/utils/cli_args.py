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

Changed in 2.4.1: reads the driver argv through the shared
``scan_value_options`` / ``parse_driver_handshake`` grammar instead of
its own scanner (WP-4, C-M8).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

from audio_suite_shared.cli_dataclasses import BaseCLIArgs, CLIValidationError
from audio_suite_shared.cli_helpers import (
    parse_driver_handshake,
    scan_value_options,
)
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

#: The same options as bare flag names, for the shared scanner.
_VALUE_FLAGS: tuple[str, ...] = tuple(flag for flag, _attr, _caster in _VALUE_OPTIONS)

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
    args.apply_handshake(parse_driver_handshake(argv, _VALUE_FLAGS))
    values, _ = scan_value_options(argv[1:], _VALUE_FLAGS)
    for flag, attr, caster in _VALUE_OPTIONS:
        if flag not in values:
            continue
        raw = values[flag]
        if raw is None:
            raise CLIValidationError(f"{flag} requires a value.")
        try:
            setattr(args, attr, caster(raw))
        except ValueError as exc:
            raise CLIValidationError(
                f"{flag} expects a {caster.__name__}, got {raw!r}."
            ) from exc
    errors = validate_args(args)
    if errors:
        raise CLIValidationError("; ".join(errors))
    return args
