"""
core/models.py
Data classes and enumerations shared across the application.

Changed in 2.4.1: ``PresetName``, ``EnhancementParams`` and ``PRESETS`` are
re-exported from ``audio_suite_shared.dsp_models`` instead of being defined
here. The two definitions had drifted — class default ``output_gain_db`` of 0.0
here against 4.0 in the shared copy, and a ``(str, Enum)`` base against a plain
``Enum`` — so the pipeline could apply a preset whose label and gain disagreed
with the table the UI displayed
(PLAN_2026-11-03_2.4.1_stop_the_drift.md WP-0).

The processing-result types below stay here for now; their removal is WP-3.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from audio_suite_shared.dsp_models import PRESETS as PRESETS
from audio_suite_shared.dsp_models import (
    EnhancementParams as EnhancementParams,
)
from audio_suite_shared.dsp_models import PresetName as PresetName


class JobStatus(str, Enum):
    """Audio processing job status values."""

    QUEUED = "Queued"
    PROCESSING = "Processing"
    DONE = "Done"
    ERROR = "Error"
    FAILED = "Failed"
    SKIPPED = "Skipped"


@dataclass
class AudioFileInfo:
    """Metadata discovered from an audio file before processing."""

    path: Path
    format: str = ""
    bitrate_kbps: int = 0
    is_vbr: bool = False
    id3_version: int = 3  # 3 = ID3v2.3, 4 = ID3v2.4
    sample_rate: int = 44100
    channels: int = 2
    duration_sec: float = 0.0
    tag_count: int = 0


@dataclass
class ProcessingResult:
    """Outcome of processing one file.

    ``source`` is required for normal processing paths.
    ``display_text`` is populated by the orchestration layer for error/skip
    paths where a canonical source ``Path`` may not be meaningful (e.g. the
    file vanished between discovery and processing).
    """

    source: Path = Path()
    output: Path | None = None
    status: JobStatus = JobStatus.QUEUED
    rms_before_db: float = 0.0
    rms_after_db: float = 0.0
    tags_copied: int = 0
    error_message: str = ""
    display_text: str = ""

    @property
    def gain_db(self) -> float:
        return self.rms_after_db - self.rms_before_db
