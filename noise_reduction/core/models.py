"""
core/models.py
Data classes for the Noise Reduction tool.

NoiseReductionParams holds all user-configurable settings for both hum
removal and broadband spectral gating.  The standalone tool and the
Audio Refinery pipeline stage share this single source of truth.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import NamedTuple

from pydub import AudioSegment


@dataclass
class NoiseReductionParams:
    """Parameters for noise reduction processing."""

    # Hum removal
    reduce_hum: bool = False
    hum_frequency: int = 60  # 50 or 60 Hz
    hum_harmonics: int = 8  # number of harmonics to filter (1-20)
    hum_quality: float = 30.0  # Q factor for notch filters (1.0-100.0)

    # Broadband noise reduction
    reduce_broadband: bool = False
    noise_start_ms: int = 0  # start of noise profile region
    noise_end_ms: int = 500  # end of noise profile region
    gate_threshold_db: float = 3.0  # gating threshold dB above noise floor

    # Common
    dry_run: bool = False


class NoiseReductionResult(NamedTuple):
    """Result of noise reduction processing."""

    audio: AudioSegment
    energy_before_db: float
    energy_after_db: float
    was_modified: bool
