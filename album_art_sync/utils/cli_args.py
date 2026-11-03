"""
cli_args.py — CLI argument parser for Album Art Sync.

Master Driver handshake layout::

    argv[1]            folder path
    --live | --dry     execution mode flag
    --start            auto-start processing on launch
    --end              auto-close window on completion
    --embed-size <n>   embedded artwork pixel dimension (600 / 800 / 1000 / 1200)
    --min-dimension <n> minimum candidate pixel dimension (px; default 500)
    --match-threshold <f> album fuzzy-match threshold 0.0–1.0 (default 0.85)
    --purge            remove hidden Windows system art files before embedding
    --no-purge         skip purge step
    display-only flags: --clear-logs|--no-clear-logs,
                        --parallel-run|--no-parallel-run

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.

Changed in 2.4.1: reads the driver argv through the shared
``scan_value_options`` / ``parse_driver_handshake`` grammar instead of
its own scanner (WP-4, C-M8).
"""

import os
import sys
from dataclasses import dataclass

from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.cli_helpers import (
    parse_driver_handshake,
    print_tool_usage_error,
    scan_value_options,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)

from ..config.settings import ALBUM_MATCH_THRESHOLD, MIN_ART_DIMENSION

# ---------------------------------------------------------------------------
# Valid embedded artwork pixel dimensions — must match the UI combobox values
# defined in ui/main_tabs.py.
# ---------------------------------------------------------------------------

VALID_EMBED_SIZES: frozenset[int] = frozenset({600, 800, 1000, 1200})

#: The options that consume the token following them, read by the shared
#: scanner so an option placed before the folder cannot be read as the path.
_VALUE_OPTIONS: tuple[str, ...] = (
    "--embed-size",
    "--min-dimension",
    "--match-threshold",
)


@dataclass
class ArtArgs(BaseCLIArgs):
    """CLI arguments for Album Art Sync."""

    embed_size: str = "800"
    purge: bool = True
    min_art_dimension: int = MIN_ART_DIMENSION
    album_match_threshold: float = ALBUM_MATCH_THRESHOLD
    clear_logs: bool = False  # Display only — driver-owned orchestration flag
    parallel_run: bool = False  # Display only — driver-owned orchestration flag


def validate_args(args: ArtArgs) -> list[str]:
    """Validate CLI arguments and return a list of error messages.

    Args:
        args: Parsed CLI arguments to validate.

    Returns:
        A list of human-readable error strings; empty when all values are valid.
    """
    errors: list[str] = []
    if args.folder_path:
        if not os.path.exists(args.folder_path):
            errors.append(f"Folder path does not exist: {args.folder_path}")
        elif not os.path.isdir(args.folder_path):
            errors.append(f"Path is not a directory: {args.folder_path}")
    if args.embed_size:
        try:
            size = int(args.embed_size)
            if size not in VALID_EMBED_SIZES:
                errors.append(
                    f"Embed size must be one of"
                    f" {sorted(VALID_EMBED_SIZES)}, got: {size}"
                )
        except ValueError:
            errors.append(f"Embed size must be numeric, got: {args.embed_size}")
    if not (200 <= args.min_art_dimension <= 2000):
        errors.append(
            f"Min dimension must be between 200 and 2000, got: {args.min_art_dimension}"
        )
    if not (0.0 < args.album_match_threshold <= 1.0):
        errors.append(
            "Match threshold must be between 0.0 and 1.0, got: "
            f"{args.album_match_threshold}"
        )
    return errors


def parse(argv: list[str] | None = None) -> ArtArgs:
    """Parse Master Driver CLI arguments for Album Art Sync.

    Master Driver handshake layout::

        argv[1]            folder path
        --live | --dry     execution mode flag
        --start            auto-start processing on launch
        --end              auto-close window on completion
        --embed-size <n>   embedded artwork pixel dimension (600 / 800 / 1000 / 1200)
        --min-dimension <n> minimum candidate pixel dimension (px; default 500)
        --match-threshold <f> album fuzzy-match threshold 0.0–1.0 (default 0.85)
        --purge            remove hidden Windows system art files before embedding
        --no-purge         skip purge step

    All flags except ``argv[1]`` are order-independent; position is not
    significant.

    Args:
        argv: Argument vector to parse.  Defaults to ``sys.argv`` when ``None``.

    Returns:
        Populated :class:`ArtArgs` instance.

    Raises:
        SystemExit: If ``argv`` contains invalid or out-of-range values.
    """
    if argv is None:
        argv = sys.argv
    args = ArtArgs()
    if len(argv) < 2:
        return args
    args.apply_handshake(parse_driver_handshake(argv, _VALUE_OPTIONS))
    values, _ = scan_value_options(argv[1:], _VALUE_OPTIONS)
    args.purge = "--no-purge" not in argv
    embed_size = values.get("--embed-size")
    if embed_size is not None:
        args.embed_size = embed_size
    raw_min_dim = values.get("--min-dimension")
    if raw_min_dim is not None:
        try:
            args.min_art_dimension = int(raw_min_dim)
        except ValueError:
            print_tool_usage_error(
                "Album Art Sync",
                f"Min dimension must be numeric, got: {raw_min_dim}",
            )
            raise SystemExit(1) from None
    raw_threshold = values.get("--match-threshold")
    if raw_threshold is not None:
        try:
            args.album_match_threshold = float(raw_threshold)
        except ValueError:
            print_tool_usage_error(
                "Album Art Sync",
                f"Match threshold must be numeric, got: {raw_threshold}",
            )
            raise SystemExit(1) from None
    errors = validate_args(args)
    if errors:
        for error in errors:
            print_tool_usage_error("Album Art Sync", error)
        raise SystemExit(1)
    return args
