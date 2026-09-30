"""
cli_args.py — CLI argument parser for Metadata Scrubber.

Master Driver handshake layout:
    argv[1]  - folder path
    argv[3]  - '--live' | '--dry'
    argv[4]  - '--start' | '--no-start'
    argv[5]  - '--end' | '--no-end'
    argv[6+] - --preserve-lyrics | --no-preserve-lyrics
               --preserve-album-artist | --no-preserve-album-artist
               --preserve-embedded-art | --no-preserve-embedded-art
               --clear-logs | --no-clear-logs           (display only)
               --parallel-run | --no-parallel-run       (display only)

BaseCLIArgs provides: folder_path, live_mode, auto_start, auto_end.
"""

import os
import sys
from dataclasses import dataclass
from typing import Any

from audio_suite_shared.cli_dataclasses import BaseCLIArgs
from audio_suite_shared.cli_helpers import (
    apply_handshake_membership,
    print_tool_usage_error,
)
from audio_suite_shared.cli_helpers import (
    was_launched_from_driver as was_launched_from_driver,
)


@dataclass
class ScrubberArgs(BaseCLIArgs):
    """CLI arguments for Metadata Scrubber."""

    preserve_lyrics: bool = True
    preserve_album_artist: bool = True
    preserve_embedded_art: bool = True
    clear_logs: bool = False
    parallel_run: bool = False


def validate_args(args: ScrubberArgs) -> list[Any]:
    """Validate CLI arguments and return list of error strings."""
    errors = []
    if args.folder_path:
        if not os.path.exists(args.folder_path):
            errors.append(f"Folder path does not exist: {args.folder_path}")
        elif not os.path.isdir(args.folder_path):
            errors.append(f"Path is not a directory: {args.folder_path}")
    return errors


def parse(argv: list[str] | None = None) -> ScrubberArgs:
    """Parse sys.argv (or a supplied list) into a ScrubberArgs instance."""
    if argv is None:
        argv = sys.argv
    args = ScrubberArgs()
    if len(argv) < 2:
        return args
    args.folder_path = argv[1]
    apply_handshake_membership(argv, args)

    # Lyrics preservation (default True; --no-preserve-lyrics disables)
    if "--no-preserve-lyrics" in argv:
        args.preserve_lyrics = False
    # --preserve-lyrics is default True; explicit flag accepted as no-op

    # Album artist preservation (default True; --no-preserve-album-artist disables)
    if "--no-preserve-album-artist" in argv:
        args.preserve_album_artist = False
    # --preserve-album-artist is default True; explicit flag accepted as no-op

    # Embedded art preservation (default True; --no-preserve-embedded-art disables)
    if "--no-preserve-embedded-art" in argv:
        args.preserve_embedded_art = False
    # --preserve-embedded-art is default True; explicit flag accepted as no-op

    errors = validate_args(args)
    if errors:
        for error in errors:
            print_tool_usage_error("Metadata Scrubber", error)
        raise SystemExit(1)
    return args
