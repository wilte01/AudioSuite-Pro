"""Tag Editor — interactive batch editing of common audio tag fields."""

from __future__ import annotations

__version__ = "1.0.0"
__all__ = ["TagEditorApp", "TagEditorProcessor"]


from tag_editor.core.processor import TagEditorProcessor


def __getattr__(name: str) -> type:
    if name == "TagEditorApp":
        from tag_editor.ui.app import TagEditorApp

        return TagEditorApp
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
