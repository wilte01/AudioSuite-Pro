"""
file_discovery.py - part of BaseFileProcessor, split out in 2.4.3.

WP-9 #2 moved this group of methods off :class:`BaseFileProcessor` into
``FileDiscoveryMixin``. Method bodies are unchanged, and ``file_processor_base``
still re-exports every public name, so existing importers are
unaffected.

Changed in 2.4.3: split out of ``audio_suite_shared.file_processor_base``
(PLAN_2026-11-03_2.4.3_structure.md WP-9).
"""

from __future__ import annotations

import os

from .audio_formats import SUPPORTED_EXTENSIONS
from .exceptions import AudioDirectoryError, AudioPermissionError


class FileDiscoveryMixin:
    """Discovery half of ``BaseFileProcessor``: one directory, one file list."""

    def discover_audio_files(
        self, dir_path: str, extensions: tuple[str, ...] | None = None
    ) -> list[str]:
        """
        Discover audio files in directory with consistent filtering logic.

        Raises AudioPermissionError or AudioDirectoryError on failure —
        never swallows OS errors silently.
        """
        if extensions is None:
            extensions = SUPPORTED_EXTENSIONS

        try:
            files = [
                e.name
                for e in os.scandir(dir_path)
                if e.is_file() and e.name.lower().endswith(extensions)
            ]
            return files
        except PermissionError as exc:
            raise AudioPermissionError(
                f"Permission denied accessing directory: {dir_path}",
                path=dir_path,
                original=exc,
            ) from exc
        except OSError as exc:
            raise AudioDirectoryError(
                f"Could not read directory: {dir_path}",
                context={"path": dir_path},
                original=exc,
            ) from exc
