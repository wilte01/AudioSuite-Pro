"""
dsp_models.py — Shared DSP parameter models and presets for the Audio Suite.

This module is the only definition of the enhancement model: the Audio Enhancer
stage, the Refinery pipeline and their UIs all read these names, so a second
copy cannot apply a different preset than the one a window displays.

``PresetName`` is a ``StrEnum``, so ``f"{preset}"``, ``str(preset)``,
``format(preset)`` and ``json.dumps(preset)`` all render the label ("Mild").
A plain ``(str, Enum)`` mixin compares equal to its value but renders
``PresetName.MILD`` through those four routes on 3.11-3.14, which is how a
label tests correct and displays wrong. Display code reads
:func:`preset_text`.

Changed in 2.4.1: this is now the only definition of the enhancement
model. ``audio_enhancer/core/models.py`` re-exports these names instead
of keeping a second copy that had drifted (class default
``output_gain_db`` 0.0 against 4.0, a ``(str, Enum)`` base against a
plain ``Enum``). ``PresetName`` is a ``StrEnum`` and :func:`preset_text`
is the single display accessor both preset combos read
(PLAN_2026-11-03_2.4.1_stop_the_drift.md WP-0).
"""

from dataclasses import dataclass
from enum import StrEnum

from audio_suite_shared.exceptions import AudioConfigValueError


class PresetName(StrEnum):
    """DSP enhancement preset names."""

    MILD = "Mild"
    MODERATE = "Moderate"
    AGGRESSIVE = "Aggressive"
    CUSTOM = "Custom"


def preset_text(preset: PresetName) -> str:
    """Return the user-facing label for *preset*.

    The single display accessor: a widget, a log line or a settings file reads
    this rather than ``preset.value``, so changing the enum's base class cannot
    silently alter a label again (the ``FingerprintStatus`` trap).

    Args:
        preset: The preset to render.

    Returns:
        The label, e.g. ``"Mild"``.
    """
    return preset.value


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
    output_gain_db: float = 4.0
    limiter_threshold_db: float = -0.5
    # Effects (Sprint 1, Item 1.2). All default off so presets and the
    # existing chain output are unchanged unless a caller opts in.
    reverse: bool = False
    karaoke: bool = False
    karaoke_strength: float = 1.0
    phaser: bool = False
    flanger: bool = False
    chorus: bool = False

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
        if not 0.0 <= self.karaoke_strength <= 1.0:
            raise AudioConfigValueError(
                f"karaoke_strength must be within [0.0, 1.0],"
                f" got {self.karaoke_strength}",
                context={
                    "field": "karaoke_strength",
                    "value": self.karaoke_strength,
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
