#!/usr/bin/env python3
"""
Tag Field Updater - Recursively scan music library and update TXXX tag fields.

This is a backward-compatibility wrapper. The actual implementation has been
refactored into the tag_field_updater package:
    - tag_field_updater/core/processor.py - Business logic
    - tag_field_updater/ui/app.py - Tkinter UI

Updates TXXX/ALBUMARTISTGENRE, TXXX/ALBUMGENRE, and TXXX/ARTISTGENRE
by replacing '/' with '; ' in existing values, but preserving values that contain ' / '.
"""

import argparse
import logging
import tkinter as tk
import warnings

from tag_field_updater.core.processor import (
    ProcessingResult,
    ProcessingStats,
    TagProcessor,
)
from tag_field_updater.ui.app import TagFieldUpdaterApp
from tag_field_updater.ui.app import main as _main

logger = logging.getLogger(__name__)


# Backward compatibility: TagFieldUpdater now inherits from the new TagFieldUpdaterApp
class TagFieldUpdater(TagFieldUpdaterApp):
    """
    Backward-compatible main class for updating tag fields in music files.

    This class is maintained for compatibility with existing code.
    New code should use TagFieldUpdaterApp from tag_field_updater.ui.app
    or TagProcessor from tag_field_updater.core.processor for non-UI use.
    """

    def __init__(self) -> None:
        """Initialize the tag field updater (backward compatibility wrapper)."""
        warnings.warn(
            "TagFieldUpdater is deprecated; use TagFieldUpdaterApp from "
            "tag_field_updater.ui.app instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(tk.Tk())


# Backward compatibility: expose all original public API
__all__ = [
    "TagFieldUpdater",
    "main",
    "TagProcessor",
    "ProcessingResult",
    "ProcessingStats",
]


def main() -> None:
    """Main function - delegates to the new package implementation."""
    parser = argparse.ArgumentParser(
        description="Tag Field Updater - Update TXXX tag fields in music library"
    )
    parser.add_argument("--directory", help="Music library directory to scan")
    args = parser.parse_args()

    _main(directory=args.directory)


if __name__ == "__main__":
    main()
