"""
Tests for audio_suite_shared.dsp_chain.

Covers the shared enhancement chain builder, RMS measurement on normalized
float arrays, and the post-DSP clipping detection added by Phase 7 of the
DSP normalization plan.

Changed in 1.1.0: added the effect-builder and
apply_enhancement_chain orchestrator tests.
Changed in 2.1.3: replaced the ``apply_effects=False`` bypass test with
``test_has_no_bypass_parameter`` and
``test_configured_effects_are_always_applied`` (R-09).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest
from pedalboard import Pedalboard

from audio_suite_shared.dsp_chain import (
    apply_enhancement_chain,
    apply_flanger,
    apply_pre_chain_effects,
    build_enhancement_chain,
    compute_rms_db,
    post_chain_clip_check,
)

LOGGER_NAME = "audio_suite.audio_suite_shared.dsp_chain"
SR = 48_000


def _chain_params() -> SimpleNamespace:
    """Duck-typed stand-in exposing the attribute names the chain builder needs.

    build_enhancement_chain intentionally accepts any object exposing the
    documented attributes, so a lightweight namespace avoids coupling this
    shared test to audio_enhancer's models.
    """
    return SimpleNamespace(
        noise_gate_threshold_db=-50.0,
        compressor_threshold_db=-24.0,
        compressor_ratio=4.0,
        compressor_attack_ms=10.0,
        compressor_release_ms=200.0,
        low_shelf_freq_hz=80.0,
        low_shelf_gain_db=3.0,
        presence_freq_hz=3000.0,
        presence_gain_db=1.5,
        high_shelf_freq_hz=8000.0,
        high_shelf_gain_db=1.0,
        output_gain_db=0.0,
        limiter_threshold_db=-1.0,
    )


def _effect_params(**overrides: object) -> SimpleNamespace:
    """Base chain params plus the Sprint 1 effect fields (all off by default)."""
    base = vars(_chain_params())
    base.update(
        reverse=False,
        karaoke=False,
        karaoke_strength=1.0,
        phaser=False,
        flanger=False,
        chorus=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _stereo_sine(freq_hz: float = 440.0, n: int = SR) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / SR
    wave = np.sin(2.0 * np.pi * freq_hz * t)
    return np.tile(wave, (2, 1)).astype(np.float64)


def _stereo_centre_and_side(n: int = SR) -> np.ndarray:
    """L = centre + side, R = centre − side, so L−R recovers the side only."""
    t = np.arange(n, dtype=np.float64) / SR
    centre = np.sin(2.0 * np.pi * 440.0 * t)
    side = np.sin(2.0 * np.pi * 1200.0 * t)
    return np.stack([centre + side, centre - side]).astype(np.float64)


class TestPostChainClipCheck:
    def test_returns_input_unchanged(self):
        data = np.full(100, 0.5, dtype=np.float32)
        out = post_chain_clip_check(data, stage_name="unittest")
        assert out is data

    def test_never_mutates_input(self):
        data = np.full(100, 1.0, dtype=np.float32)
        out = post_chain_clip_check(data, stage_name="unittest")
        np.testing.assert_array_equal(out, data)

    def test_warning_when_peak_above_headroom(self, caplog):
        # 0 dBFS exceeds the -0.5 dBFS headroom target → warning logged.
        data = np.full(100, 1.0, dtype=np.float32)
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            post_chain_clip_check(data, stage_name="Enhance")
        messages = [r.getMessage() for r in caplog.records]
        assert any("Enhance" in m for m in messages)
        assert any("Clipping risk" in m for m in messages)

    def test_no_warning_with_headroom(self, caplog):
        # 0.5 amplitude is -6 dBFS → within the -0.5 dBFS target.
        data = np.full(100, 0.5, dtype=np.float32)
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            post_chain_clip_check(data)
        assert not caplog.records

    def test_silence_no_warning(self, caplog):
        data = np.zeros(100, dtype=np.float32)
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            post_chain_clip_check(data)
        assert not caplog.records

    def test_default_stage_name_is_dsp_chain(self, caplog):
        data = np.full(100, 1.0, dtype=np.float32)
        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            post_chain_clip_check(data)
        assert any("[dsp_chain]" in r.getMessage() for r in caplog.records)


class TestComputeRmsDb:
    def test_known_signal(self):
        data = np.full(100, 0.5, dtype=np.float32)
        assert np.isclose(compute_rms_db(data), 20 * np.log10(0.5), atol=1e-3)

    def test_full_scale(self):
        data = np.full(100, 1.0, dtype=np.float32)
        assert np.isclose(compute_rms_db(data), 0.0, atol=1e-3)

    def test_silence_returns_minus_180(self):
        data = np.zeros(100, dtype=np.float32)
        assert compute_rms_db(data) == pytest.approx(-180.0)


class TestBuildEnhancementChain:
    def test_returns_pedalboard(self):
        chain = build_enhancement_chain(_chain_params())
        assert isinstance(chain, Pedalboard)

    def test_has_seven_plugins(self):
        chain = build_enhancement_chain(_chain_params())
        assert len(chain) == 7

    def test_plugin_order(self):
        names = [type(p).__name__ for p in build_enhancement_chain(_chain_params())]
        assert names == [
            "NoiseGate",
            "Compressor",
            "LowShelfFilter",
            "PeakFilter",
            "HighShelfFilter",
            "Gain",
            "Limiter",
        ]


class TestBuildEnhancementChainEffects:
    """D17: Phaser/Chorus are inserted post-EQ, pre-Gain; flanger is numpy."""

    def test_phaser_inserted_before_gain(self):
        names = [
            type(p).__name__
            for p in build_enhancement_chain(_effect_params(phaser=True))
        ]
        assert names == [
            "NoiseGate",
            "Compressor",
            "LowShelfFilter",
            "PeakFilter",
            "HighShelfFilter",
            "Phaser",
            "Gain",
            "Limiter",
        ]

    def test_chorus_inserted_before_gain(self):
        names = [
            type(p).__name__
            for p in build_enhancement_chain(_effect_params(chorus=True))
        ]
        assert names[-3:] == ["Chorus", "Gain", "Limiter"]

    def test_phaser_then_chorus_order(self):
        names = [
            type(p).__name__
            for p in build_enhancement_chain(_effect_params(phaser=True, chorus=True))
        ]
        assert names[-4:] == ["Phaser", "Chorus", "Gain", "Limiter"]

    def test_missing_effect_attrs_default_off(self):
        """A params object predating the effects yields the 7-plugin board."""
        assert len(build_enhancement_chain(_chain_params())) == 7


class TestApplyPreChainEffects:
    def test_no_effects_returns_input_unchanged(self):
        audio = _stereo_sine()
        out = apply_pre_chain_effects(audio, _effect_params())
        np.testing.assert_array_equal(out, audio)

    def test_missing_effect_attrs_is_noop(self):
        audio = _stereo_sine()
        out = apply_pre_chain_effects(audio, _chain_params())
        np.testing.assert_array_equal(out, audio)

    def test_reverse_flips_time_axis(self):
        audio = np.arange(20, dtype=np.float64).reshape(2, 10)
        out = apply_pre_chain_effects(audio, _effect_params(reverse=True))
        assert out.shape == audio.shape
        np.testing.assert_array_equal(out[:, 0], audio[:, -1])
        np.testing.assert_array_equal(out[:, -1], audio[:, 0])

    def test_karaoke_full_strength_cancels_centre(self):
        audio = _stereo_centre_and_side()
        out = apply_pre_chain_effects(
            audio, _effect_params(karaoke=True, karaoke_strength=1.0)
        )
        # Fully-processed output is the side signal on L and its inverse on R.
        assert np.max(np.abs(out[0] + out[1])) < 1e-9

    def test_karaoke_zero_strength_is_transparent(self):
        audio = _stereo_centre_and_side()
        out = apply_pre_chain_effects(
            audio, _effect_params(karaoke=True, karaoke_strength=0.0)
        )
        np.testing.assert_allclose(out, audio, atol=1e-12)

    def test_karaoke_mono_input_unchanged(self):
        mono = np.sin(np.arange(64, dtype=np.float64)).reshape(1, 64)
        out = apply_pre_chain_effects(
            mono, _effect_params(karaoke=True, karaoke_strength=1.0)
        )
        np.testing.assert_array_equal(out, mono)

    def test_reverse_applied_before_karaoke(self):
        """D17 order: reverse runs first, so karaoke sees reversed samples."""
        audio = _stereo_centre_and_side()
        out = apply_pre_chain_effects(
            audio, _effect_params(reverse=True, karaoke=True, karaoke_strength=1.0)
        )
        manual = apply_pre_chain_effects(
            apply_pre_chain_effects(audio, _effect_params(reverse=True)),
            _effect_params(karaoke=True, karaoke_strength=1.0),
        )
        np.testing.assert_allclose(out, manual, atol=1e-12)


class TestApplyFlanger:
    def test_shape_and_dtype_preserved(self):
        audio = _stereo_sine()
        out = apply_flanger(audio, SR)
        assert out.shape == audio.shape
        assert out.dtype == audio.dtype

    def test_output_is_finite_and_changed(self):
        audio = _stereo_sine()
        out = apply_flanger(audio, SR)
        assert np.all(np.isfinite(out))
        assert not np.array_equal(out, audio)

    def test_empty_input_is_safe(self):
        audio = np.zeros((2, 0), dtype=np.float64)
        out = apply_flanger(audio, SR)
        assert out.shape == (2, 0)

    def test_mix_zero_is_transparent(self):
        audio = _stereo_sine()
        out = apply_flanger(audio, SR, mix=0.0)
        np.testing.assert_allclose(out, audio, atol=1e-12)


class TestApplyEnhancementChain:
    def _base(self, params: SimpleNamespace) -> np.ndarray:
        return build_enhancement_chain(params)(_stereo_sine(), SR)

    def test_has_no_bypass_parameter(self):
        """There is no way to ask the chain for a different signal (R-09)."""
        import inspect

        assert (
            "apply_effects" not in inspect.signature(apply_enhancement_chain).parameters
        )
        with pytest.raises(TypeError):
            apply_enhancement_chain(
                _stereo_sine(), SR, _effect_params(), apply_effects=False
            )

    def test_configured_effects_are_always_applied(self):
        """An enabled effect changes the output whether or not a caller is
        previewing - the difference a bypass would have hidden."""
        params = _effect_params(karaoke=True)
        audio = _stereo_sine()
        out = apply_enhancement_chain(audio, SR, params)
        expected = build_enhancement_chain(params)(audio, SR)
        assert compute_rms_db(expected) - compute_rms_db(out) > 6.0

    def test_all_effects_off_equals_base_chain(self):
        params = _effect_params()
        audio = _stereo_sine()
        out = apply_enhancement_chain(audio, SR, params)
        expected = build_enhancement_chain(params)(audio, SR)
        np.testing.assert_array_equal(out, expected)

    def test_flanger_path_finite(self):
        params = _effect_params(phaser=True, flanger=True, chorus=True)
        out = apply_enhancement_chain(_stereo_sine(), SR, params)
        assert out.shape == (2, SR)
        assert np.all(np.isfinite(out))

    def test_flanger_path_differs_from_no_flanger(self):
        audio = _stereo_sine()
        with_flanger = apply_enhancement_chain(audio, SR, _effect_params(flanger=True))
        without = apply_enhancement_chain(audio, SR, _effect_params())
        assert not np.array_equal(with_flanger, without)

    def test_reverse_propagates_through_chain(self):
        ramp = np.tile(np.arange(SR, dtype=np.float64), (2, 1))
        out = apply_enhancement_chain(ramp, SR, _effect_params(reverse=True))
        # A monotonic ramp reversed must be monotonically decreasing.
        assert out[0, 1] < out[0, 0]
