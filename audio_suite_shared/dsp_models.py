"""
dsp_models.py — Shared DSP parameter models and presets for the Audio Suite.
"""

from dataclasses import dataclass
from enum import Enum

from audio_suite_shared.exceptions import AudioConfigValueError


class PresetName(Enum):
    """DSP enhancement preset names."""

    MILD = "Mild"
    MODERATE = "Moderate"
    AGGRESSIVE = "Aggressive"
    CUSTOM = "Custom"


@dataclass(frozen=True)
class EnhancementParams:
    """Parameters for the Audio Enhancer DSP chain."""

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

    def __post_init__(self) -> None:
        """Validate critical DSP parameters to prevent runtime errors."""
        if self.compressor_ratio <= 0:
            raise AudioConfigValueError(
                f"compressor_ratio must be > 0, got {self.compressor_ratio}",
                context={"field": "compressor_ratio", "value": self.compressor_ratio},
            )
        if self.compressor_attack_ms <= 0:
            raise AudioConfigValueError(
                f"compressor_attack_ms must be > 0, got {self.compressor_attack_ms}",
                context={
                    "field": "compressor_attack_ms",
                    "value": self.compressor_attack_ms,
                },
            )
        if self.compressor_release_ms <= 0:
            raise AudioConfigValueError(
                f"compressor_release_ms must be > 0, got {self.compressor_release_ms}",
                context={
                    "field": "compressor_release_ms",
                    "value": self.compressor_release_ms,
                },
            )
        if self.limiter_threshold_db > 0:
            raise AudioConfigValueError(
                f"limiter_threshold_db must be <= 0, got {self.limiter_threshold_db}",
                context={
                    "field": "limiter_threshold_db",
                    "value": self.limiter_threshold_db,
                },
            )


PRESETS = {
    PresetName.MILD: EnhancementParams(
        noise_gate_threshold_db=-70.0,
        compressor_threshold_db=-18.0,
        compressor_ratio=2.5,
        compressor_attack_ms=10.0,
        compressor_release_ms=150.0,
        low_shelf_gain_db=1.5,
        low_shelf_freq_hz=120.0,
        presence_gain_db=1.5,
        presence_freq_hz=3000.0,
        high_shelf_gain_db=2.0,
        high_shelf_freq_hz=8000.0,
        output_gain_db=2.0,
        limiter_threshold_db=-1.0,
    ),
    PresetName.MODERATE: EnhancementParams(
        noise_gate_threshold_db=-65.0,
        compressor_threshold_db=-22.0,
        compressor_ratio=3.5,
        compressor_attack_ms=8.0,
        compressor_release_ms=120.0,
        low_shelf_gain_db=2.5,
        low_shelf_freq_hz=100.0,
        presence_gain_db=2.5,
        presence_freq_hz=3500.0,
        high_shelf_gain_db=4.0,
        high_shelf_freq_hz=7000.0,
        output_gain_db=4.0,
        limiter_threshold_db=-0.5,
    ),
    PresetName.AGGRESSIVE: EnhancementParams(
        noise_gate_threshold_db=-60.0,
        compressor_threshold_db=-26.0,
        compressor_ratio=5.0,
        compressor_attack_ms=5.0,
        compressor_release_ms=80.0,
        low_shelf_gain_db=3.5,
        low_shelf_freq_hz=80.0,
        presence_gain_db=3.5,
        presence_freq_hz=4000.0,
        high_shelf_gain_db=6.0,
        high_shelf_freq_hz=6000.0,
        output_gain_db=6.0,
        limiter_threshold_db=-0.3,
    ),
}
