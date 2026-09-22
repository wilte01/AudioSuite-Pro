"""completeness.py — Tag completeness analysis for Library Statistics.

Walks a directory tree and reports what percentage of audio files carry
each metadata tag (BPM, key, genre, mood, tempo marking, embedded album
art, ReplayGain).  All data is read-only — no analysis or tag writing is
performed — and every field delegates to ``audio_suite_shared`` readers so
file-format differences are handled uniformly.
"""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from audio_suite_shared.audio_formats import SUPPORTED_EXTENSIONS

_logger = logging.getLogger(__name__)

# Field order is the canonical display order everywhere (GUI, CLI, exports).
TAG_FIELDS: tuple[str, ...] = (
    "bpm",
    "key",
    "genre",
    "mood",
    "tempo_marking",
    "album_art",
    "replaygain",
)

TAG_LABELS: dict[str, str] = {
    "bpm": "BPM",
    "key": "Key",
    "genre": "Genre",
    "mood": "Mood",
    "tempo_marking": "Tempo Marking",
    "album_art": "Album Art",
    "replaygain": "ReplayGain",
}


@dataclass(frozen=True)
class TagCompleteness:
    """Completeness tally for a single tag field."""

    field: str
    total: int
    present: int
    missing: int
    pct_complete: float  # 0.0–100.0
    missing_files: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        """Human-readable tag name for display."""
        return TAG_LABELS.get(self.field, self.field)


@dataclass(frozen=True)
class CompletenessReport:
    """Aggregated tag-completeness results for one scanned directory."""

    directory: str
    total_files: int
    tag_results: dict[str, TagCompleteness] = field(default_factory=dict)
    overall_pct: float = 0.0  # 0.0–100.0
    duration_secs: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a JSON-friendly dict (includes per-file missing lists)."""
        return {
            "directory": self.directory,
            "total_files": self.total_files,
            "overall_pct": self.overall_pct,
            "duration_secs": self.duration_secs,
            "tag_results": {
                k: {
                    "field": v.field,
                    "total": v.total,
                    "present": v.present,
                    "missing": v.missing,
                    "pct_complete": v.pct_complete,
                    "missing_files": list(v.missing_files),
                }
                for k, v in self.tag_results.items()
            },
        }


def _tag_presence(path: str) -> dict[str, bool]:
    """Read every tracked field for one file.

    Args:
        path: Path to the audio file.

    Returns:
        Dict mapping each field in ``TAG_FIELDS`` to whether a usable value
        was found.
    """
    from audio_suite_shared.tag_helper_reader import (
        has_artwork,
        read_bpm,
        read_genre,
        read_key,
        read_mood,
        read_replaygain,
        read_tempo_marking,
    )

    def _present(value: Any) -> bool:
        if isinstance(value, tuple):
            return any(v is not None for v in value)
        return value is not None and value is not False

    return {
        "bpm": _present(read_bpm(path)),
        "key": _present(read_key(path)),
        "genre": _present(read_genre(path)),
        "mood": _present(read_mood(path)),
        "tempo_marking": _present(read_tempo_marking(path)),
        "album_art": _present(has_artwork(path)),
        "replaygain": _present(read_replaygain(path)),
    }


def analyse_completeness(
    directory: str | os.PathLike[str],
    *,
    progress_callback: Callable[[int, int], None] | None = None,
) -> CompletenessReport:
    """Scan *directory* and report tag completeness for each tracked field.

    Unreadable files (e.g. write-protected or corrupt) count every field as
    missing, matching the dashboard's "unknown equals missing" semantics.

    Args:
        directory: Root directory to scan (recursive).
        progress_callback: Optional ``(processed, total)`` callback invoked
            after each audio file is scanned.

    Returns:
        Populated :class:`CompletenessReport`.
    """
    directory = os.path.normpath(str(directory))
    start = time.monotonic()

    if not os.path.isdir(directory):
        return CompletenessReport(directory=directory, total_files=0, overall_pct=0.0)

    counts: dict[str, int] = {f: 0 for f in TAG_FIELDS}
    missing_files: dict[str, list[str]] = {f: [] for f in TAG_FIELDS}
    total = 0
    processed = 0

    for root, _dirs, files in os.walk(directory):
        for name in files:
            if not name.lower().endswith(SUPPORTED_EXTENSIONS):
                continue
            full = os.path.join(root, name)
            total += 1

            presence: dict[str, bool] = {f: False for f in TAG_FIELDS}
            # Deliberate broad safety net (not narrowed): the shared tag
            # facades can surface any error type while parsing a corrupt or
            # write-protected file, and one unreadable file must never abort
            # the whole completeness walk.
            try:
                presence = _tag_presence(full)
            except Exception as exc:
                _logger.debug(
                    "Completeness scan skipping unreadable file %s (%s: %s)",
                    full,
                    type(exc).__name__,
                    exc,
                    exc_info=True,
                )

            for tag_field in TAG_FIELDS:
                if presence.get(tag_field, False):
                    counts[tag_field] += 1
                else:
                    missing_files[tag_field].append(full)

            processed += 1
            if progress_callback is not None:
                progress_callback(processed, total)

    tag_results: dict[str, TagCompleteness] = {}
    for tag_field in TAG_FIELDS:
        present = counts[tag_field]
        missing = total - present
        pct = (present / total * 100.0) if total else 0.0
        tag_results[tag_field] = TagCompleteness(
            field=tag_field,
            total=total,
            present=present,
            missing=missing,
            pct_complete=round(pct, 1),
            missing_files=tuple(sorted(missing_files[tag_field])),
        )

    checks = total * len(TAG_FIELDS) if total else 0
    overall = sum(counts.values()) / checks * 100.0 if checks else 0.0

    return CompletenessReport(
        directory=directory,
        total_files=total,
        tag_results=tag_results,
        overall_pct=round(overall, 1),
        duration_secs=round(time.monotonic() - start, 2),
    )


def export_completeness_csv(report: CompletenessReport, output_path: str) -> None:
    """Write the per-tag completeness table as CSV.

    Args:
        report: Populated completeness report.
        output_path: Destination CSV path (written in UTF-8).
    """
    import csv as csv_mod

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv_mod.writer(f)
        writer.writerow(["tag", "total", "present", "missing", "pct_complete"])
        for field in TAG_FIELDS:
            tr = report.tag_results[field]
            writer.writerow(
                [tr.label, tr.total, tr.present, tr.missing, tr.pct_complete]
            )


def export_completeness_json(report: CompletenessReport, output_path: str) -> None:
    """Write the full completeness report as JSON, including missing-file lists.

    Args:
        report: Populated completeness report.
        output_path: Destination JSON path (written in UTF-8).
    """
    import json as json_mod

    with open(output_path, "w", encoding="utf-8") as f:
        json_mod.dump(report.to_dict(), f, indent=2, default=str)
