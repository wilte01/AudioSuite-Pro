"""
test_dsp_models.py — Unit tests for audio_suite_shared.dsp_models

Covers:
    • PresetName enum completeness and string values
    • EnhancementParams default field values and DSP safety constraints
    • PRESETS dictionary keys, completeness, and per-preset constraint validation
    • Dataclass mutability and field independence between instances
"""

from __future__ import annotations

import pytest

from audio_suite_shared.dsp_models import PRESETS, EnhancementParams, PresetName
from audio_suite_shared.exceptions import AudioConfigValueError

# ---------------------------------------------------------------------------
# PresetName enum
# ---------------------------------------------------------------------------


class TestPresetNameEnum:
    """Tests for the PresetName enumeration."""

    def test_all_expected_members_present(self) -> None:
        """All four preset names must be present."""
        expected = {"MILD", "MODERATE", "AGGRESSIVE", "CUSTOM"}
        actual = {m.name for m in PresetName}
        assert actual == expected

    def test_string_values_are_title_case(self) -> None:
        """Enum values must be capitalised title-case strings."""
        assert PresetName.MILD.value == "Mild"
        assert PresetName.MODERATE.value == "Moderate"
        assert PresetName.AGGRESSIVE.value == "Aggressive"
        assert PresetName.CUSTOM.value == "Custom"

    def test_enum_lookup_by_value(self) -> None:
        """Enum must be reachable by value as well as name."""
        assert PresetName("Mild") is PresetName.MILD
        assert PresetName("Aggressive") is PresetName.AGGRESSIVE

    def test_invalid_value_raises(self) -> None:
        """Looking up a non-existent value must raise ValueError."""
        with pytest.raises(ValueError):
            PresetName("NonExistent")


# ---------------------------------------------------------------------------
# EnhancementParams defaults and DSP safety constraints
# ---------------------------------------------------------------------------


class TestEnhancementParamsDefaults:
    """Tests for EnhancementParams default values and DSP invariants."""

    @staticmethod
    @pytest.fixture()
    def default_params() -> EnhancementParams:
        """Return a default EnhancementParams instance."""
        return EnhancementParams()

    def test_default_noise_gate_is_negative_db(
        self, default_params: EnhancementParams
    ) -> None:
        """Noise gate threshold must be negative dB."""
        assert default_params.noise_gate_threshold_db < 0.0

    def test_default_compressor_threshold_is_negative_db(
        self, default_params: EnhancementParams
    ) -> None:
        """Compressor threshold must be negative dB."""
        assert default_params.compressor_threshold_db < 0.0

    def test_default_compressor_ratio_greater_than_one(
        self, default_params: EnhancementParams
    ) -> None:
        """Compressor ratio must be ≥ 1:1 (unity or compression)."""
        assert default_params.compressor_ratio >= 1.0

    def test_default_attack_and_release_positive_ms(
        self, default_params: EnhancementParams
    ) -> None:
        """Attack and release times must be positive milliseconds."""
        assert default_params.compressor_attack_ms > 0.0
        assert default_params.compressor_release_ms > 0.0

    def test_default_shelf_frequencies_in_audible_range(
        self, default_params: EnhancementParams
    ) -> None:
        """EQ shelf frequencies must be in the audible range (20 Hz – 20 kHz)."""
        assert 20.0 <= default_params.low_shelf_freq_hz <= 20_000.0
        assert 20.0 <= default_params.presence_freq_hz <= 20_000.0
        assert 20.0 <= default_params.high_shelf_freq_hz <= 20_000.0

    def test_default_limiter_below_zero_dbfs(
        self, default_params: EnhancementParams
    ) -> None:
        """Limiter threshold must be below 0 dBFS to prevent digital clipping."""
        assert default_params.limiter_threshold_db < 0.0

    def test_default_high_shelf_above_low_shelf_frequency(
        self, default_params: EnhancementParams
    ) -> None:
        """High-shelf frequency must be above low-shelf frequency."""
        assert default_params.high_shelf_freq_hz > default_params.low_shelf_freq_hz

    def test_all_fields_are_floats(self, default_params: EnhancementParams) -> None:
        """Every numeric field must be a float (not int) at default instantiation."""
        float_fields = [
            "noise_gate_threshold_db",
            "compressor_threshold_db",
            "compressor_ratio",
            "compressor_attack_ms",
            "compressor_release_ms",
            "low_shelf_gain_db",
            "low_shelf_freq_hz",
            "presence_gain_db",
            "presence_freq_hz",
            "high_shelf_gain_db",
            "high_shelf_freq_hz",
            "output_gain_db",
            "limiter_threshold_db",
        ]
        for field in float_fields:
            assert isinstance(getattr(default_params, field), float), (
                f"Field '{field}' should be float"
            )

    def test_dataclass_instances_are_independent(self) -> None:
        """Replacing a field on one instance must not affect another."""
        from dataclasses import replace

        p1 = EnhancementParams()
        p2 = EnhancementParams()
        p1_replaced = replace(p1, output_gain_db=99.0)
        assert p2.output_gain_db != 99.0
        assert p1_replaced.output_gain_db == 99.0

    def test_dataclass_is_frozen(self) -> None:
        """EnhancementParams must be immutable (frozen)."""
        p = EnhancementParams()
        with pytest.raises(AttributeError):
            p.output_gain_db = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EnhancementParams validation (__post_init__)
# ---------------------------------------------------------------------------


class TestEnhancementParamsValidation:
    """Tests for __post_init__ validation rules."""

    def test_compressor_ratio_zero_raises(self) -> None:
        """compressor_ratio == 0 must raise AudioConfigValueError."""
        with pytest.raises(AudioConfigValueError, match="compressor_ratio"):
            EnhancementParams(compressor_ratio=0.0)

    def test_compressor_ratio_negative_raises(self) -> None:
        """Negative compressor_ratio must raise AudioConfigValueError."""
        with pytest.raises(AudioConfigValueError, match="compressor_ratio"):
            EnhancementParams(compressor_ratio=-1.0)

    def test_compressor_attack_ms_zero_raises(self) -> None:
        """compressor_attack_ms == 0 must raise AudioConfigValueError."""
        with pytest.raises(AudioConfigValueError, match="compressor_attack_ms"):
            EnhancementParams(compressor_attack_ms=0.0)

    def test_compressor_attack_ms_negative_raises(self) -> None:
        """Negative compressor_attack_ms must raise AudioConfigValueError."""
        with pytest.raises(AudioConfigValueError, match="compressor_attack_ms"):
            EnhancementParams(compressor_attack_ms=-5.0)

    def test_compressor_release_ms_zero_raises(self) -> None:
        """compressor_release_ms == 0 must raise AudioConfigValueError."""
        with pytest.raises(AudioConfigValueError, match="compressor_release_ms"):
            EnhancementParams(compressor_release_ms=0.0)

    def test_compressor_release_ms_negative_raises(self) -> None:
        """Negative compressor_release_ms must raise AudioConfigValueError."""
        with pytest.raises(AudioConfigValueError, match="compressor_release_ms"):
            EnhancementParams(compressor_release_ms=-10.0)

    def test_limiter_threshold_positive_raises(self) -> None:
        """Positive limiter_threshold_db must raise AudioConfigValueError."""
        with pytest.raises(AudioConfigValueError, match="limiter_threshold_db"):
            EnhancementParams(limiter_threshold_db=1.0)

    def test_limiter_threshold_zero_is_valid(self) -> None:
        """limiter_threshold_db == 0 must be accepted."""
        p = EnhancementParams(limiter_threshold_db=0.0)
        assert p.limiter_threshold_db == 0.0

    def test_valid_params_pass(self) -> None:
        """All-default params must pass validation."""
        p = EnhancementParams()
        assert p.compressor_ratio > 0
        assert p.compressor_attack_ms > 0
        assert p.compressor_release_ms > 0
        assert p.limiter_threshold_db <= 0


# ---------------------------------------------------------------------------
# PRESETS dictionary
# ---------------------------------------------------------------------------


class TestPresets:
    """Tests for the PRESETS dictionary and per-preset DSP constraints."""

    def test_all_named_presets_present(self) -> None:
        """MILD, MODERATE, and AGGRESSIVE presets must all exist."""
        assert PresetName.MILD in PRESETS
        assert PresetName.MODERATE in PRESETS
        assert PresetName.AGGRESSIVE in PRESETS

    def test_custom_not_in_presets(self) -> None:
        """CUSTOM is a user-defined placeholder and must not have a built-in entry."""
        assert PresetName.CUSTOM not in PRESETS

    def test_all_preset_values_are_enhancement_params(self) -> None:
        """Every value in PRESETS must be an EnhancementParams instance."""
        for key, value in PRESETS.items():
            assert isinstance(value, EnhancementParams), (
                f"PRESETS[{key}] is {type(value)}, expected EnhancementParams"
            )

    @pytest.mark.parametrize(
        "preset_key", [PresetName.MILD, PresetName.MODERATE, PresetName.AGGRESSIVE]
    )
    def test_preset_limiter_below_zero_dbfs(self, preset_key: PresetName) -> None:
        """Every preset must have a sub-zero limiter threshold (clipping prevention)."""
        assert PRESETS[preset_key].limiter_threshold_db < 0.0, (
            f"{preset_key.value} preset limiter threshold must be below 0 dBFS"
        )

    @pytest.mark.parametrize(
        "preset_key", [PresetName.MILD, PresetName.MODERATE, PresetName.AGGRESSIVE]
    )
    def test_preset_compressor_ratio_gte_one(self, preset_key: PresetName) -> None:
        """Every preset compressor ratio must be ≥ 1.0."""
        assert PRESETS[preset_key].compressor_ratio >= 1.0

    @pytest.mark.parametrize(
        "preset_key", [PresetName.MILD, PresetName.MODERATE, PresetName.AGGRESSIVE]
    )
    def test_preset_shelf_frequencies_in_audible_range(
        self, preset_key: PresetName
    ) -> None:
        """Every preset shelf frequency must be within the audible range."""
        p = PRESETS[preset_key]
        assert 20.0 <= p.low_shelf_freq_hz <= 20_000.0
        assert 20.0 <= p.presence_freq_hz <= 20_000.0
        assert 20.0 <= p.high_shelf_freq_hz <= 20_000.0

    def test_aggressive_ratio_greater_than_mild(self) -> None:
        """Aggressive preset must have a higher compression ratio than Mild."""
        assert (
            PRESETS[PresetName.AGGRESSIVE].compressor_ratio
            > PRESETS[PresetName.MILD].compressor_ratio
        )

    def test_aggressive_output_gain_gte_mild(self) -> None:
        """Aggressive preset output gain must be >= Mild
        (more processing = more gain)."""
        assert (
            PRESETS[PresetName.AGGRESSIVE].output_gain_db
            >= PRESETS[PresetName.MILD].output_gain_db
        )

    def test_presets_are_independent_copies(self) -> None:
        """Creating a modified copy of a preset must not corrupt the PRESETS dict."""
        from dataclasses import replace

        replace(PRESETS[PresetName.MILD], output_gain_db=999.0)
        assert PRESETS[PresetName.MILD].output_gain_db != 999.0
