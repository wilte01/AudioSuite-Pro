"""The channel tool's settings record.

Changed in 2.5.0: new file (PLAN_2026-11-03_2.5.0_feature_wave_1.md F-E6).
"""

from __future__ import annotations

import pytest

from audio_suite_shared import channel_ops
from audio_suite_shared.exceptions import AudioConfigValueError
from channel_tools.core.models import ChannelSettings


class TestDefaults:
    """The unconfigured run states a rule, never an empty setting."""

    def test_the_default_is_the_arithmetic_mean(self) -> None:
        settings = ChannelSettings()
        assert settings.operation == channel_ops.MONO_MEAN
        assert settings.rule == "Mono, arithmetic mean (0.5 x (L + R))"

    def test_the_rule_names_the_width_it_would_apply(self) -> None:
        settings = ChannelSettings(
            operation=channel_ops.STEREO_WIDTH, width_percent=50.0
        )
        assert settings.rule.endswith("width 50 %")

    def test_the_rule_names_the_dual_mono_source(self) -> None:
        settings = ChannelSettings(
            operation=channel_ops.DUAL_MONO, source_channel="right"
        )
        assert settings.rule.endswith("source: right")

    def test_the_rule_names_the_invert_target(self) -> None:
        settings = ChannelSettings(
            operation=channel_ops.INVERT_PHASE, invert_target="left"
        )
        assert settings.rule.endswith("target: left")


class TestValidation:
    """A setting no operation could honour is refused at construction."""

    def test_an_unknown_operation_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="Unknown channel operation"):
            ChannelSettings(operation="bogus")

    def test_a_width_out_of_range_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="Stereo width"):
            ChannelSettings(operation=channel_ops.STEREO_WIDTH, width_percent=500.0)

    def test_an_unknown_source_channel_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="left or the right"):
            ChannelSettings(operation=channel_ops.DUAL_MONO, source_channel="mid")

    def test_an_unknown_invert_target_is_refused(self) -> None:
        with pytest.raises(AudioConfigValueError, match="left, right or both"):
            ChannelSettings(operation=channel_ops.INVERT_PHASE, invert_target="centre")

    def test_stereo_operations_advertise_their_need(self) -> None:
        assert ChannelSettings(operation=channel_ops.STEREO_WIDTH).needs_stereo is True
        assert ChannelSettings().needs_stereo is False
