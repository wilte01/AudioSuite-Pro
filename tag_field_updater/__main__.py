"""
Entry point for Tag Field Updater package.

Usage:
    python -m tag_field_updater
    python -m tag_field_updater --directory /path/to/music
"""

from __future__ import annotations

import argparse

from .ui.app import main


def cli_entry() -> None:
    """Command-line entry point."""
    parser = argparse.ArgumentParser(
        description="Tag Field Updater - Update TXXX tag fields in music library"
    )
    parser.add_argument("--directory", "-d", help="Music library directory to scan")
    args = parser.parse_args()

    main(directory=args.directory)


if __name__ == "__main__":
    cli_entry()
