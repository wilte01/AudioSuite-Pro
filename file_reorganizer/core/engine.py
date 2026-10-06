"""
Engine for reorganising audio files based on tag patterns.

Reads tags from each audio file, evaluates the user-defined pattern,
and copies or moves the file to the resolved target path.
"""

from __future__ import annotations

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from audio_suite_shared.constants import VARIOUS_ARTISTS_ALIASES
from audio_suite_shared.tag_helper import SUPPORTED_EXTENSIONS
from audio_suite_shared.tag_helper_base import TagHandlerFactory

try:
    from mutagen import MutagenError
except ImportError:  # pragma: no cover
    from audio_suite_shared.exceptions import MutagenError  # type: ignore[assignment]

from .pattern import PatternError, resolve_path

logger = logging.getLogger(__name__)


@dataclass
class ReorganizerStats:
    files_scanned: int = 0
    files_processed: int = 0
    files_skipped: int = 0
    errors: int = 0


ProgressCallback = Callable[[str, ReorganizerStats], None]


_TAG_FIELD_MAP: dict[str, str] = {
    "albumartist": "album_artist",
    "album": "album",
    "artist": "artist",
    "title": "title",
    "tracknumber": "tracknumber",
    "discnumber": "discnumber",
    "date": "date",
    "originaldate": "originaldate",
    "originalyear": "originalyear",
    "genre": "genre",
    "bpm": "bpm",
    "key": "key",
}


def _read_all_tags(file_path: str) -> dict[str, str]:
    """Read every supported tag from *file_path* into a flat dict.

    Keys use the lowercase names expected by the pattern syntax
    (``albumartist``, ``artist``, ``album``, ``title``, etc.).
    Missing or unreadable tags are returned as empty strings.
    """
    tags: dict[str, str] = {}
    try:
        handler = TagHandlerFactory.get_handler(file_path)
    except (MutagenError, OSError, ValueError) as exc:
        logger.debug("Could not open %s: %s", file_path, exc)
        return tags

    # Read album artist / artist / album / title
    album_artist = handler.read_album_artist()
    artist, album = handler.read_artist_album()
    tags["albumartist"] = album_artist if album_artist else ""
    tags["artist"] = artist
    tags["album"] = album

    # Read title via raw tags
    raw = handler.get_raw_tags()
    if raw is not None:
        _read_title(raw, tags)
        _read_track_disc(raw, tags)
        _read_date(raw, tags)
    else:
        tags["title"] = Path(file_path).stem
        tags["tracknumber"] = ""
        tags["discnumber"] = ""
        tags["date"] = ""
        tags["originaldate"] = ""
        tags["originalyear"] = ""

    # Read other well-known tags
    tags["genre"] = handler.read_genre() or ""
    tags["bpm"] = str(handler.read_bpm() or "")
    tags["key"] = handler.read_key() or ""

    return tags


def _safe_get(raw: Any, key: str) -> Any:
    """Read *key* from a mutagen tags container, tolerating absent keys.

    Vorbis comment dicts raise a bare ``ValueError`` (not ``KeyError``)
    from ``get()`` when the key is missing, so callers cannot rely on
    ``None`` being returned.

    Args:
        raw: Mutagen raw-tags container exposing ``get``.
        key: Tag key to read.

    Returns:
        The stored value, or None when the key is absent.
    """
    try:
        return raw.get(key)
    except (KeyError, ValueError):
        return None


def _read_title(raw: object, tags: dict[str, str]) -> None:
    """Extract title from raw mutagen tags."""
    try:
        if hasattr(raw, "get"):
            for key in ("TIT2", "\xa9nam", "title"):
                val = _safe_get(raw, key)
                if val:
                    text = val[0] if isinstance(val, list) else val
                    tags["title"] = str(text).strip()
                    return
    except (MutagenError, OSError, ValueError):
        pass
    tags["title"] = tags.get("title", "")


def _read_track_disc(raw: object, tags: dict[str, str]) -> None:
    """Extract track number and disc number from raw tags."""
    try:
        if hasattr(raw, "get"):
            trck = _safe_get(raw, "TRCK")
            if trck is None:
                trck = _safe_get(raw, "tracknumber")
            if trck is not None:
                text = str(trck[0] if isinstance(trck, list) else trck)
                tags["tracknumber"] = text.split("/")[0].strip()

            disc = _safe_get(raw, "TPOS")
            if disc is None:
                disc = _safe_get(raw, "discnumber")
            if disc is not None:
                text = str(disc[0] if isinstance(disc, list) else disc)
                tags["discnumber"] = text.split("/")[0].strip()
    except (MutagenError, OSError, ValueError):
        pass


def _read_date(raw: object, tags: dict[str, str]) -> None:
    """Extract date, originaldate, originalyear from raw tags."""
    try:
        if hasattr(raw, "get"):
            for src_key, dst_key in (
                ("TDRC", "date"),
                ("\xa9day", "date"),
                ("date", "date"),
                ("TDOR", "originaldate"),
                ("originaldate", "originaldate"),
                ("TORY", "originalyear"),
                ("originalyear", "originalyear"),
            ):
                val = _safe_get(raw, src_key)
                if val is not None:
                    text = str(val[0] if isinstance(val, list) else val)
                    tags[dst_key] = text.strip()
            # Fallback: check user-defined TXXX frames (common in
            # MusicBrainz-tagged files)
            if not tags.get("originalyear"):
                for desc in ("originalyear", "ORIGINALYEAR", "OriginalYear"):
                    val = _safe_get(raw, f"TXXX:{desc}")
                    if val is not None:
                        text = str(val[0] if isinstance(val, list) else val)
                        tags["originalyear"] = text.strip()[:4]
                        break
            if not tags.get("originaldate"):
                for desc in ("ORIGINALDATE", "originaldate", "OriginalDate"):
                    val = _safe_get(raw, f"TXXX:{desc}")
                    if val is not None:
                        text = str(val[0] if isinstance(val, list) else val)
                        tags["originaldate"] = text.strip()
                        break
    except (MutagenError, OSError, ValueError):
        pass


class FileReorganizer:
    """Scans a directory, evaluates patterns, and copies/moves files."""

    def __init__(
        self,
        specific_pattern: str,
        various_pattern: str,
        base_dir: str,
        action: str = "copy",
        dry_run: bool = False,
    ) -> None:
        self.specific_pattern = specific_pattern
        self.various_pattern = various_pattern
        self.base_dir = base_dir
        self.action = action.lower()
        self.dry_run = dry_run
        self.stats = ReorganizerStats()
        self._stop_requested = False

    def stop(self) -> None:
        self._stop_requested = True

    def _choose_pattern(self, tags: dict[str, str]) -> str:
        """Select pattern based on whether album artist is 'Various Artists'."""
        aa = tags.get("albumartist", "")
        if aa.lower() in VARIOUS_ARTISTS_ALIASES:
            return self.various_pattern
        return self.specific_pattern

    def run(
        self,
        source_dir: str,
        progress_callback: ProgressCallback | None = None,
    ) -> ReorganizerStats:
        self.stats = ReorganizerStats()
        self._stop_requested = False
        source_path = Path(source_dir)

        for entry in sorted(source_path.rglob("*")):
            if self._stop_requested:
                break
            if not entry.is_file():
                continue
            ext = entry.suffix.lower()
            if ext not in SUPPORTED_EXTENSIONS:
                continue

            self.stats.files_scanned += 1
            file_path = str(entry)

            try:
                tags = _read_all_tags(file_path)
                if not tags.get("album") and not tags.get("title"):
                    self.stats.files_skipped += 1
                    if progress_callback:
                        progress_callback(
                            f"SKIPPED (no tags): {os.path.basename(file_path)}",
                            self.stats,
                        )
                    continue

                pattern = self._choose_pattern(tags)
                target_rel = resolve_path(pattern, tags)
                if not target_rel:
                    self.stats.files_skipped += 1
                    if progress_callback:
                        progress_callback(
                            f"SKIPPED (empty path): {os.path.basename(file_path)}",
                            self.stats,
                        )
                    continue

                # Append source file extension if the resolved path lacks one
                if not os.path.splitext(target_rel)[1]:
                    target_rel += entry.suffix

                target_path = os.path.join(self.base_dir, target_rel)
                self._perform_action(file_path, target_path)

                self.stats.files_processed += 1
                if progress_callback:
                    progress_callback(target_rel, self.stats)

            except PatternError as exc:
                logger.warning("Pattern error for %s: %s", file_path, exc)
                self.stats.errors += 1
                if progress_callback:
                    progress_callback(
                        f"PATTERN ERROR: {os.path.basename(file_path)}", self.stats
                    )
            except (OSError, ValueError) as exc:
                logger.error("Error processing %s: %s", file_path, exc, exc_info=True)
                self.stats.errors += 1
                if progress_callback:
                    progress_callback(
                        f"ERROR: {os.path.basename(file_path)}", self.stats
                    )

        return self.stats

    def _perform_action(self, source: str, target: str) -> None:
        if self.dry_run:
            logger.info("[DRY-RUN] %s -> %s", source, target)
            return
        from audio_suite_shared.batch_undo import record_file_reorg_snapshot

        record_file_reorg_snapshot(source, target, self.action)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        if self.action == "copy":
            shutil.copy2(source, target)
            logger.debug("Copied %s -> %s", source, target)
        elif self.action == "move":
            shutil.move(source, target)
            logger.debug("Moved %s -> %s", source, target)
