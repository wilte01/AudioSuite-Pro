"""
core/models.py
Data classes for the Audio Refinery pipeline.

Each stage carries its own parameter dataclass so the pipeline can pass
exactly the right settings to each tool's processing function without any
coupling to the individual tools' internal models.

Changed in 1.1.0: extended EnhanceParams with the five Sprint 1
effect toggles plus karaoke_strength (kept field-parity with the
shared and enhancer classes).

Changed in 2.6.0 (U-04): ``NormaliseParams`` carries the standalone Audio
Normalizer's whole delivery set — true-peak ceiling, LRA target and the
lossless MP3 path — and defaults to the tool's -14 LUFS target, because the
standalone window that used to hold the -16 default is gone.

Changed in 2.3.1: carries this window's change for its module (see
CHANGELOG.md and TECHNICAL_CHANGELOG.md).

Changed in 2.5.0: ``NormaliseParams.album_mode`` (F-E1) selects album
loudness: one gain measured across the whole folder instead of a per-file
measurement.  ``TrimParams`` gains its exact-range fields (F-E3): a millisecond
span to keep, and the choice between a sample-accurate re-encode and a
frame-accurate stream copy.
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


#: The two things the Trim stage can cut by: detected silence, or a range the
#: user names in milliseconds.  Kept here so the CLI, the GUI, the settings
#: loader and the stage engine all validate against one list.
TRIM_MODES: tuple[str, ...] = ("silence", "exact")

#: The mode that reads ``start_ms``/``end_ms``/``duration_ms``.
EXACT_TRIM_MODE = "exact"


@dataclass
class TrimParams:
    """Parameters for the trimming stage.

    ``mode == "silence"`` (the default) trims detected leading/trailing
    silence and ignores the range fields, which is the stage's behaviour before
    F-E3.  ``mode == "exact"`` keeps the configured millisecond span instead:
    ``start_ms`` defaults to 0, and exactly one of ``end_ms``/``duration_ms``
    must be set.  ``copy_mode`` copies the source's frames rather than
    re-encoding them (frame-accurate, not sample-accurate).
    """

    threshold: int = -50  # silence threshold dBFS
    apply_fade: bool = False
    fade_in_ms: int = 500
    fade_out_ms: int = 1000
    mode: str = "silence"
    start_ms: int | None = None
    end_ms: int | None = None
    duration_ms: int | None = None
    copy_mode: bool = False


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
    output_gain_db: float = 0.0
    limiter_threshold_db: float = -0.5
    # Effects (Sprint 1, Item 1.2). All default off so presets and the
    # existing chain output are unchanged unless a caller opts in.
    reverse: bool = False
    karaoke: bool = False
    karaoke_strength: float = 1.0
    phaser: bool = False
    flanger: bool = False
    chorus: bool = False


#: The two normalisation strategies: an FFmpeg loudnorm re-encode, or the
#: lossless MP3 path that rewrites the frame ``global_gain`` in place.  Kept
#: here rather than in a tool package so the CLI, the settings loader and the
#: stage validator cannot drift apart.
NORMALISATION_MODES: tuple[str, ...] = ("normalise", "lossless")


@dataclass
class NormaliseParams:
    """Parameters for loudness normalisation stage.

    ``true_peak`` and ``lra`` are the loudnorm delivery targets the standalone
    Audio Normalizer carried (U-04); without a window to open, they have to be
    settable here or a file normalised by the pipeline could never honour a
    ceiling.  ``mode`` selects the strategy: ``"lossless"`` rewrites an MP3's
    ``global_gain`` in place instead of re-encoding it, and falls back to the
    re-encode for every other format.
    """

    target_lufs: float = -14.0
    tolerance: float = 0.5
    true_peak: float = -1.5
    lra: float = 11.0
    mode: str = "normalise"
    #: Album mode (F-E1): measure the folder as one signal and apply that single
    #: gain to every track.  Off by default, which keeps per-file normalisation
    #: exactly as it was for anyone who does not ask for it.
    album_mode: bool = False


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


@dataclass(frozen=True)
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


@dataclass(frozen=True)
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
