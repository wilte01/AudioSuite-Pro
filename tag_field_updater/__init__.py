"""
Tag Field Updater - Recursively scan music library and update TXXX tag fields.

This package provides functionality to update TXXX/ALBUMARTISTGENRE, TXXX/ALBUMGENRE,
and TXXX/ARTISTGENRE by replacing '/' with '; ' in existing values, while preserving
values that contain ' / '.

Package Structure:
- core/: Business logic and file format processors
- ui/: Tkinter user interface
"""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["TagProcessor", "TagFieldUpdaterApp"]

from .core.processor import TagProcessor


def __getattr__(name: str) -> type:
    if name == "TagFieldUpdaterApp":
        from .ui.app import TagFieldUpdaterApp

        return TagFieldUpdaterApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
