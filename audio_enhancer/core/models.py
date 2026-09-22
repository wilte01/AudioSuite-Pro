"""
core/models.py
Data classes and enumerations shared across the application.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class PresetName(str, Enum):
    """Audio enhancement preset names."""

    MILD = "Mild"
    MODERATE = "Moderate"
    AGGRESSIVE = "Aggressive"
    CUSTOM = "Custom"


class JobStatus(str, Enum):
    """Audio processing job status values."""

    QUEUED = "Queued"
    PROCESSING = "Processing"
    DONE = "Done"
    ERROR = "Error"
    FAILED = "Failed"
    SKIPPED = "Skipped"


@dataclass(frozen=True)
class EnhancementParams:
    """All DSP parameters for one enhancement pass."""

    noise_gate_threshold_db: float = -65.0
    compressor_threshold_db: float = -22.0
    compressor_ratio: float = 3.5
    compressor_attack_ms: float = 8.0
    compressor_release_ms: float = 120.0
    low_shelf_gain_db: float = 2.5
    low_shelf_freq_hz: float = 100.0
    presence_gain_db: float = 2.5
    presence_freq_hz: float = 3500.0
    high_shelf_gain_db: float = 4.0
    high_shelf_freq_hz: float = 7000.0
    output_gain_db: float = 4.0
    limiter_threshold_db: float = -0.5

    def __post_init__(self) -> None:
        """Validate critical DSP parameters to prevent runtime errors."""
        if self.compressor_ratio <= 0:
            raise ValueError(
                f"compressor_ratio must be > 0, got {self.compressor_ratio}"
            )
        if self.compressor_attack_ms <= 0:
            raise ValueError(
                f"compressor_attack_ms must be > 0, got {self.compressor_attack_ms}"
            )
        if self.compressor_release_ms <= 0:
            raise ValueError(
                f"compressor_release_ms must be > 0, got {self.compressor_release_ms}"
            )
        if self.limiter_threshold_db > 0:
            raise ValueError(
                f"limiter_threshold_db must be <= 0, got {self.limiter_threshold_db}"
            )


PRESETS: dict[PresetName, EnhancementParams] = {
    PresetName.MILD: EnhancementParams(
        noise_gate_threshold_db=-70,
        compressor_threshold_db=-18,
        compressor_ratio=2.5,
        compressor_attack_ms=10,
        compressor_release_ms=150,
        low_shelf_gain_db=1.5,
        low_shelf_freq_hz=120,
        presence_gain_db=1.5,
        presence_freq_hz=3000,
        high_shelf_gain_db=2.0,
        high_shelf_freq_hz=8000,
        output_gain_db=2.0,
        limiter_threshold_db=-1.0,
    ),
    PresetName.MODERATE: EnhancementParams(
        noise_gate_threshold_db=-65,
        compressor_threshold_db=-22,
        compressor_ratio=3.5,
        compressor_attack_ms=8,
        compressor_release_ms=120,
        low_shelf_gain_db=2.5,
        low_shelf_freq_hz=100,
        presence_gain_db=2.5,
        presence_freq_hz=3500,
        high_shelf_gain_db=4.0,
        high_shelf_freq_hz=7000,
        output_gain_db=4.0,
        limiter_threshold_db=-0.5,
    ),
    PresetName.AGGRESSIVE: EnhancementParams(
        noise_gate_threshold_db=-60,
        compressor_threshold_db=-26,
        compressor_ratio=5.0,
        compressor_attack_ms=5,
        compressor_release_ms=80,
        low_shelf_gain_db=3.5,
        low_shelf_freq_hz=80,
        presence_gain_db=3.5,
        presence_freq_hz=4000,
        high_shelf_gain_db=6.0,
        high_shelf_freq_hz=6000,
        output_gain_db=6.0,
        limiter_threshold_db=-0.3,
    ),
}


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
