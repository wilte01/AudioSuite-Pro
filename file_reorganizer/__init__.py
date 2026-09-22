"""
File Reorganizer - Tag-based file reorganization utility.

Moves or copies audio files into a folder hierarchy based on their
existing tag values, using foobar2000-like pattern syntax.
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["FileReorganizer", "FileReorganizerApp", "evaluate_pattern", "resolve_path"]

from .core.engine import FileReorganizer
from .core.pattern import evaluate_pattern, resolve_path


def main() -> None:
    from .app import main as _app_main

    _app_main()


def __getattr__(name: str) -> type:
    if name == "FileReorganizerApp":
        from .app import FileReorganizerApp

        return FileReorganizerApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
