"""
core/models.py
Data classes for the Audio Refinery pipeline.

Each stage carries its own parameter dataclass so the pipeline can pass
exactly the right settings to each tool's processing function without any
coupling to the individual tools' internal models.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from noise_reduction.core.models import NoiseReductionParams

# ── Stage enable/disable + per-stage params ───────────────────────────────────


@dataclass
class DeclickParams:
    """Parameters for declick processing stage."""

    sensitivity: float = 0.31  # (0.0, 0.40] — lower = more aggressive
    # NOTE: default changed from 0.1 to 0.31 to match pop_click_remover's
    # corrected default after a threshold-direction bug was fixed there.
    # 0.31 reproduces the effective detection behaviour of the old 0.1
    # default; it was not independently re-tuned.
    max_width_ms: int = 2  # maximum defect width to repair


@dataclass
class TrimParams:
    """Parameters for silence trimming stage."""

    threshold: int = -50  # silence threshold dBFS
    apply_fade: bool = False
    fade_in_ms: int = 500
    fade_out_ms: int = 1000


@dataclass
class EnhanceParams:
    """Parameters for audio enhancement stage."""

    preset: str = "Moderate"  # Mild | Moderate | Aggressive | Custom
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
    # output_gain_db intentionally omitted — suppressed when normaliser is active
    output_gain_db: float = 0.0
    limiter_threshold_db: float = -0.5


@dataclass
class NormaliseParams:
    """Parameters for loudness normalisation stage."""

    target_lufs: float = -16.0
    tolerance: float = 0.5


@dataclass
class StageConfig:
    """Which stages are active and their parameters."""

    declick: bool = True
    trim: bool = True
    enhance: bool = True
    normalise: bool = True
    reduce_noise: bool = False
    dry_run: bool = False

    declick_params: DeclickParams = field(default_factory=DeclickParams)
    trim_params: TrimParams = field(default_factory=TrimParams)
    enhance_params: EnhanceParams = field(default_factory=EnhanceParams)
    normalise_params: NormaliseParams = field(default_factory=NormaliseParams)
    noise_reduction_params: NoiseReductionParams = field(
        default_factory=NoiseReductionParams
    )


# ── Job status ────────────────────────────────────────────────────────────────


class FileStatus(str, Enum):
    """File processing status values."""

    PENDING = "Pending"
    PROCESSING = "Processing"
    DONE = "Done"
    SKIPPED = "Skipped"  # already in completion registry
    ERROR = "Error"


@dataclass
class StageMetrics:
    """Detailed before/after measurements for a pipeline stage."""

    stage: str
    before_values: dict[str, Any] = field(default_factory=dict)
    after_values: dict[str, Any] = field(default_factory=dict)
    processing_time: float = 0.0
    modifications_made: int = 0

    def get_change(self, metric: str) -> Optional[float]:
        """Calculate the change in a metric (after - before)."""
        if metric in self.before_values and metric in self.after_values:
            before = self.before_values[metric]
            after = self.after_values[metric]
            if isinstance(before, (int, float)) and isinstance(after, (int, float)):
                return float(after) - float(before)
        return None


@dataclass
class StageResult:
    """Outcome of a single stage for one file."""

    stage: str
    status: FileStatus = FileStatus.DONE
    message: str = ""
    metrics: Optional[StageMetrics] = None


@dataclass
class FileResult:
    """Full pipeline outcome for one file."""

    path: Path
    status: FileStatus = FileStatus.PENDING
    stages: list[StageResult] = field(default_factory=list)
    error: Optional[str] = None
    was_modified: bool = False
    total_processing_time: float = 0.0

    def add_stage(
        self,
        stage: str,
        status: FileStatus,
        message: str = "",
        metrics: Optional[StageMetrics] = None,
    ) -> None:
        """Add a stage result with optional metrics."""
        self.stages.append(
            StageResult(stage=stage, status=status, message=message, metrics=metrics)
        )

    def get_stage_metrics(self, stage: str) -> Optional[StageMetrics]:
        """Get metrics for a specific stage."""
        for stage_result in self.stages:
            if stage_result.stage == stage:
                return stage_result.metrics
        return None
