"""
mapping_engine.py — Data types, constants, and value-transformation logic.

This module owns the pure data layer: result types, statistics accumulator,
format-agnostic tag mappings, and the slash-replacement utility functions.
It has zero knowledge of Mutagen or file I/O.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ProcessingResult:
    """Immutable result of processing a single audio file.

    Attributes:
        file_path: Absolute path to the processed file.
        updated: True if one or more tags were written back to disk.
        tags_updated: Names of tag keys that were modified.
        error: Human-readable error string if processing failed, else None.
    """

    file_path: Path
    updated: bool = False
    tags_updated: tuple[str, ...] = field(default_factory=tuple)
    error: str | None = None


@dataclass
class ProcessingStats:
    """Mutable accumulator for statistics across a processing run.

    Attributes:
        total_files: Audio files that matched a supported extension.
        processed_files: Files that were opened and inspected (includes errors).
        updated_files: Files where at least one tag was rewritten.
        error_files: Files that raised an unhandled exception during processing.
        skipped_files: Files ignored due to unsupported extension or missing tags.
    """

    total_files: int = 0
    processed_files: int = 0
    updated_files: int = 0
    error_files: int = 0
    skipped_files: int = 0


# Supported audio extensions
SUPPORTED_EXTENSIONS: tuple[str, ...] = (
    ".mp3",
    ".flac",
    ".mp4",
    ".m4a",
    ".ogg",
    ".opus",
    ".wav",
    ".aiff",
    ".aif",
    ".wma",
)

# Tag field mappings by format
TAG_MAPPINGS: dict[str, dict[str, list[str]]] = {
    "mp3": {
        "txxx": ["TXXX:ALBUMARTISTGENRE", "TXXX:ALBUMGENRE", "TXXX:ARTISTGENRE"],
        "standard": ["TIT1", "TCON"],
    },
    "flac": {
        "txxx": ["ALBUMARTISTGENRE", "ALBUMGENRE", "ARTISTGENRE"],
        "standard": ["CONTENTGROUP", "GENRE"],
    },
    "mp4": {
        "txxx": [
            "----:TXXX:ALBUMARTISTGENRE",
            "----:TXXX:ALBUMGENRE",
            "----:TXXX:ARTISTGENRE",
        ],
        "standard": ["©grp", "©gen"],
    },
    "ogg": {
        "txxx": ["ALBUMARTISTGENRE", "ALBUMGENRE", "ARTISTGENRE"],
        "standard": ["CONTENTGROUP", "GENRE"],
    },
    "opus": {
        "txxx": ["ALBUMARTISTGENRE", "ALBUMGENRE", "ARTISTGENRE"],
        "standard": ["CONTENTGROUP", "GENRE"],
    },
    "wav": {
        "txxx": ["TXXX:ALBUMARTISTGENRE", "TXXX:ALBUMGENRE", "TXXX:ARTISTGENRE"],
        "standard": ["TIT1", "TCON"],
    },
    "aiff": {
        "txxx": ["TXXX:ALBUMARTISTGENRE", "TXXX:ALBUMGENRE", "TXXX:ARTISTGENRE"],
        "standard": ["TIT1", "TCON"],
    },
    "wma": {
        "txxx": ["ALBUMARTISTGENRE", "ALBUMGENRE", "ARTISTGENRE"],
        "standard": ["ContentGroupDescription", "Genre"],
    },
}


def should_update_value(value: str) -> bool:
    """Determine if a tag value contains a bare slash and requires updating.

    Args:
        value: The tag value string to inspect.

    Returns:
        True if ``value`` contains at least one ``'/'`` character.
    """
    return "/" in value


def update_value(value: str) -> str:
    """Transform a tag value by replacing bare slashes with ``'; '``.

    Segments separated by ``' / '`` (space-slash-space) are left intact;
    only bare ``'/'`` characters within each segment are replaced.

    Args:
        value: The original tag value string.

    Returns:
        The transformed string with bare ``'/'`` replaced by ``'; '``.
        Values containing no ``'/'`` are returned unchanged.
    """
    if " / " in value:
        parts = value.split(" / ")
        updated_parts = [
            part.replace("/", "; ") if "/" in part else part for part in parts
        ]
        return " / ".join(updated_parts)

    if "/" in value:
        return value.replace("/", "; ")

    return value
