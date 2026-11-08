"""The shared channel maths, measured on arrays and on decoded audio.

The assertions are on the samples and levels the operations produce: an
uncorrelated pair tells the two mono rules apart, a decoded file proves the
packing round trip, and every refusal is a named reason rather than a guess.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

import numpy as np
import pytest

from audio_suite_shared import channel_ops
from audio_suite_shared.audio_conversion import (
    measure_rms_db,
    numpy_to_segment,
    segment_to_numpy,
)
from audio_suite_shared.exceptions import AudioConfigValueError

SR = 44_100


def _pair(frames: int = SR // 2) -> np.ndarray:
    """Return an uncorrelated stereo pair: 440 Hz left, 220 Hz right."""
    t = np.arange(frames) / SR
    left = 0.4 * np.sin(2.0 * np.pi * 440.0 * t)
    right = 0.4 * np.sin(2.0 * np.pi * 220.0 * t)
    return np.stack([left, right]).astype(np.float32)


class TestMonoRules:
    """The two downmix rules are both available and measurably different."""

    def test_mean_is_the_arithmetic_average(self) -> None:
        pair = _pair()
        result = channel_ops.apply_operation(pair, channel_ops.MONO_MEAN)
        assert result.audio.shape == (1, pair.shape[1])
        samples = pair.astype(np.float64)
        np.testing.assert_allclose(
            result.audio[0], 0.5 * (samples[0] + samples[1]), rtol=0, atol=1e-12
        )

    def test_centre_rule_is_three_db_above_the_mean_on_an_uncorrelated_pair(
        self,
    ) -> None:
        pair = _pair()
        mean = channel_ops.apply_operation(pair, channel_ops.MONO_MEAN)
        centre = channel_ops.apply_operation(pair, channel_ops.MONO_MINUS3DB)
        assert measure_rms_db(centre.audio) - measure_rms_db(
            mean.audio
        ) == pytest.approx(3.0103, abs=0.01)

    def test_the_centre_rule_is_three_db_above_the_mean_on_a_correlated_pair(
        self,
    ) -> None:
        mono = (0.3 * np.sin(2.0 * np.pi * 300.0 * np.arange(SR // 4) / SR)).astype(
            np.float32
        )
        correlated = np.stack([mono, mono])
        mean = channel_ops.apply_operation(correlated, channel_ops.MONO_MEAN)
        centre = channel_ops.apply_operation(correlated, channel_ops.MONO_MINUS3DB)
        assert measure_rms_db(centre.audio) - measure_rms_db(
            mean.audio
        ) == pytest.approx(3.0103, abs=0.01)

    def test_a_mono_source_is_left_alone(self) -> None:
        mono = np.stack([np.full(100, 0.25, dtype=np.float32)])
        for operation in (channel_ops.MONO_MEAN, channel_ops.MONO_MINUS3DB):
            result = channel_ops.apply_operation(mono, operation)
            assert result.rule.startswith("already mono")
            np.testing.assert_array_equal(result.audio, mono.astype(np.float64))


class TestChannelCopying:
    """Dual mono and phase inversion act on the side they were told to."""

    def test_dual_mono_copies_the_named_channel(self) -> None:
        pair = _pair()
        left = channel_ops.apply_operation(pair, channel_ops.DUAL_MONO)
        np.testing.assert_array_equal(left.audio[0], left.audio[1])
        np.testing.assert_array_equal(left.audio[0], pair[0].astype(np.float64))
        right = channel_ops.apply_operation(
            pair, channel_ops.DUAL_MONO, source_channel="right"
        )
        np.testing.assert_array_equal(right.audio[0], pair[1].astype(np.float64))

    def test_dual_mono_duplicates_a_mono_source(self) -> None:
        mono = np.full((1, 64), 0.5, dtype=np.float32)
        result = channel_ops.apply_operation(mono, channel_ops.DUAL_MONO)
        assert result.audio.shape == (2, 64)
        np.testing.assert_array_equal(result.audio[0], result.audio[1])

    def test_phase_inversion_negates_only_the_named_side(self) -> None:
        pair = _pair()
        result = channel_ops.apply_operation(
            pair, channel_ops.INVERT_PHASE, invert_target="left"
        )
        np.testing.assert_array_equal(result.audio[0], -pair[0].astype(np.float64))
        np.testing.assert_array_equal(result.audio[1], pair[1].astype(np.float64))
        both = channel_ops.apply_operation(pair, channel_ops.INVERT_PHASE)
        np.testing.assert_array_equal(both.audio, -pair.astype(np.float64))


class TestMidSide:
    """Encode and decode are inverses; width is the ratio between them."""

    def test_encode_decode_round_trips_the_samples(self) -> None:
        pair = _pair()
        encoded = channel_ops.apply_operation(pair, channel_ops.MS_ENCODE).audio
        decoded = channel_ops.apply_operation(encoded, channel_ops.MS_DECODE).audio
        np.testing.assert_array_equal(decoded, pair.astype(np.float64))

    def test_encode_writes_mid_then_side(self) -> None:
        pair = _pair()
        encoded = channel_ops.apply_operation(pair, channel_ops.MS_ENCODE).audio
        np.testing.assert_allclose(encoded[0], 0.5 * (pair[0] + pair[1]), atol=1e-12)
        np.testing.assert_allclose(encoded[1], 0.5 * (pair[0] - pair[1]), atol=1e-12)

    def test_zero_width_is_the_mono_mean_on_both_sides(self) -> None:
        pair = _pair()
        zero = channel_ops.apply_operation(
            pair, channel_ops.STEREO_WIDTH, width_percent=0.0
        ).audio
        np.testing.assert_array_equal(zero[0], zero[1])
        np.testing.assert_allclose(zero[0], 0.5 * (pair[0] + pair[1]), atol=1e-12)

    def test_unity_width_changes_nothing(self) -> None:
        pair = _pair()
        result = channel_ops.apply_operation(
            pair, channel_ops.STEREO_WIDTH, width_percent=100.0
        )
        np.testing.assert_array_equal(result.audio, pair.astype(np.float64))
        assert result.rule.endswith("unchanged")

    def test_double_width_lifts_the_side_by_six_db(self) -> None:
        pair = _pair()
        side_before = 0.5 * (pair[0] - pair[1])
        doubled = channel_ops.apply_operation(
            pair, channel_ops.STEREO_WIDTH, width_percent=200.0
        ).audio
        side_after = 0.5 * (doubled[0] - doubled[1])
        assert measure_rms_db(side_after) - measure_rms_db(
            side_before
        ) == pytest.approx(6.0206, abs=0.01)

    def test_a_width_that_would_clip_is_clamped_and_reported(self) -> None:
        loud = np.stack([np.ones(8, dtype=np.float32), -np.ones(8, dtype=np.float32)])
        result = channel_ops.apply_operation(
            loud, channel_ops.STEREO_WIDTH, width_percent=400.0
        )
        assert result.clipped is True
        assert "clamped" in result.rule
        assert float(np.max(np.abs(result.audio))) == pytest.approx(1.0)


class TestDecodedOutcome:
    """The maths survives the pack: a decoded file carries what was computed."""

    def test_a_mono_downmix_decodes_as_one_channel_at_the_mean_level(self) -> None:
        pair = _pair(SR // 4)
        source = numpy_to_segment(pair, SR, sample_width=2, num_channels=2)
        decoded, rate = segment_to_numpy(source)
        assert rate == SR
        result = channel_ops.apply_operation(decoded, channel_ops.MONO_MEAN)
        packed = numpy_to_segment(result.audio, rate, sample_width=2, num_channels=1)
        reread, _ = segment_to_numpy(packed)
        assert reread.shape[0] == 1
        assert measure_rms_db(reread) == pytest.approx(
            measure_rms_db(result.audio), abs=0.01
        )


class TestRefusals:
    """A request that cannot be honoured names why."""

    def test_stereo_operations_refuse_a_mono_source(self) -> None:
        mono = np.full((1, 32), 0.1, dtype=np.float32)
        for operation in (
            channel_ops.MS_ENCODE,
            channel_ops.MS_DECODE,
            channel_ops.STEREO_WIDTH,
        ):
            with pytest.raises(AudioConfigValueError, match="stereo"):
                channel_ops.apply_operation(mono, operation)

    def test_more_than_two_channels_is_refused(self) -> None:
        surround = np.full((6, 32), 0.1, dtype=np.float32)
        with pytest.raises(AudioConfigValueError, match="6 channels"):
            channel_ops.apply_operation(surround, channel_ops.MONO_MEAN)

    def test_an_unknown_operation_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="Unknown channel operation"):
            channel_ops.apply_operation(_pair(8), "not_an_operation")

    @pytest.mark.parametrize("width", [-1.0, 401.0])
    def test_a_width_outside_the_documented_range_is_refused(
        self, width: float
    ) -> None:
        with pytest.raises(AudioConfigValueError, match="Stereo width"):
            channel_ops.apply_operation(
                _pair(8), channel_ops.STEREO_WIDTH, width_percent=width
            )

    def test_inverting_both_sides_needs_stereo(self) -> None:
        mono = np.full((1, 32), 0.1, dtype=np.float32)
        with pytest.raises(AudioConfigValueError, match="stereo"):
            channel_ops.apply_operation(mono, channel_ops.INVERT_PHASE)
        assert channel_ops.apply_operation(
            mono, channel_ops.INVERT_PHASE, invert_target="left"
        ).audio[0][0] == pytest.approx(-0.1)
