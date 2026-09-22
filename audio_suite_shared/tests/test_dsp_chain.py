"""
Tests for audio_suite_shared.dsp_chain.

Covers the shared enhancement chain builder, RMS measurement on normalized
float arrays, and the post-DSP clipping detection added by Phase 7 of the
DSP normalization plan.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import numpy as np
import pytest
from pedalboard import Pedalboard

from audio_suite_shared.dsp_chain import (
    build_enhancement_chain,
    compute_rms_db,
    post_chain_clip_check,
)

LOGGER_NAME = "audio_suite_shared.dsp_chain"


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
